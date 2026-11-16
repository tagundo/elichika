package com.klab.lovelive.allstars.fovmod;

import android.graphics.ImageFormat;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.os.Build;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * API21+ bounded offline encoder. This is an encoder backend, not an MV clock,
 * Unity render hook or screen recorder. Only its dedicated worker calls codecs.
 * The Unity producer must retry the SAME frame when offerVideo returns false;
 * it may advance simulation only after the frame has been accepted.
 */
public final class AndroidMVEncoder {
    public static final String AVC = "video/avc";
    public static final String HEVC = "video/hevc";
    private static final int SLOTS = 3;
    private static final int AUDIO_PACKET_FRAMES = 4096;
    private static final int MAX_PENDING_ENCODED_BYTES = 8 * 1024 * 1024;
    private static final long STALL_NS = TimeUnit.SECONDS.toNanos(30);

    public static final class Config {
        public final String mime;
        public final int width, height, fps, videoBitrate, sampleRate, channels, audioBitrate;
        public final long videoFrames, audioFrames;
        /** audioFrames=0/channels=0/sampleRate=0 is a video-only diagnostic probe. */
        public Config(String mime, int width, int height, int fps, int videoBitrate,
                long videoFrames, int sampleRate, int channels, int audioBitrate, long audioFrames) {
            MVExportContract.validateVideo(mime, width, height, fps, videoBitrate, videoFrames);
            boolean audio = audioFrames > 0;
            if (audio ? (sampleRate < 8000 || sampleRate > 96000 || channels < 1 || channels > 2
                    || audioBitrate < 16000) : (audioFrames != 0 || channels != 0 || sampleRate != 0))
                throw new IllegalArgumentException("Invalid PCM/AAC configuration");
            if (audio) MVExportContract.timestampUs(audioFrames, sampleRate);
            this.mime=mime; this.width=width; this.height=height; this.fps=fps;
            this.videoBitrate=videoBitrate; this.videoFrames=videoFrames;
            this.sampleRate=sampleRate; this.channels=channels;
            this.audioBitrate=audioBitrate; this.audioFrames=audioFrames;
        }
        public boolean hasAudio() { return audioFrames > 0; }
    }

    private static final class Packet {
        final boolean audio;
        final byte[] bytes;
        final int count;
        final long index;
        Packet(boolean audio, byte[] bytes, int count, long index) {
            this.audio=audio; this.bytes=bytes; this.count=count; this.index=index;
        }
    }
    private static final class Sample {
        final boolean audio;
        final byte[] bytes;
        final MediaCodec.BufferInfo info;
        Sample(boolean audio, byte[] bytes, MediaCodec.BufferInfo info) {
            this.audio=audio; this.bytes=bytes; this.info=info;
        }
    }

    private final Object guard = new Object();
    private final Config config;
    private final File output, partial;
    private final ArrayBlockingQueue<Packet> queue = new ArrayBlockingQueue<Packet>(SLOTS);
    private final ArrayBlockingQueue<byte[]> videoPool = new ArrayBlockingQueue<byte[]>(SLOTS);
    private final ArrayBlockingQueue<byte[]> audioPool = new ArrayBlockingQueue<byte[]>(SLOTS);
    private final FutureTask<File> result;
    private final long diagnosticWriteDelayMs;
    private volatile boolean cancelled;
    private boolean finishing, terminal;
    private long acceptedVideo, acceptedAudio;
    private MediaCodec videoCodec, audioCodec;
    private MediaMuxer muxer;
    private int videoTrack=-1, audioTrack=-1, pendingBytes;
    private boolean muxStarted, videoOutputEOS, audioOutputEOS;
    private long outputVideoFrames, lastVideoPTS=-1, lastAudioPTS=-1;
    private final ArrayDeque<Sample> pending = new ArrayDeque<Sample>();

    /** The destination must be a new path in app-private storage. */
    public AndroidMVEncoder(Config config, File destination) throws IOException {
        this(config,destination,0);
    }
    /** Package-only device-test seam: delays mux writes to prove backpressure. */
    AndroidMVEncoder(Config config, File destination, long diagnosticWriteDelayMs) throws IOException {
        if (config == null || destination == null) throw new IllegalArgumentException("Missing configuration");
        if (diagnosticWriteDelayMs<0 || diagnosticWriteDelayMs>1000)
            throw new IllegalArgumentException("Invalid diagnostic write delay");
        this.config=config; this.output=destination.getCanonicalFile();
        this.diagnosticWriteDelayMs=diagnosticWriteDelayMs;
        File parent=output.getParentFile();
        if (parent == null || !parent.isDirectory() || !output.createNewFile())
            throw new IOException("Destination must not already exist");
        partial=new File(parent, "."+output.getName()+"."+UUID.randomUUID()+".partial");
        try {
            int bytes=MVExportContract.i420Bytes(config.width,config.height);
            for (int i=0;i<SLOTS;i++) videoPool.add(new byte[bytes]);
            if (config.hasAudio()) for (int i=0;i<SLOTS;i++)
                audioPool.add(new byte[AUDIO_PACKET_FRAMES*config.channels*2]);
        } catch (Throwable error) { output.delete(); throw error; }
        result=new FutureTask<File>(new Callable<File>() { public File call() throws Exception { return encode(); } });
        Thread worker=new Thread(result,"SIFAS-MV-Encoder");
        try { worker.start(); } catch (Throwable error) { output.delete(); throw error; }
    }

    /** Input is limited-range SDR Rec.709 I420, Y then U then V, no row padding. */
    public boolean offerVideo(long frameIndex, ByteBuffer i420) {
        synchronized (guard) {
            open();
            if (frameIndex != acceptedVideo || acceptedVideo >= config.videoFrames || i420 == null
                    || i420.remaining() != MVExportContract.i420Bytes(config.width,config.height))
                throw new IllegalArgumentException("Expected next complete I420 frame");
            byte[] slot=videoPool.poll();
            if (slot == null || queue.remainingCapacity() == 0) {
                if (slot != null) videoPool.add(slot);
                return false;
            }
            i420.get(slot);
            queue.add(new Packet(false,slot,slot.length,acceptedVideo++));
            return true;
        }
    }

    /** PCM16 little endian, interleaved; packets contain 1..4096 sample frames. */
    public boolean offerAudio(long sampleFrameIndex, ByteBuffer pcm) {
        synchronized (guard) {
            open();
            int stride=config.channels*2;
            if (!config.hasAudio() || sampleFrameIndex != acceptedAudio || pcm == null
                    || pcm.remaining() == 0 || pcm.remaining() % stride != 0
                    || pcm.remaining()/stride > AUDIO_PACKET_FRAMES
                    || pcm.remaining()/stride > config.audioFrames-acceptedAudio)
                throw new IllegalArgumentException("Expected next PCM16 packet");
            byte[] slot=audioPool.poll();
            if (slot == null || queue.remainingCapacity() == 0) {
                if (slot != null) audioPool.add(slot);
                return false;
            }
            int count=pcm.remaining(); pcm.get(slot,0,count);
            queue.add(new Packet(true,slot,count,acceptedAudio));
            acceptedAudio+=count/stride;
            return true;
        }
    }

    /** Nonblocking. Call only after every expected video/audio frame was accepted. */
    public void finish() {
        synchronized (guard) {
            open();
            if (acceptedVideo != config.videoFrames || acceptedAudio != config.audioFrames)
                throw new IllegalStateException("Cannot finish an incomplete export");
            finishing=true;
        }
    }
    public void cancel() { synchronized (guard) { if (!terminal) cancelled=true; } }
    public boolean isDone() { return result.isDone(); }
    /** Validate the native simulation/PCM contract before it can own the clock. */
    public boolean matchesConfig(int width,int height,int fps,long frames,
            int sampleRate,int channels,long audioFrames) {
        return config.width==width&&config.height==height&&config.fps==fps&&config.videoFrames==frames&&
                config.sampleRate==sampleRate&&config.channels==channels&&config.audioFrames==audioFrames;
    }
    public File awaitCompletion(long timeout, TimeUnit unit)
            throws InterruptedException, ExecutionException, TimeoutException {
        return result.get(timeout,unit);
    }
    /** Nonblocking completion query for a native Unity-thread pump. */
    public String completedPath() {
        if (!result.isDone()) return null;
        try { return result.get().getPath(); }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
        catch (ExecutionException error) { throw new IllegalStateException("MV encoder failed",error.getCause()); }
    }
    private void open() {
        if (cancelled || terminal || result.isDone() || finishing)
            throw new IllegalStateException("Encoder no longer accepts input");
    }
    private void checkCancelled() throws IOException {
        if (cancelled || Thread.currentThread().isInterrupted()) throw new IOException("Export cancelled");
    }

    private MediaCodec makeVideo() throws IOException {
        MediaFormat format=MediaFormat.createVideoFormat(config.mime,config.width,config.height);
        format.setInteger(MediaFormat.KEY_BIT_RATE,config.videoBitrate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE,config.fps);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,2);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        // Literal keys remain safe to compile/run on API21. Unknown optional keys
        // may be ignored; output timestamps/frame counts are still checked.
        format.setInteger("color-standard",1); // BT.709
        format.setInteger("color-range",2);    // limited
        format.setInteger("color-transfer",3); // SDR video
        format.setInteger("max-bframes",0);
        if (AVC.equals(config.mime)) format.setInteger(MediaFormat.KEY_PROFILE,
                MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
        MediaFormat selection=format;
        if (Build.VERSION.SDK_INT==21) {
            // Lollipop's findEncoderForFormat must not receive KEY_FRAME_RATE.
            // Keep the real configuration intact and check rate separately below.
            selection=MediaFormat.createVideoFormat(config.mime,config.width,config.height);
            selection.setInteger(MediaFormat.KEY_BIT_RATE,config.videoBitrate);
            selection.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            if (AVC.equals(config.mime)) selection.setInteger(MediaFormat.KEY_PROFILE,
                    MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
        }
        String name=new MediaCodecList(MediaCodecList.REGULAR_CODECS).findEncoderForFormat(selection);
        if (name == null) throw new IOException("No encoder supports the requested format");
        MediaCodec codec=MediaCodec.createByCodecName(name);
        try {
            MediaCodecInfo.CodecCapabilities caps=codec.getCodecInfo().getCapabilitiesForType(config.mime);
            MediaCodecInfo.VideoCapabilities video=caps.getVideoCapabilities();
            if (video == null || !video.areSizeAndRateSupported(config.width,config.height,config.fps)
                    || !video.getBitrateRange().contains(config.videoBitrate))
                throw new IOException("Requested size, rate or bitrate is unsupported");
            codec.configure(format,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start(); return codec;
        } catch (Throwable error) { codec.release(); throw error; }
    }
    private MediaCodec makeAudio() throws IOException {
        MediaFormat format=MediaFormat.createAudioFormat("audio/mp4a-latm",config.sampleRate,config.channels);
        format.setInteger(MediaFormat.KEY_AAC_PROFILE,MediaCodecInfo.CodecProfileLevel.AACObjectLC);
        format.setInteger(MediaFormat.KEY_BIT_RATE,config.audioBitrate);
        format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE,AUDIO_PACKET_FRAMES*config.channels*2);
        MediaCodec codec=MediaCodec.createEncoderByType("audio/mp4a-latm");
        try { codec.configure(format,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE); codec.start(); return codec; }
        catch (Throwable error) { codec.release(); throw error; }
    }

    private File encode() throws Exception {
        boolean success=false;
        try {
            videoCodec=makeVideo();
            if (config.hasAudio()) audioCodec=makeAudio();
            else audioOutputEOS=true;
            muxer=new MediaMuxer(partial.getPath(),MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            boolean inputEOS=false;
            long producerDeadline=System.nanoTime()+STALL_NS;
            while (!inputEOS) {
                checkCancelled();
                Packet packet=queue.poll(5,TimeUnit.MILLISECONDS);
                if (packet != null) {
                    try { feed(packet); }
                    finally { (packet.audio?audioPool:videoPool).add(packet.bytes); }
                    producerDeadline=System.nanoTime()+STALL_NS;
                } else {
                    synchronized (guard) { inputEOS=finishing && queue.isEmpty(); }
                    if (!inputEOS && System.nanoTime()>producerDeadline)
                        throw new IOException("MV frame/audio producer stalled");
                }
                drain(false); drain(true);
            }
            feedEOS(false);
            if (config.hasAudio()) feedEOS(true);
            long deadline=System.nanoTime()+STALL_NS;
            while (!videoOutputEOS || !audioOutputEOS) {
                checkCancelled();
                boolean progress=drain(false)|drain(true);
                if (progress) deadline=System.nanoTime()+STALL_NS;
                else { if (System.nanoTime()>deadline) throw new IOException("Encoder EOS stalled"); Thread.sleep(2); }
            }
            if (!muxStarted || !pending.isEmpty() || outputVideoFrames != config.videoFrames)
                throw new IOException("Encoded frame count or tracks are incomplete");
            muxer.stop(); muxStarted=false;
            muxer.release(); muxer=null;
            synchronized (guard) {
                checkCancelled();
                if (!partial.renameTo(output)) throw new IOException("Could not finalize MP4");
                success=true; terminal=true;
            }
            return output;
        } finally {
            // Stop accepting input before any ownership containers are cleared.
            synchronized (guard) { terminal=true; }
            release(videoCodec); release(audioCodec);
            if (muxer != null) { try { muxer.release(); } catch (RuntimeException ignored) {} }
            queue.clear(); pending.clear(); videoPool.clear(); audioPool.clear();
            synchronized (guard) {
                terminal=true;
                if (!success) { partial.delete(); output.delete(); }
            }
        }
    }
    private static void release(MediaCodec codec) {
        if (codec != null) { try { codec.stop(); } catch (RuntimeException ignored) {}
            try { codec.release(); } catch (RuntimeException ignored) {} }
    }
    private void feed(Packet packet) throws Exception {
        MediaCodec codec=packet.audio?audioCodec:videoCodec;
        int consumed=0;
        long deadline=System.nanoTime()+STALL_NS;
        do {
            checkCancelled();
            int index=codec.dequeueInputBuffer(0);
            if (index < 0) {
                boolean progress=drain(false)|drain(true);
                if (progress) deadline=System.nanoTime()+STALL_NS;
                else { if (System.nanoTime()>deadline) throw new IOException("Encoder input stalled"); Thread.sleep(2); }
                continue;
            }
            int length;
            long pts;
            if (packet.audio) {
                ByteBuffer target=codec.getInputBuffer(index);
                if (target == null) throw new IOException("Missing AAC input buffer");
                target.clear();
                int stride=config.channels*2;
                length=Math.min(packet.count-consumed,target.remaining()/stride*stride);
                if (length == 0) throw new IOException("AAC buffer cannot hold one PCM frame");
                target.put(packet.bytes,consumed,length);
                pts=MVExportContract.timestampUs(packet.index+consumed/stride,config.sampleRate);
            } else {
                Image image=codec.getInputImage(index);
                if (image == null) throw new IOException("Encoder does not expose flexible YUV input images");
                writeI420(image,packet.bytes,config.width,config.height);
                // The image is codec-owned until queueInputBuffer; do not close it.
                length=packet.count;
                pts=MVExportContract.timestampUs(packet.index,config.fps);
            }
            codec.queueInputBuffer(index,0,length,pts,0);
            consumed+=length;
            deadline=System.nanoTime()+STALL_NS;
            drain(false); drain(true);
        } while (consumed<packet.count);
    }
    private void feedEOS(boolean audio) throws Exception {
        MediaCodec codec=audio?audioCodec:videoCodec;
        long deadline=System.nanoTime()+STALL_NS;
        for (;;) {
            checkCancelled();
            int index=codec.dequeueInputBuffer(0);
            if (index >= 0) {
                long pts=MVExportContract.timestampUs(audio?config.audioFrames:config.videoFrames,
                        audio?config.sampleRate:config.fps);
                codec.queueInputBuffer(index,0,0,pts,MediaCodec.BUFFER_FLAG_END_OF_STREAM); return;
            }
            boolean progress=drain(false)|drain(true);
            if (progress) deadline=System.nanoTime()+STALL_NS;
            else { if (System.nanoTime()>deadline) throw new IOException("Encoder EOS input stalled"); Thread.sleep(2); }
        }
    }
    private boolean drain(boolean audio) throws IOException {
        MediaCodec codec=audio?audioCodec:videoCodec;
        if (codec == null || (audio?audioOutputEOS:videoOutputEOS)) return false;
        boolean progress=false;
        MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
        for (;;) {
            checkCancelled();
            int index=codec.dequeueOutputBuffer(info,0);
            if (index == MediaCodec.INFO_TRY_AGAIN_LATER) return progress;
            progress=true;
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                if (muxStarted || (audio?audioTrack:videoTrack) >= 0)
                    throw new IOException("Unexpected repeated encoder format");
                int track=muxer.addTrack(codec.getOutputFormat());
                if (audio) audioTrack=track; else videoTrack=track;
                if (videoTrack>=0 && (!config.hasAudio() || audioTrack>=0)) {
                    muxer.start(); muxStarted=true;
                    while (!pending.isEmpty()) { Sample sample=pending.removeFirst(); write(sample); pendingBytes-=sample.bytes.length; }
                }
                continue;
            }
            if (index < 0) continue;
            try {
                if (info.size>0 && (info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0) {
                    long previous=audio?lastAudioPTS:lastVideoPTS;
                    if (info.presentationTimeUs < 0 || info.presentationTimeUs <= previous)
                        throw new IOException("Encoder produced invalid or reordered presentation timestamps");
                    if (audio) lastAudioPTS=info.presentationTimeUs;
                    else {
                        if (outputVideoFrames>=config.videoFrames || info.presentationTimeUs!=
                                MVExportContract.timestampUs(outputVideoFrames,config.fps))
                            throw new IOException("Encoder changed a video frame presentation timestamp");
                        lastVideoPTS=info.presentationTimeUs; outputVideoFrames++;
                    }
                    ByteBuffer buffer=codec.getOutputBuffer(index);
                    if (buffer == null || info.offset<0 || info.size>buffer.capacity()-info.offset)
                        throw new IOException("Invalid encoded output buffer");
                    if (info.size>MAX_PENDING_ENCODED_BYTES ||
                            (!muxStarted && info.size>MAX_PENDING_ENCODED_BYTES-pendingBytes))
                        throw new IOException("Audio/video must be interleaved; format wait buffer is full");
                    byte[] bytes=new byte[info.size];
                    buffer.position(info.offset); buffer.limit(info.offset+info.size); buffer.get(bytes);
                    MediaCodec.BufferInfo copy=new MediaCodec.BufferInfo();
                    copy.set(0,bytes.length,info.presentationTimeUs,info.flags&~MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                    Sample sample=new Sample(audio,bytes,copy);
                    if (muxStarted) write(sample); else { pending.addLast(sample); pendingBytes+=bytes.length; }
                }
                if ((info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0) {
                    if (audio) audioOutputEOS=true; else videoOutputEOS=true;
                    return true;
                }
            } finally { codec.releaseOutputBuffer(index,false); }
        }
    }
    private void write(Sample sample) throws IOException {
        checkCancelled();
        if (diagnosticWriteDelayMs>0) {
            try { Thread.sleep(diagnosticWriteDelayMs); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); checkCancelled(); }
            checkCancelled();
        }
        muxer.writeSampleData(sample.audio?audioTrack:videoTrack,ByteBuffer.wrap(sample.bytes),sample.info);
    }
    private static void writeI420(Image image, byte[] source, int width, int height) throws IOException {
        if (image.getFormat()!=ImageFormat.YUV_420_888 || image.getWidth()<width || image.getHeight()<height
                || image.getPlanes().length!=3 || image.getCropRect().left!=0 || image.getCropRect().top!=0
                || image.getCropRect().width()!=width || image.getCropRect().height()!=height)
            throw new IOException("Unexpected flexible YUV layout");
        int offset=0;
        for (int p=0;p<3;p++) {
            int w=p==0?width:width/2, h=p==0?height:height/2;
            Image.Plane plane=image.getPlanes()[p];
            ByteBuffer target=plane.getBuffer().duplicate();
            int base=target.position(), row=plane.getRowStride(), pixel=plane.getPixelStride();
            long last=(long)base+(long)(h-1)*row+(long)(w-1)*pixel;
            if (row<=0 || pixel<=0 || last>=target.limit()) throw new IOException("Invalid YUV plane strides");
            for (int y=0;y<h;y++) for (int x=0;x<w;x++)
                target.put(base+y*row+x*pixel,source[offset++]);
        }
    }
}
