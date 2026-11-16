package com.klab.lovelive.allstars.fovmod;

import android.media.MediaExtractor;
import android.media.MediaFormat;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
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
    private static void pause(long deadline) throws Exception {
        if (System.nanoTime()>deadline) throw new IOException("Producer retry deadline exceeded");
        Thread.sleep(2);
    }
}
