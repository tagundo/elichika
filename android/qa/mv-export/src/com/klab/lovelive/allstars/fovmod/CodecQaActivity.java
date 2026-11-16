package com.klab.lovelive.allstars.fovmod;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import org.json.JSONObject;

/** Standalone diagnostic only. It never loads or modifies the game. */
public final class CodecQaActivity extends Activity {
    private TextView status;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        status=new TextView(this); status.setPadding(24,48,24,24); status.setTextSize(16);
        setContentView(status);
        show("RUNNING: Android MediaCodec MP4 round-trip\nH.264 / HEVC + AAC\nEncoder backend only; no game or MV clock loaded.");
        new Thread(new Runnable() { public void run() { execute(); } },"MP4-Codec-QA").start();
    }
    private void execute() {
        JSONObject report=new JSONObject();
        try {
            put(report,"scope","actual Android encoder backend + independent decode; no game/MV integration claim");
            put(report,"sdk",android.os.Build.VERSION.SDK_INT);
            put(report,"fingerprint",android.os.Build.FINGERPRINT);
            put(report,"h264",CodecRoundTripTest.run(getFilesDir(),AndroidMVEncoder.AVC));
            show("RUNNING: H.264 passed. Checking HEVC availability and round-trip.");
            put(report,"hevc",CodecRoundTripTest.run(getFilesDir(),AndroidMVEncoder.HEVC));
            put(report,"result","PASS");
            write("report.json",report.toString(2)); write("status.txt","PASS\n");
            Log.i("MP4CodecQA",report.toString()); show("PASS\n"+report.toString(2));
        } catch (Throwable error) {
            Log.e("MP4CodecQA","Codec round-trip failed",error);
            try {
                put(report,"result","FAIL"); put(report,"error",Log.getStackTraceString(error));
                write("report.json",report.toString(2)); write("status.txt","FAIL\n");
            } catch (Exception ignored) { Log.e("MP4CodecQA","Cannot write failure report",ignored); }
            show("FAIL\n"+Log.getStackTraceString(error));
        }
    }
    private static void put(JSONObject o,String key,Object value) throws Exception { o.put(key,value); }
    private void show(final String text) { runOnUiThread(new Runnable() { public void run() { status.setText(text); } }); }
    private void write(String name,String text) throws Exception {
        File file=new File(getFilesDir(),name);
        FileOutputStream stream=new FileOutputStream(file);
        try { stream.write(text.getBytes("UTF-8")); stream.getFD().sync(); } finally { stream.close(); }
    }
}
