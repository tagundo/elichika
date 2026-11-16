package com.klab.lovelive.allstars.fovmod;

import android.graphics.ImageFormat;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Independent MP4 demux + video/PCM decode. Production encoder sources stay frozen. */
final class CodecRoundTripTest {
    private static final int W=1280,H=720,FPS=30,FRAMES=60,RATE=48000,CHANNELS=2;
    private static final int AUDIO_FRAMES=96000,ONSET=12000,BITRATE=4000000;
    private static final long TIMEOUT_NS=TimeUnit.SECONDS.toNanos(120);
    private static void check(boolean ok,String message) throws IOException { if (!ok) throw new IOException(message); }
    private static void deadline(long end) throws IOException { check(System.nanoTime()<end,"Codec QA deadline exceeded"); }
    private static void pause(long end) throws Exception { deadline(end); Thread.sleep(2); }

    static JSONObject run(File directory,String mime) throws Exception {
        JSONObject report=new JSONObject(); report.put("mime",mime);
        MediaFormat selection=MediaFormat.createVideoFormat(mime,W,H);
        selection.setInteger(MediaFormat.KEY_BIT_RATE,BITRATE);
        selection.setInteger(MediaFormat.KEY_FRAME_RATE,FPS);
        selection.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        if (AndroidMVEncoder.AVC.equals(mime)) selection.setInteger(MediaFormat.KEY_PROFILE,MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
        String codec=new MediaCodecList(MediaCodecList.REGULAR_CODECS).findEncoderForFormat(selection);
        if (codec==null) {
            check(AndroidMVEncoder.HEVC.equals(mime),"H.264 encoder is required and unavailable");
            report.put("status","SKIP"); report.put("reason","No advertised encoder supports the exact HEVC 1280x720 30fps 4Mbps flexible-YUV configuration");
            return report;
        }
        report.put("encoder",codec);
        File output=new File(directory,"roundtrip-"+(AndroidMVEncoder.AVC.equals(mime)?"h264":"hevc")+".mp4");
        check(!output.exists(),"Output already exists; fresh QA install is required");
        AndroidMVEncoder.Config config=new AndroidMVEncoder.Config(mime,W,H,FPS,BITRATE,FRAMES,RATE,CHANNELS,192000,AUDIO_FRAMES);
        AndroidMVEncoder encoder=new AndroidMVEncoder(config,output,40);
        long started=System.nanoTime(),end=started+TIMEOUT_NS; int retries=0;
        try {
            byte[] picture=new byte[MVExportContract.i420Bytes(W,H)];
            long audioIndex=0;
            for (int frame=0;frame<FRAMES;frame++) {
                paint(picture,frame);
                long next=(frame+1L)*RATE/FPS;
                ByteBuffer pcm=ByteBuffer.allocate((int)(next-audioIndex)*CHANNELS*2).order(ByteOrder.LITTLE_ENDIAN);
                for (long n=audioIndex;n<next;n++) for (int channel=0;channel<CHANNELS;channel++)
                    pcm.putShort((short)(n<ONSET?0:Math.sin(2*Math.PI*(channel==0?440:880)*(n-ONSET)/RATE)*10000));
                pcm.flip();
                while (!encoder.offerAudio(audioIndex,pcm)) { retries++; pause(end); }
                audioIndex=next;
                ByteBuffer video=ByteBuffer.wrap(picture);
                while (!encoder.offerVideo(frame,video)) { retries++; pause(end); }
            }
            encoder.finish();
            check(output.getCanonicalFile().equals(encoder.awaitCompletion(120,TimeUnit.SECONDS)),"Wrong final output");
        } catch (Throwable error) { encoder.cancel(); throw error; }
        long elapsed=System.nanoTime()-started;
        check(retries>0,"40ms diagnostic writer did not exercise bounded retry backpressure");
        check(elapsed>TimeUnit.SECONDS.toNanos(2),"Diagnostic export was not slower than 2s playback");
        check(output.isFile()&&output.length()>0,"Missing MP4");
        report.put("backpressureRetries",retries); report.put("wallTimeMs",elapsed/1000000);
        report.put("video",decodeVideo(output,mime));
        report.put("audio",decodeAudio(output));
        cancellation(directory,config,output);
        report.put("cancelPartialCleanup","PASS"); report.put("status","PASS");
        report.put("mp4",output.getName()); report.put("mp4Bytes",output.length()); return report;
    }
    private static void paint(byte[] bytes,int frame) {
        for (int y=0;y<H;y++) for (int x=0;x<W;x++) {
            int value=32+(x>=W/2?48:0)+(y>=H/2?96:0);
            if (y>=H/16&&y<H/5) {
                for (int bit=0;bit<6;bit++) if (Math.abs(x-W*(bit+1)/7)<W/28)
                    value=(frame&(1<<bit))==0?32:220;
            }
            bytes[y*W+x]=(byte)value;
        }
        for (int n=W*H;n<bytes.length;n++) bytes[n]=(byte)128;
    }
    private static MediaExtractor extractor(File file,String prefix) throws Exception {
        MediaExtractor e=new MediaExtractor();
        try {
            e.setDataSource(file.getPath()); int found=-1;
            for (int n=0;n<e.getTrackCount();n++) {
                String type=e.getTrackFormat(n).getString(MediaFormat.KEY_MIME);
                check(type!=null,"Track has no MIME");
                check(type.equals(AndroidMVEncoder.AVC)||type.equals(AndroidMVEncoder.HEVC)||type.equals("audio/mp4a-latm"),"Unexpected MP4 codec: "+type);
                if (type.startsWith(prefix)) { check(found<0,"Duplicate MP4 track"); found=n; }
            }
            check(e.getTrackCount()==2&&found>=0,"MP4 must have exactly one video and one AAC track");
            e.selectTrack(found); return e;
        } catch (Throwable error) { e.release(); throw error; }
    }
    private static boolean input(MediaExtractor e,MediaCodec decoder,boolean finished) throws Exception {
        if (finished) return true;
        int index=decoder.dequeueInputBuffer(1000);
        if (index<0) return false;
        ByteBuffer buffer=decoder.getInputBuffer(index); check(buffer!=null,"Missing decode input buffer"); buffer.clear();
        int size=e.readSampleData(buffer,0);
        if (size<0) { decoder.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM); return true; }
        decoder.queueInputBuffer(index,0,size,e.getSampleTime(),e.getSampleFlags()&MediaCodec.BUFFER_FLAG_KEY_FRAME);
        e.advance(); return false;
    }
    private static JSONObject decodeVideo(File file,String mime) throws Exception {
        MediaExtractor e=extractor(file,"video/"); MediaCodec decoder=null;
        int decoded=0,samples=0; long last=-1; JSONObject report=new JSONObject();
        try {
            int track=e.getSampleTrackIndex(); MediaFormat format=e.getTrackFormat(track);
            check(mime.equals(format.getString(MediaFormat.KEY_MIME)),"Wrong encoded video MIME");
            check(format.getInteger(MediaFormat.KEY_WIDTH)==W&&format.getInteger(MediaFormat.KEY_HEIGHT)==H,"Wrong MP4 video dimensions");
            ByteBuffer packet=ByteBuffer.allocate(4*1024*1024);
            while (e.getSampleTrackIndex()>=0) {
                check(e.readSampleData(packet,0)>0,"Empty encoded video sample");
                check(e.getSampleTime()==MVExportContract.timestampUs(samples,FPS),"Extractor video PTS differs at frame "+samples);
                samples++; if (!e.advance()) break;
            }
            check(samples==FRAMES,"Extractor video sample count differs: "+samples);
            e.seekTo(0,MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            decoder=MediaCodec.createDecoderByType(mime); report.put("decoder",decoder.getName());
            decoder.configure(format,null,null,0); decoder.start();
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo(); boolean in=false,out=false;
            long end=System.nanoTime()+TIMEOUT_NS;
            while (!out) {
                deadline(end); in=input(e,decoder,in); int index=decoder.dequeueOutputBuffer(info,1000);
                if (index>=0) {
                    try {
                        if (info.size>0) {
                            check(decoded<FRAMES,"Extra decoded video frame");
                            check(info.presentationTimeUs==MVExportContract.timestampUs(decoded,FPS),"Decoded video PTS changed at "+decoded);
                            check(info.presentationTimeUs>last,"Decoded video PTS reordered"); last=info.presentationTimeUs;
                            Image image=decoder.getOutputImage(index); check(image!=null,"Video decoder did not expose CPU YUV image");
                            try { verify(image,decoded); } finally { image.close(); }
                            decoded++;
                        }
                        out=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    } finally { decoder.releaseOutputBuffer(index,false); }
                }
            }
            check(decoded==FRAMES,"Decoded video frame count differs: "+decoded);
            report.put("extractorSamples",samples); report.put("decodedFrames",decoded);
            report.put("framePTS","exact rational 30fps; all 60 frames");
            report.put("pixels","all-frame six-bit identity barcode + four quadrant orientation"); return report;
        } finally { e.release(); if (decoder!=null) { try { decoder.stop(); } finally { decoder.release(); } } }
    }
    private static void verify(Image image,int frame) throws Exception {
        check(image.getFormat()==ImageFormat.YUV_420_888,"Unexpected decoded image format");
        check(image.getCropRect().width()==W&&image.getCropRect().height()==H,"Unexpected decoded crop");
        for (int q=0;q<4;q++) {
            int x=(q%2==0?W/4:W*3/4),y=(q<2?H/3:H*2/3),expected=32+(q%2)*48+(q/2)*96;
            check(Math.abs(luma(image,x,y)-expected)<=16,"Decoded orientation/luma mismatch frame="+frame+" quadrant="+q);
        }
        int identity=0;
        for (int bit=0;bit<6;bit++) if (luma(image,W*(bit+1)/7,H/8)>126) identity|=1<<bit;
        check(identity==frame,"Decoded image identity mismatch; expected="+frame+" actual="+identity);
    }
    private static int luma(Image image,int x,int y) throws Exception {
        Image.Plane plane=image.getPlanes()[0]; ByteBuffer b=plane.getBuffer();
        int at=b.position()+(y+image.getCropRect().top)*plane.getRowStride()+(x+image.getCropRect().left)*plane.getPixelStride();
        check(at>=b.position()&&at<b.limit(),"Decoded luma stride outside buffer"); return b.get(at)&255;
    }
    private static JSONObject decodeAudio(File file) throws Exception {
        MediaExtractor e=extractor(file,"audio/"); MediaCodec decoder=null; JSONObject report=new JSONObject();
        int packets=0,rawFrames=0,delay=0,padding=0; long last=-1; short[] pcm=new short[(AUDIO_FRAMES+8192)*CHANNELS];
        try {
            MediaFormat format=e.getTrackFormat(e.getSampleTrackIndex());
            check("audio/mp4a-latm".equals(format.getString(MediaFormat.KEY_MIME)),"Audio must be AAC");
            check(format.getInteger(MediaFormat.KEY_SAMPLE_RATE)==RATE&&format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)==CHANNELS,"Wrong AAC rate/channels");
            delay=format.containsKey("encoder-delay")?format.getInteger("encoder-delay"):0;
            padding=format.containsKey("encoder-padding")?format.getInteger("encoder-padding"):0;
            while (e.getSampleTrackIndex()>=0) {
                check(e.getSampleTime()>last,"AAC extractor PTS reordered");
                if (packets==0) check(e.getSampleTime()==0,"AAC extractor timeline does not start at zero");
                last=e.getSampleTime(); packets++;
                if (!e.advance()) break;
            }
            check(packets>0,"AAC contains no packets"); e.seekTo(0,MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
            decoder=MediaCodec.createDecoderByType("audio/mp4a-latm"); report.put("decoder",decoder.getName());
            decoder.configure(format,null,null,0); decoder.start();
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo(); boolean in=false,out=false;
            long end=System.nanoTime()+TIMEOUT_NS;
            while (!out) {
                deadline(end); in=input(e,decoder,in); int index=decoder.dequeueOutputBuffer(info,1000);
                if (index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat actual=decoder.getOutputFormat();
                    check(actual.getInteger(MediaFormat.KEY_SAMPLE_RATE)==RATE&&actual.getInteger(MediaFormat.KEY_CHANNEL_COUNT)==CHANNELS,"Decoder changed PCM rate/channels");
                    if (actual.containsKey("pcm-encoding")) check(actual.getInteger("pcm-encoding")==2,"PCM decoder did not produce PCM16");
                }
                if (index>=0) {
                    try {
                        if (info.size>0) {
                            check(info.size%(CHANNELS*2)==0,"Partial decoded PCM frame");
                            check(Math.abs(info.presentationTimeUs-MVExportContract.timestampUs(rawFrames,RATE))<=1,
                                "Decoded PCM timeline changed at sample "+rawFrames+" PTS="+info.presentationTimeUs);
                            ByteBuffer data=decoder.getOutputBuffer(index); check(data!=null,"Missing decoded PCM");
                            data.position(info.offset); data.limit(info.offset+info.size); data.order(ByteOrder.LITTLE_ENDIAN);
                            int count=info.size/(CHANNELS*2); check(rawFrames+count<=pcm.length/CHANNELS,"Unexpected excess decoded audio");
                            for (int n=0;n<count*CHANNELS;n++) pcm[rawFrames*CHANNELS+n]=data.getShort(); rawFrames+=count;
                        }
                        out=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    } finally { decoder.releaseOutputBuffer(index,false); }
                }
            }
            // Android decoders may apply the extractor's gapless metadata themselves.
            // Accept only an exact presented sample count or an exact documented trim.
            int offset=0;
            if (rawFrames!=AUDIO_FRAMES) {
                check(delay>=0&&padding>=0&&rawFrames-delay-padding==AUDIO_FRAMES,
                    "AAC exact sample count failed: decoded="+rawFrames+" expected="+AUDIO_FRAMES+" encoder-delay="+delay+" encoder-padding="+padding);
                offset=delay;
            }
            int onset=-1;
            for (int n=0;n<AUDIO_FRAMES-128;n+=128) {
                double rms=energy(pcm,offset+n,128,0);
                if (rms>1500) { onset=n; break; }
            }
            check(Math.abs(onset-ONSET)<=256,"AAC tone onset differs: "+onset+" expected="+ONSET);
            check(energy(pcm,offset+2000,4096,0)<200,"AAC initial silence is corrupted");
            check(energy(pcm,offset+AUDIO_FRAMES-4096,4096,0)>5000&&energy(pcm,offset+AUDIO_FRAMES-4096,4096,1)>5000,
                "AAC tone tail is missing or unexpectedly padded");
            double left440=projection(pcm,offset+24000,24000,0,440),left880=projection(pcm,offset+24000,24000,0,880);
            double right880=projection(pcm,offset+24000,24000,1,880),right440=projection(pcm,offset+24000,24000,1,440);
            check(left440>5000&&left440>left880*8&&right880>5000&&right880>right440*8,"AAC tone frequency/amplitude/channel order mismatch");
            report.put("aacPackets",packets); report.put("rawDecodedPCMFrames",rawFrames);
            report.put("encoderDelay",delay); report.put("encoderPadding",padding); report.put("verifiedPCMFrames",AUDIO_FRAMES);
            report.put("toneOnsetSample",onset); report.put("expectedOnsetSample",ONSET);
            report.put("stereoTonesHz","440 left, 880 right");
            report.put("audioPTS","extractor starts at zero; every PCM buffer follows exact sample timeline within 1us"); return report;
        } finally { e.release(); if (decoder!=null) { try { decoder.stop(); } finally { decoder.release(); } } }
    }
    private static double energy(short[] pcm,int at,int count,int channel) {
        double sum=0; for (int n=0;n<count;n++) { double v=pcm[(at+n)*CHANNELS+channel]; sum+=v*v; } return Math.sqrt(sum/count);
    }
    private static double projection(short[] pcm,int at,int count,int channel,int hz) {
        double sin=0,cos=0;
        for (int n=0;n<count;n++) { double v=pcm[(at+n)*CHANNELS+channel],r=2*Math.PI*hz*n/RATE; sin+=v*Math.sin(r); cos+=v*Math.cos(r); }
        return 2*Math.sqrt(sin*sin+cos*cos)/count;
    }
    private static void cancellation(File directory,AndroidMVEncoder.Config config,File complete) throws Exception {
        File output=new File(directory,"cancel-"+System.nanoTime()+".mp4");
        AndroidMVEncoder encoder=new AndroidMVEncoder(config,output,40);
        long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(15);
        byte[] first=new byte[MVExportContract.i420Bytes(W,H)]; paint(first,0);
        ByteBuffer audio=ByteBuffer.allocate(1600*CHANNELS*2);
        while (!encoder.offerAudio(0,audio)) pause(end);
        ByteBuffer video=ByteBuffer.wrap(first);
        while (!encoder.offerVideo(0,video)) pause(end);
        boolean observedPartial=false;
        while (!observedPartial) {
            File[] active=directory.listFiles(); check(active!=null,"Cannot inspect active export directory");
            for (File file:active) if (file.getName().startsWith("."+output.getName()+".")&&file.getName().endsWith(".partial")) observedPartial=true;
            if (!observedPartial) pause(end);
        }
        encoder.cancel(); boolean failed=false;
        try { encoder.awaitCompletion(60,TimeUnit.SECONDS); } catch (ExecutionException expected) { failed=true; }
        check(failed&&!output.exists(),"Cancelled final output was retained");
        File[] files=directory.listFiles(); check(files!=null,"Cannot inspect cancellation directory");
        for (File file:files) check(!file.getName().startsWith("."+output.getName()+"."),"Cancelled partial file remains");
        check(complete.isFile()&&complete.length()>0,"Cancellation damaged completed output");
    }
}
