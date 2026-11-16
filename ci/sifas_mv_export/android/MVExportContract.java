package com.klab.lovelive.allstars.fovmod;

/** Pure arithmetic shared by the Android encoder and host/device checks. */
public final class MVExportContract {
    private MVExportContract() {}

    public static long timestampUs(long index, int rate) {
        if (index < 0 || rate <= 0) throw new IllegalArgumentException("Invalid timestamp");
        // Divide first: multiplying an arbitrary sample/frame index may overflow.
        long seconds=index/rate, remainder=(index%rate)*1000000L/rate;
        if (seconds>(Long.MAX_VALUE-remainder)/1000000L)
            throw new IllegalArgumentException("Timestamp overflow");
        return seconds*1000000L+remainder;
    }

    public static int i420Bytes(int width, int height) {
        if (width < 2 || height < 2 || (width & 1) != 0 || (height & 1) != 0)
            throw new IllegalArgumentException("I420 requires positive even dimensions");
        long pixels=(long)width*height;
        if (pixels>Integer.MAX_VALUE*2L/3) throw new IllegalArgumentException("I420 frame is too large");
        return (int)(pixels*3/2);
    }

    public static void validateVideo(String mime, int width, int height, int fps,
            int bitrate, long frames) {
        if (!"video/avc".equals(mime) && !"video/hevc".equals(mime))
            throw new IllegalArgumentException("Only H.264 and HEVC are supported");
        i420Bytes(width, height);
        if (fps <= 0 || fps > 240 || bitrate <= 0 || frames <= 0)
            throw new IllegalArgumentException("Invalid video configuration");
        timestampUs(frames, fps);
    }
}
