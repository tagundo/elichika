package com.klab.lovelive.allstars.fovmod;

public final class MVExportContractTest {
    private static void check(boolean ok) { if (!ok) throw new AssertionError(); }
    private static void rejects(Runnable run) {
        try { run.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Invalid configuration accepted");
    }
    public static void main(String[] args) {
        check(MVExportContract.i420Bytes(1280, 720) == 1382400);
        check(MVExportContract.timestampUs(300, 30) == 10000000L);
        // Every accepted frame/sample receives its rational timestamp, without
        // cumulative truncated-delta drift at 60/90/120 FPS and 44.1 kHz audio.
        for (int rate : new int[] {30, 60, 90, 120, 44100, 48000}) {
            long previous = -1;
            for (long n = 0; n <= 120000; n++) {
                long time = MVExportContract.timestampUs(n, rate);
                check(time > previous);
                check(time == n * 1000000L / rate);
                previous = time;
            }
        }
        check(MVExportContract.timestampUs(44100L * 60 * 60 * 12, 44100) == 43200000000L);
        for (int fps : new int[] {30, 60, 120}) {
            for (int sampleRate : new int[] {44100, 48000, 96000}) {
                long end=0;
                for (int frames : new int[] {121, 177, 1401}) {
                    long start=MVExportContract.audioFramesThroughVideoFrame(end,fps,sampleRate);
                    end+=frames;
                    long next=MVExportContract.audioFramesThroughVideoFrame(end,fps,sampleRate);
                    long independent=MVExportContract.audioFramesThroughVideoFrame(frames,fps,sampleRate);
                    check(next==(end*sampleRate+fps-1L)/fps);
                    check(next-start==independent||next-start==independent-1);
                }
            }
        }
        // Keeping two independently rounded half-samples would add a sample at each 120 fps join.
        check(MVExportContract.audioFramesThroughVideoFrame(1,120,44100)==368);
        check(MVExportContract.audioFramesThroughVideoFrame(2,120,44100)==735);
        check(MVExportContract.audioFramesThroughVideoFrame(Long.MAX_VALUE,1,1)==Long.MAX_VALUE);
        rejects(() -> MVExportContract.audioFramesThroughVideoFrame(Long.MAX_VALUE,1,48000));
        rejects(() -> MVExportContract.audioFramesThroughVideoFrame(-1,120,44100));
        rejects(() -> MVExportContract.validateVideo("video/av01", 1280, 720, 30, 4000000, 300));
        rejects(() -> MVExportContract.i420Bytes(1279, 720));
        rejects(() -> MVExportContract.timestampUs(-1, 30));
        rejects(() -> MVExportContract.validateVideo("video/avc", 1280, 720, 0, 4000000, 300));
        rejects(() -> MVExportContract.timestampUs(Long.MAX_VALUE, 1));
        rejects(() -> MVExportContract.i420Bytes(Integer.MAX_VALUE-1, Integer.MAX_VALUE-1));
        System.out.println("PASS: rational timestamps, long audio, I420 bounds, codec allowlist");
    }
}
