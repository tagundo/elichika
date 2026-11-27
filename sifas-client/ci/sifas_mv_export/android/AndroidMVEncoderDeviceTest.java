package com.klab.lovelive.allstars.fovmod;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

/**
 * Run inside an actual API21+ Android app process, on a background test thread.
 * This uses real MediaCodec/MediaMuxer/MediaExtractor, never mocked Android jars.
 * It proves encoding only; it cannot establish SIFAS MV stepping/render fidelity.
 */
public final class AndroidMVEncoderDeviceTest {
    private static void check(boolean ok, String detail) throws IOException {
        if (!ok) throw new IOException(detail);
    }
    public static String run(File appPrivateDirectory, String videoMime) throws Exception {
        final int fps=30, frames=60, sampleRate=48000;
        final long audioFrames=96000;
        File output=new File(appPrivateDirectory,"encoder-probe-"+System.nanoTime()+".mp4");
        AndroidMVEncoder.Config config=new AndroidMVEncoder.Config(videoMime,1280,720,fps,
                4000000,frames,sampleRate,2,192000,audioFrames);
        AndroidMVEncoder encoder=new AndroidMVEncoder(config,output,40);
        long start=System.nanoTime(), deadline=start+TimeUnit.SECONDS.toNanos(120);
        int rejected=0;
        byte[] i420=new byte[MVExportContract.i420Bytes(1280,720)];
        long audioIndex=0;
        try {
            for (int frame=0;frame<frames;frame++) {
                // A frame-specific luminance bar distinguishes submitted frames.
                for (int y=0;y<720;y++) for (int x=0;x<1280;x++)
                    i420[y*1280+x]=(byte)(16+(x/160+frame)%8*29);
                for (int n=1280*720;n<i420.length;n++) i420[n]=(byte)128;
                long nextAudio=(frame+1L)*sampleRate/fps;
                int count=(int)(nextAudio-audioIndex);
                ByteBuffer pcm=ByteBuffer.allocate(count*4);
                for (int n=0;n<count;n++) {
                    short value=(short)(Math.sin(2*Math.PI*440*(audioIndex+n)/sampleRate)*8000);
                    for (int channel=0;channel<2;channel++) {
                        pcm.put((byte)value); pcm.put((byte)(value>>>8));
                    }
                }
                pcm.flip();
                while (!encoder.offerAudio(audioIndex,pcm)) { rejected++; pause(deadline); }
                audioIndex=nextAudio;
                ByteBuffer video=ByteBuffer.wrap(i420);
                while (!encoder.offerVideo(frame,video)) { rejected++; pause(deadline); }
            }
            encoder.finish();
            check(encoder.awaitCompletion(120,TimeUnit.SECONDS).equals(output.getCanonicalFile()),"Wrong completion file");
        } catch (Exception error) { encoder.cancel(); throw error; }
        long elapsed=System.nanoTime()-start;
        check(rejected>0,"Slow writer did not exercise bounded producer backpressure");
        check(elapsed>TimeUnit.SECONDS.toNanos(2),"Diagnostic writer did not run slower than playback");
        MediaExtractor reader=new MediaExtractor();
        int videoSamples=0, audioSamples=0;
        try {
            reader.setDataSource(output.getPath());
            for (int track=0;track<reader.getTrackCount();track++) {
                MediaFormat format=reader.getTrackFormat(track);
                String mime=format.getString(MediaFormat.KEY_MIME);
                boolean video=mime.startsWith("video/");
                if (!video && !mime.equals("audio/mp4a-latm")) continue;
                reader.selectTrack(track); reader.seekTo(0,MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
                int count=0;
                long previous=-1;
                while (reader.getSampleTrackIndex()>=0) {
                    check(reader.getSampleTrackIndex()==track,"Unexpected selected MP4 track");
                    long pts=reader.getSampleTime();
                    check(pts>previous,"Nonmonotonic MP4 sample timestamps");
                    if (video) check(pts==MVExportContract.timestampUs(count,fps),"MP4 changed a video timestamp");
                    previous=pts; count++;
                    if (!reader.advance()) break;
                }
                reader.unselectTrack(track);
                if (video) { check(mime.equals(videoMime),"Wrong video codec"); videoSamples=count; }
                else { audioSamples=count; check(previous>=1900000L && previous<=2050000L,"AAC track is truncated or too long"); }
            }
        } finally { reader.release(); }
        check(videoSamples==frames && audioSamples>0,"MP4 lost video or AAC samples");

        // Cancellation must remove only this session's reserved/partial output.
        File cancelled=new File(appPrivateDirectory,"encoder-cancel-"+System.nanoTime()+".mp4");
        AndroidMVEncoder cancelledEncoder=new AndroidMVEncoder(config,cancelled);
        cancelledEncoder.cancel();
        boolean failed=false;
        try { cancelledEncoder.awaitCompletion(60,TimeUnit.SECONDS); }
        catch (ExecutionException expected) { failed=true; }
        check(failed && !cancelled.exists(),"Cancelled session retained a final output");
        check(output.isFile() && output.length()>0,"Cancellation damaged the completed output");
        return "PASS encoder-only: "+videoMime+", "+videoSamples+" video samples, "+audioSamples+
                " AAC packets; backpressure retries="+rejected+"; output="+output.getPath();
    }

    /** Opt-in sequential export probe for a background thread in the device test app. */
    public static String runCombine(File appPrivateDirectory, String videoMime) throws Exception {
        File directory = new File(appPrivateDirectory, "encoder-combine-" + System.nanoTime());
        check(directory.mkdir(), "Could not create the combine probe directory");
        AndroidMVEncoder.Segment first = encodeClip(directory, "first", videoMime, 12, 48, 440);
        AndroidMVEncoder.Segment second = encodeClip(directory, "second", videoMime, 15, 200, 1320);
        int joinFrame = (int) first.config.videoFrames;
        int totalFrames = joinFrame + (int) second.config.videoFrames;
        List<byte[]> firstSamples = videoSamples(first.video, first.config, joinFrame, -1);
        List<byte[]> secondSamples = videoSamples(second.video, second.config, totalFrames - joinFrame, -1);
        check(!Arrays.equals(firstSamples.get(0), secondSamples.get(0)), "Probe keyframes must differ");

        File output = new File(directory, "combined.mp4");
        AndroidMVEncoder combined = AndroidMVEncoder.combine(Arrays.asList(first, second), output);
        try {
            check(combined.awaitCompletion(120, TimeUnit.SECONDS).equals(output.getCanonicalFile()),
                    "Combine returned the wrong output file");
        } catch (Exception error) {
            combined.cancel();
            throw error;
        }

        List<byte[]> expected = new ArrayList<>(firstSamples);
        expected.addAll(secondSamples);
        List<byte[]> actual = videoSamples(output, first.config, totalFrames, joinFrame);
        for (int n = 0; n < actual.size(); n++) {
            check(Arrays.equals(expected.get(n), actual.get(n)), "Wrong combined video sample at frame " + n);
        }
        check(first.video.isFile() && second.video.isFile()
                && first.pcm.length() == first.config.audioFrames * 4
                && second.pcm.length() == second.config.audioFrames * 4,
                "Combine removed or truncated a source clip");

        int boundary = (int) first.config.audioFrames;
        int total = boundary + (int) second.config.audioFrames;
        short[] pcm = decodeCombinedAudio(output, first.config.sampleRate, total);
        // Leave two AAC access units around the boundary for decoder priming/edit-list handling.
        checkTone(pcm, boundary - 3840, first.config.sampleRate, 440, 1320);
        checkTone(pcm, boundary + 2400, first.config.sampleRate, 1320, 440);
        return "PASS sequential combine: " + videoMime + ", 27 frames at 30 FPS, tones change near 0.4 s; output="
                + output.getPath();
    }

    private static AndroidMVEncoder.Segment encodeClip(File directory, String name, String mime,
            int frames, int luminance, int tone) throws Exception {
        int width = 320, height = 192, fps = 30, sampleRate = 48000;
        int samplesPerFrame = sampleRate / fps;
        AndroidMVEncoder.Config config = new AndroidMVEncoder.Config(mime, width, height, fps,
                500000, frames, sampleRate, 2, 192000, (long) frames * samplesPerFrame);
        File video = new File(directory, name + ".mp4");
        File pcm = new File(directory, name + ".pcm");
        AndroidMVEncoder encoder = new AndroidMVEncoder(config, video, pcm);
        byte[] image = new byte[MVExportContract.i420Bytes(width, height)];
        Arrays.fill(image, 0, width * height, (byte) luminance);
        Arrays.fill(image, width * height, image.length, (byte) 128);
        ByteBuffer audio = ByteBuffer.allocate(samplesPerFrame * 4).order(ByteOrder.LITTLE_ENDIAN);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120);
        try {
            for (int frame = 0; frame < frames; frame++) {
                long audioIndex = (long) frame * samplesPerFrame;
                audio.clear();
                for (int n = 0; n < samplesPerFrame; n++) {
                    short value = (short) (8000 * Math.sin(2 * Math.PI * tone * (audioIndex + n) / sampleRate));
                    audio.putShort(value).putShort(value);
                }
                audio.flip();
                while (!encoder.offerAudio(audioIndex, audio)) pause(deadline);
                ByteBuffer frameData = ByteBuffer.wrap(image);
                while (!encoder.offerVideo(frame, frameData)) pause(deadline);
            }
            encoder.finish();
            check(encoder.awaitCompletion(120, TimeUnit.SECONDS).equals(video.getCanonicalFile()),
                    "Segment returned the wrong output file");
            check(pcm.length() == config.audioFrames * 4, "Segment PCM length differs from the submitted audio");
            return new AndroidMVEncoder.Segment(video, pcm, config);
        } catch (Exception error) {
            encoder.cancel();
            throw error;
        }
    }

    private static List<byte[]> videoSamples(File file, AndroidMVEncoder.Config config,
            int expectedFrames, int joinFrame) throws IOException {
        MediaExtractor reader = new MediaExtractor();
        try {
            reader.setDataSource(file.getPath());
            int expectedTracks = joinFrame < 0 ? 1 : 2;
            check(reader.getTrackCount() == expectedTracks, "Unexpected track count for " + file.getName());
            int track = findTrack(reader, config.mime);
            MediaFormat format = reader.getTrackFormat(track);
            check(format.getInteger(MediaFormat.KEY_WIDTH) == config.width
                    && format.getInteger(MediaFormat.KEY_HEIGHT) == config.height, "Wrong probe video dimensions");
            reader.selectTrack(track);
            ByteBuffer data = ByteBuffer.allocateDirect(1024 * 1024);
            List<byte[]> samples = new ArrayList<>();
            while (reader.getSampleTrackIndex() >= 0) {
                int frame = samples.size();
                check(frame < expectedFrames, "Unexpected extra video frame");
                long pts = reader.getSampleTime();
                check(Math.abs(pts - MVExportContract.timestampUs(frame, config.fps)) <= 11,
                        "Wrong video PTS at frame " + frame + ": " + pts);
                if (frame == 0 || frame == joinFrame) {
                    check((reader.getSampleFlags() & MediaExtractor.SAMPLE_FLAG_SYNC) != 0,
                            "Clip does not start on a sync sample at frame " + frame);
                }
                data.clear();
                int size = reader.readSampleData(data, 0);
                check(size > 0 && size <= data.capacity(), "Invalid probe video sample size");
                byte[] sample = new byte[size];
                data.position(0);
                data.get(sample);
                samples.add(sample);
                reader.advance();
            }
            check(samples.size() == expectedFrames, "Video has missing frames");
            return samples;
        } finally {
            reader.release();
        }
    }

    private static int findTrack(MediaExtractor reader, String mime) throws IOException {
        int selected = -1;
        for (int n = 0; n < reader.getTrackCount(); n++) {
            if (mime.equals(reader.getTrackFormat(n).getString(MediaFormat.KEY_MIME))) {
                check(selected == -1, "Duplicate " + mime + " tracks");
                selected = n;
            }
        }
        check(selected >= 0, "Missing " + mime + " track");
        return selected;
    }

    private static short[] decodeCombinedAudio(File output, int sampleRate, int expectedFrames) throws IOException {
        MediaExtractor reader = new MediaExtractor();
        MediaCodec decoder = null;
        int tolerance = 2048;
        short[] pcm = new short[expectedFrames + tolerance];
        int decodedFrames = 0;
        try {
            reader.setDataSource(output.getPath());
            String mime = "audio/mp4a-latm";
            int track = findTrack(reader, mime);
            MediaFormat format = reader.getTrackFormat(track);
            check(format.getInteger(MediaFormat.KEY_SAMPLE_RATE) == sampleRate
                    && format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == 2, "Wrong combined audio format");
            long duration = format.getLong(MediaFormat.KEY_DURATION);
            check(Math.abs(duration - MVExportContract.timestampUs(expectedFrames, sampleRate))
                    <= MVExportContract.timestampUs(tolerance, sampleRate), "Wrong combined audio duration");
            reader.selectTrack(track);
            decoder = MediaCodec.createDecoderByType(mime);
            decoder.configure(format, null, null, 0);
            decoder.start();

            boolean inputDone = false;
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            while (true) {
                check(System.nanoTime() <= deadline, "Timed out decoding the combined audio");
                if (!inputDone) {
                    int inputIndex = decoder.dequeueInputBuffer(10000);
                    if (inputIndex >= 0) {
                        ByteBuffer input = decoder.getInputBuffer(inputIndex);
                        check(input != null, "Missing decoder input buffer");
                        int size = reader.readSampleData(input, 0);
                        inputDone = size < 0;
                        decoder.queueInputBuffer(inputIndex, 0, Math.max(size, 0),
                                inputDone ? 0 : reader.getSampleTime(),
                                inputDone ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                        if (!inputDone) reader.advance();
                    }
                }
                int outputIndex = decoder.dequeueOutputBuffer(info, 10000);
                if (outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat decodedFormat = decoder.getOutputFormat();
                    check(decodedFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE) == sampleRate
                            && decodedFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT) == 2
                            && (!decodedFormat.containsKey("pcm-encoding")
                            || decodedFormat.getInteger("pcm-encoding") == AudioFormat.ENCODING_PCM_16BIT),
                            "Unexpected decoder PCM format");
                }
                if (outputIndex < 0) continue;
                if (info.size > 0) {
                    ByteBuffer decoded = decoder.getOutputBuffer(outputIndex);
                    check(decoded != null && info.size % 4 == 0, "Expected decoded stereo PCM16");
                    decoded.order(ByteOrder.LITTLE_ENDIAN);
                    decoded.position(info.offset);
                    int frames = info.size / 4;
                    check(frames <= pcm.length - decodedFrames, "Combined audio contains extra PCM");
                    for (int n = 0; n < frames; n++) {
                        pcm[decodedFrames++] = decoded.getShort();
                        decoded.getShort();
                    }
                }
                decoder.releaseOutputBuffer(outputIndex, false);
                if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break;
            }
            check(decodedFrames >= expectedFrames - tolerance, "Combined audio is truncated");
            return pcm;
        } finally {
            if (decoder != null) decoder.release();
            reader.release();
        }
    }

    private static void checkTone(short[] pcm, int start, int rate, int expected, int other) throws IOException {
        double signal = tonePower(pcm, start, rate, expected);
        check(signal > 1000000 && signal > 10 * tonePower(pcm, start, rate, other),
                "Expected " + expected + " Hz at PCM frame " + start);
    }

    private static double tonePower(short[] pcm, int start, int rate, int frequency) {
        int count = rate / 50;
        double cosine = 0, sine = 0;
        for (int n = 0; n < count; n++) {
            double angle = 2 * Math.PI * frequency * n / rate;
            cosine += pcm[start + n] * Math.cos(angle);
            sine += pcm[start + n] * Math.sin(angle);
        }
        return (cosine * cosine + sine * sine) / ((double) count * count);
    }

    private static void pause(long deadline) throws Exception {
        if (System.nanoTime()>deadline) throw new IOException("Producer retry deadline exceeded");
        Thread.sleep(2);
    }
}
