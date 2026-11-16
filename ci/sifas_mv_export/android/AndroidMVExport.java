package com.klab.lovelive.allstars.fovmod;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.ref.WeakReference;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Game-local export controls. Audio preparation and document copying use one
 * worker; Unity render work is requested through the native main-thread pump.
 * The progress panel is a View in the game window, so it cannot pause Unity by
 * stealing window focus. It is outside the Unity backbuffer being exported.
 */
public final class AndroidMVExport {
    private static final int SAVE_REQUEST = 0x534d;
    private static final long QUERY_TIMEOUT_MS = 15000;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ExecutorService WORK = Executors.newSingleThreadExecutor(new ThreadFactory() {
        public Thread newThread(Runnable task) { return new Thread(task,"SIFAS-MV-Export-IO"); }
    });
    private static WeakReference<Activity> game = new WeakReference<Activity>(null);
    private static long generation;
    private static boolean openWhenResumed, saveWhenResumed, querying, saving, gameResumed, completedWaiting;
    private static View panel;
    private static TextView status;
    private static ProgressBar progress;
    private static Session current;
    private static File completed;
    private static SaveRequest pendingSave;
    private static PendingQuery pendingQuery;
    private static String pendingNotice;
    private static boolean pendingNoticeError;
    private static AlertDialog setupDialog;

    private AndroidMVExport() {}

    private static native int nativeQuery(Object callback);
    private static native long nativePrepare(String selectedSongJson,String cacheRoot,int fps);
    private static native String nativePreparedInfo(long prepared);
    private static native int nativeBegin(long prepared,AndroidMVEncoder encoder,int width,int height,int fps,Object listener);
    private static native void nativeRelease(long prepared);
    private static native void nativeCancel();

    /** Called only from the existing actual-game Activity lifecycle hook. */
    public static void onGameResumed(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameResumed(activity); } }); return;
        }
        game=new WeakReference<Activity>(activity); gameResumed=true;
        MAIN.postDelayed(new Runnable() { public void run() {
            if (!foreground(activity)) return;
            if (current!=null) showProgress(activity,current);
            else if (saveWhenResumed) {
                saveWhenResumed=false; File previous=findCompleted(activity);
                if (previous!=null) offerSave(activity,previous); else toast(activity,"No completed MP4 is available.");
            }
            else if (openWhenResumed) {
                openWhenResumed=false; pendingNotice=null; completedWaiting=false; requestSetup(activity);
            }
            else if (completedWaiting&&completed!=null&&completed.isFile()) { completedWaiting=false; offerSave(activity,completed); }
            else if (pendingNotice!=null) {
                String message=pendingNotice; boolean error=pendingNoticeError; pendingNotice=null;
                if (error) showError(activity,message); else toast(activity,message);
            }
        } },150);
    }

    /** Cancel transport immediately; native scene restoration runs when Unity
     * next resumes its own thread. No lifecycle callback waits for an encoder. */
    public static void onGamePaused(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGamePaused(activity); } }); return;
        }
        if (game.get()!=activity) return;
        gameResumed=false;
        if (setupDialog!=null) {
            setupDialog.dismiss(); setupDialog=null;
            try { nativeCancel(); } catch (Throwable ignored) {}
        }
        if (querying) { generation++; querying=false; }
        if (pendingQuery!=null) pendingQuery.cancel();
        if (current!=null) cancel(current);
        removePanel();
    }
    public static void onGameDestroyed(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameDestroyed(activity); } }); return;
        }
        if (game.get()!=activity) return;
        onGamePaused(activity); game=new WeakReference<Activity>(null);
    }

    /** Added to the original settings Activity by the incremental DEX updater. */
    public static void installSettingsButton(final Activity settings,LinearLayout parent) {
        Button button=new Button(settings); button.setText("Export MP4");
        parent.addView(button,new LinearLayout.LayoutParams(-1,-2));
        button.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
            Activity activity=game.get();
            if (!usable(activity)) { toast(settings,"Open the game and load an MV first."); return; }
            saveWhenResumed=false; openWhenResumed=true; settings.finish();
        } });
        if (findCompleted(settings.getApplicationContext())!=null) {
            Button save=new Button(settings); save.setText("Save last completed MP4");
            parent.addView(save,new LinearLayout.LayoutParams(-1,-2));
            save.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
                Activity activity=game.get();
                if (!usable(activity)) { toast(settings,"Open the game to save the retained MP4."); return; }
                openWhenResumed=false; saveWhenResumed=true; settings.finish();
            } });
        }
    }

    /** The corner settings gesture remains inactive while an export owns the MV. */
    public static boolean isBusy() { return current!=null || querying || saving; }

    private static boolean usable(Activity activity) {
        return activity!=null && !activity.isFinishing() && (Build.VERSION.SDK_INT<17 || !activity.isDestroyed());
    }
    private static boolean foreground(Activity activity) { return usable(activity)&&gameResumed&&game.get()==activity; }
    private static int dp(Context context,int value) { return (int)(value*context.getResources().getDisplayMetrics().density+0.5f); }
    private static void toast(Context context,String text) { Toast.makeText(context,text,Toast.LENGTH_LONG).show(); }
    private static void removePanel() {
        if (panel!=null && panel.getParent() instanceof ViewGroup) ((ViewGroup)panel.getParent()).removeView(panel);
        panel=null; status=null; progress=null;
    }
    private static void overlay(Activity activity,String message,final Runnable cancel) {
        removePanel();
        FrameLayout cover=new FrameLayout(activity); cover.setBackgroundColor(0xb0000000); cover.setClickable(true);
        cover.setFocusableInTouchMode(true);
        cover.setOnKeyListener(new View.OnKeyListener() { public boolean onKey(View ignored,int keyCode,KeyEvent event) {
            if (keyCode!=KeyEvent.KEYCODE_BACK) return false;
            if (event.getAction()==KeyEvent.ACTION_UP) cancel.run();
            return true;
        } });
        LinearLayout box=new LinearLayout(activity); box.setOrientation(LinearLayout.VERTICAL);
        int pad=dp(activity,24); box.setPadding(pad,pad,pad,pad); box.setBackgroundColor(0xff20242a);
        TextView title=new TextView(activity); title.setText("Export MP4"); title.setTextColor(0xffffffff); title.setTextSize(20); box.addView(title);
        status=new TextView(activity); status.setTextColor(0xffffffff); status.setPadding(0,pad/2,0,pad/2); status.setText(message); box.addView(status);
        progress=new ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal); progress.setIndeterminate(true); box.addView(progress,new LinearLayout.LayoutParams(-1,-2));
        Button button=new Button(activity); button.setText("Cancel"); box.addView(button);
        button.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) { cancel.run(); } });
        FrameLayout.LayoutParams layout=new FrameLayout.LayoutParams(-1,-2,Gravity.CENTER); layout.leftMargin=pad; layout.rightMargin=pad;
        cover.addView(box,layout);
        View decor=activity.getWindow().getDecorView();
        if (!(decor instanceof ViewGroup)) throw new IllegalStateException("Game window is unavailable");
        ((ViewGroup)decor).addView(cover,new ViewGroup.LayoutParams(-1,-1)); cover.requestFocus(); panel=cover;
    }

    private static void requestSetup(final Activity activity) {
        if (!foreground(activity)) return;
        if (current!=null) { showProgress(activity,current); return; }
        if (saving) { toast(activity,"Wait for the MP4 to finish saving."); return; }
        final long ticket=++generation; querying=true;
        overlay(activity,"Checking the loaded MV…",new Runnable() { public void run() {
            if (ticket==generation) {
                generation++; querying=false; if (pendingQuery!=null) pendingQuery.cancel(); removePanel();
            }
        } });
        query(new SongCallback() {
            public void onSong(final String json) { MAIN.post(new Runnable() { public void run() {
                if (ticket!=generation || !querying) return;
                querying=false; removePanel();
                try { showSetup(activity,new JSONObject(json)); }
                catch (Throwable error) { showError(activity,message(error)); }
            } }); }
            public void onFailed(final String reason) { MAIN.post(new Runnable() { public void run() {
                if (ticket!=generation || !querying) return;
                querying=false; removePanel(); showError(activity,reason);
            } }); }
        });
    }
    public abstract static class SongCallback {
        public abstract void onSong(String json);
        public abstract void onFailed(String reason);
    }
    private static final class PendingQuery extends SongCallback {
        final SongCallback callback;
        boolean settled;
        final Runnable deadline=new Runnable() { public void run() {
            if (settled) return;
            try { nativeCancel(); } catch (Throwable ignored) {}
            complete(null,"The MV did not respond. Resume a loaded MV and try again.");
        } };
        PendingQuery(SongCallback callback) { this.callback=callback; }
        public void onSong(String json) { complete(json,null); }
        public void onFailed(String reason) { complete(null,reason); }
        void cancel() {
            try { nativeCancel(); } catch (Throwable ignored) {}
            complete(null,"Export cancelled");
        }
        void complete(final String json,final String error) {
            if (Looper.myLooper()!=Looper.getMainLooper()) {
                MAIN.post(new Runnable() { public void run() { complete(json,error); } }); return;
            }
            if (settled) return; settled=true; MAIN.removeCallbacks(deadline);
            if (pendingQuery==this) pendingQuery=null;
            if (error==null) callback.onSong(json); else callback.onFailed(error);
        }
    }
    private static void query(SongCallback callback) {
        if (pendingQuery!=null) pendingQuery.cancel();
        PendingQuery request=new PendingQuery(callback); pendingQuery=request;
        MAIN.postDelayed(request.deadline,QUERY_TIMEOUT_MS);
        try { if (nativeQuery(request)!=1) request.onFailed("Load an MV and try again when the game is ready."); }
        catch (UnsatisfiedLinkError error) { request.onFailed("This client does not include the MP4 export backend."); }
        catch (Throwable error) { request.onFailed(message(error)); }
    }
    private static Spinner spinner(Context context,String[] entries) {
        Spinner value=new Spinner(context);
        ArrayAdapter<String> adapter=new ArrayAdapter<String>(context,android.R.layout.simple_spinner_item,entries);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); value.setAdapter(adapter); return value;
    }
    private static void label(LinearLayout parent,String text) { TextView view=new TextView(parent.getContext()); view.setText(text); parent.addView(view); }
    private static boolean ready(JSONObject song) {
        Object value=song.opt("ready"); return Boolean.TRUE.equals(value) || value instanceof Number && ((Number)value).intValue()==1;
    }
    private static void showSetup(final Activity activity,JSONObject song) {
        if (!foreground(activity)) return;
        if (!ready(song)) { showError(activity,"Load a complete MV before exporting."); return; }
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        int pad=dp(activity,20); form.setPadding(pad,pad,pad,pad);
        long duration=song.optLong("music_length_ms",0)/1000;
        label(form,"Export the complete loaded MV with audio. The MV restarts from the beginning.");
        if (duration>0) label(form,String.format(Locale.US,"Duration: %d:%02d",duration/60,duration%60));
        label(form,"Resolution"); final Spinner resolution=spinner(activity,new String[]{"720p · 1280 × 720","1080p · 1920 × 1080"}); form.addView(resolution);
        label(form,"Frame rate"); final Spinner rate=spinner(activity,new String[]{"30 FPS","60 FPS"}); form.addView(rate);
        label(form,"Video codec"); final Spinner codec=spinner(activity,new String[]{"H.264 · broad compatibility","HEVC · device support required"}); form.addView(codec);
        label(form,"Video bitrate (Mbps)"); final EditText bitrate=new EditText(activity);
        bitrate.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL); bitrate.setSingleLine(true); bitrate.setText("5"); form.addView(bitrate);
        Button recommendation=new Button(activity); recommendation.setText("Use recommended bitrate"); form.addView(recommendation);
        recommendation.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
            bitrate.setText(resolution.getSelectedItemPosition()==0?(rate.getSelectedItemPosition()==0?"5":"7.5"):(rate.getSelectedItemPosition()==0?"8":"12"));
        } });
        final File previous=findCompleted(activity);
        if (previous!=null) { Button save=new Button(activity); save.setText("Save previous MP4"); form.addView(save);
            save.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) { offerSave(activity,previous); } }); }
        final AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("Export MP4").setView(form).setNegativeButton("Cancel",null).setPositiveButton("Export",null).create();
        setupDialog=dialog;
        dialog.setOnDismissListener(new android.content.DialogInterface.OnDismissListener() { public void onDismiss(android.content.DialogInterface ignored) {
            if (setupDialog==dialog) setupDialog=null;
        } });
        dialog.setOnShowListener(new android.content.DialogInterface.OnShowListener() { public void onShow(android.content.DialogInterface ignored) {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() { public void onClick(View view) {
                final int width=resolution.getSelectedItemPosition()==0?1280:1920,height=resolution.getSelectedItemPosition()==0?720:1080;
                final int fps=rate.getSelectedItemPosition()==0?30:60; final String mime=codec.getSelectedItemPosition()==0?AndroidMVEncoder.AVC:AndroidMVEncoder.HEVC;
                final int bits;
                try {
                    double mbps=Double.parseDouble(bitrate.getText().toString().trim().replace(',','.'));
                    if (Double.isNaN(mbps)||Double.isInfinite(mbps)||mbps<0.25||mbps>200) throw new IllegalArgumentException();
                    bits=(int)Math.round(mbps*1000000);
                } catch (Throwable error) { bitrate.setError("Enter a bitrate from 0.25 to 200 Mbps"); return; }
                dialog.dismiss(); MAIN.postDelayed(new Runnable() { public void run() { start(activity,width,height,fps,mime,bits); } },150);
            } });
        } }); dialog.show();
    }

    private static final class Session {
        final long id; final Context app; final int width,height,fps,bitrate; final String mime; final File output;
        volatile boolean cancelled,accepted; volatile AndroidMVEncoder encoder;
        long done,total; String phase="Preparing the song audio…";
        Session(Activity activity,int width,int height,int fps,String mime,int bitrate) throws IOException {
            id=++generation; app=activity.getApplicationContext(); this.width=width; this.height=height; this.fps=fps; this.mime=mime; this.bitrate=bitrate;
            File folder=new File(app.getFilesDir(),"MVExports"); if (!folder.isDirectory()&&!folder.mkdirs()) throw new IOException("Cannot create the MP4 output folder");
            output=new File(folder,"MV-"+UUID.randomUUID()+".mp4").getCanonicalFile();
        }
    }
    private static void start(final Activity activity,int width,int height,int fps,String mime,int bitrate) {
        if (!foreground(activity)||current!=null||querying||saving) return;
        final Session session;
        try { session=new Session(activity,width,height,fps,mime,bitrate); }
        catch (Throwable error) { showError(activity,message(error)); return; }
        current=session; showProgress(activity,session);
        // Query again after the configuration dialog closes. Its window may
        // pause Unity, and its earlier selection may have changed meanwhile.
        query(new SongCallback() {
            public void onSong(final String json) { MAIN.post(new Runnable() { public void run() {
                if (current!=session) return;
                if (session.cancelled) { failed(session,"Export cancelled"); return; }
                WORK.execute(new Runnable() { public void run() { prepare(session,json); } });
            } }); }
            public void onFailed(final String reason) { MAIN.post(new Runnable() { public void run() { failed(session,reason); } }); }
        });
    }
    private static void checkEncoder(Session session) throws IOException {
        MediaFormat format=MediaFormat.createVideoFormat(session.mime,session.width,session.height);
        format.setInteger(MediaFormat.KEY_BIT_RATE,session.bitrate);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        if (Build.VERSION.SDK_INT!=21) format.setInteger(MediaFormat.KEY_FRAME_RATE,session.fps);
        if (AndroidMVEncoder.AVC.equals(session.mime)) format.setInteger(MediaFormat.KEY_PROFILE,MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
        MediaCodecList list=new MediaCodecList(MediaCodecList.REGULAR_CODECS); String selected=list.findEncoderForFormat(format);
        if (selected==null) throw new IOException("This device cannot encode that codec, resolution and bitrate. Try H.264 at 720p30.");
        for (MediaCodecInfo info:list.getCodecInfos()) if (selected.equals(info.getName())) {
            MediaCodecInfo.VideoCapabilities caps=info.getCapabilitiesForType(session.mime).getVideoCapabilities();
            if (caps==null||!caps.areSizeAndRateSupported(session.width,session.height,session.fps)||!caps.getBitrateRange().contains(session.bitrate))
                throw new IOException("The requested frame rate or bitrate is unsupported on this device.");
            return;
        }
        throw new IOException("The video encoder is unavailable.");
    }
    private static void prepare(final Session session,String selectedSong) {
        long prepared=0; boolean consumed=false; Throwable failure=null; AndroidMVEncoder encoder=null;
        try {
            if (session.cancelled) throw new IOException("Export cancelled");
            checkEncoder(session);
            prepared=nativePrepare(selectedSong,session.app.getCacheDir().getCanonicalPath(),session.fps);
            if (prepared==0) throw new IOException("The selected MV audio could not be prepared.");
            JSONObject info=new JSONObject(nativePreparedInfo(prepared));
            int sampleRate=info.getInt("sample_rate"),channels=info.getInt("channels");
            long audioFrames=info.getLong("audio_frames"),videoFrames=info.getLong("video_frames");
            if (session.cancelled) throw new IOException("Export cancelled");
            encoder=new AndroidMVEncoder(new AndroidMVEncoder.Config(session.mime,session.width,session.height,session.fps,
                    session.bitrate,videoFrames,sampleRate,channels,192000,audioFrames),session.output);
            session.encoder=encoder;
            if (session.cancelled) throw new IOException("Export cancelled");
            if (nativeBegin(prepared,encoder,session.width,session.height,session.fps,new ExportCallback(session))!=1)
                throw new IOException("The loaded MV changed or the exporter is busy. Load the MV and try again.");
            consumed=true; prepared=0; session.accepted=true;
            if (session.cancelled) { nativeCancel(); encoder.cancel(); }
            MAIN.post(new Runnable() { public void run() { if (current==session&&!session.cancelled) { session.phase="Rendering the full MV…"; updateProgress(session); } } });
        } catch (Throwable error) { failure=error; }
        finally {
            if (!consumed) {
                if (prepared!=0) { try { nativeRelease(prepared); } catch (Throwable error) { if (failure==null) failure=error; } }
                if (encoder!=null) { encoder.cancel(); try { encoder.awaitCompletion(60,TimeUnit.SECONDS); } catch (Throwable ignored) {} }
            }
        }
        if (failure!=null&&!consumed) { final String reason=message(failure); MAIN.post(new Runnable() { public void run() { failed(session,reason); } }); }
    }
    public static final class ExportCallback {
        private final Session session;
        ExportCallback(Session session) { this.session=session; }
        public void onProgress(final long done,final long total) { MAIN.post(new Runnable() { public void run() {
            if (current!=session) return; session.done=done; session.total=total; updateProgress(session);
        } }); }
        public void onFinished(final String path) { MAIN.post(new Runnable() { public void run() {
            if (current!=session) return;
            try {
                File actual=new File(path).getCanonicalFile();
                if (!actual.equals(session.output)||!actual.isFile()||actual.length()==0) throw new IOException("The completed MP4 path is invalid.");
                completed=actual; current=null; removePanel(); Activity activity=game.get();
                if (foreground(activity)) offerSave(activity,actual); else completedWaiting=true;
            } catch (Throwable error) { failed(session,message(error)); }
        } }); }
        public void onFailed(final String reason) { MAIN.post(new Runnable() { public void run() { failed(session,reason); } }); }
    }
    private static void cancel(Session session) {
        if (current!=session) return; session.cancelled=true; session.phase="Cancelling…"; updateProgress(session);
        try { nativeCancel(); } catch (Throwable ignored) {}
        AndroidMVEncoder encoder=session.encoder; if (encoder!=null) encoder.cancel();
    }
    private static void showProgress(Activity activity,final Session session) {
        overlay(activity,session.phase,new Runnable() { public void run() { cancel(session); } }); updateProgress(session);
    }
    private static void updateProgress(Session session) {
        if (current!=session||status==null||progress==null) return;
        status.setText(session.cancelled?"Cancelling…":session.total>0?String.format(Locale.US,"Rendering: %d / %d frames",session.done,session.total):session.phase);
        progress.setIndeterminate(session.total<=0);
        if (session.total>0) { progress.setMax(1000); progress.setProgress((int)Math.min(1000,session.done*1000/session.total)); }
    }
    private static void failed(Session session,String reason) {
        if (current!=session) return; current=null; removePanel(); Activity activity=game.get();
        if (foreground(activity)) { if (session.cancelled) toast(activity,"Export cancelled."); else showError(activity,reason); }
        else { pendingNotice=session.cancelled?"Export cancelled.":reason; pendingNoticeError=!session.cancelled; }
    }

    private static final class SaveRequest {
        final File source; final Context app;
        SaveRequest(Activity activity,File source) { this.source=source; app=activity.getApplicationContext(); }
    }
    private static File findCompleted(Context context) {
        if (completed!=null&&completed.isFile()&&completed.length()>0) return completed;
        File[] files=new File(context.getFilesDir(),"MVExports").listFiles(); File latest=null;
        if (files!=null) for (File file:files) if (file.getName().startsWith("MV-")&&file.getName().endsWith(".mp4")&&file.isFile()&&file.length()>0)
            if (latest==null||file.lastModified()>latest.lastModified()) latest=file;
        completed=latest; return latest;
    }
    private static void offerSave(final Activity activity,final File source) {
        if (!foreground(activity)||!source.isFile()||source.length()==0) return;
        completedWaiting=false;
        new AlertDialog.Builder(activity).setTitle("MP4 export complete").setMessage("Save the MP4 to a folder or document provider. The private copy stays available until saving succeeds.")
            .setNegativeButton("Later",null).setPositiveButton("Save MP4",new android.content.DialogInterface.OnClickListener() { public void onClick(android.content.DialogInterface ignored,int which) {
                if (saving||pendingSave!=null) { toast(activity,"A save request is already open."); return; }
                Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("video/mp4");
                intent.putExtra(Intent.EXTRA_TITLE,source.getName()); intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
                pendingSave=new SaveRequest(activity,source);
                try { activity.startActivityForResult(intent,SAVE_REQUEST); }
                catch (Throwable error) { pendingSave=null; showError(activity,"No document picker is available. The MP4 is kept for saving later."); }
            } }).show();
    }
    /** Actual game Activity override forwards only our SAF result here. */
    public static boolean handleActivityResult(final Activity activity,int requestCode,int resultCode,Intent data) {
        if (requestCode!=SAVE_REQUEST) return false;
        final SaveRequest request=pendingSave; pendingSave=null;
        if (request==null) { toast(activity,"Open Export MP4 to save the retained export."); return true; }
        final Uri uri=data==null?null:data.getData();
        if (resultCode!=Activity.RESULT_OK||uri==null) {
            // The owned completed file stays discoverable through Save previous
            // MP4. Cancelling the picker must not reopen another save prompt.
            completed=request.source; return true;
        }
        saving=true;
        WORK.execute(new Runnable() { public void run() {
            Throwable failure=null;
            try {
                long expected=request.source.length(),copied=0;
                if (expected<=0||!request.source.isFile()) throw new IOException("The private MP4 is unavailable.");
                try (InputStream input=new FileInputStream(request.source); OutputStream output=request.app.getContentResolver().openOutputStream(uri,"w")) {
                    if (output==null) throw new IOException("The document provider did not open the destination.");
                    byte[] block=new byte[1024*1024]; int count;
                    while ((count=input.read(block))!=-1) { output.write(block,0,count); copied+=count; }
                    output.flush();
                }
                if (copied!=expected) throw new IOException("The MP4 copy was incomplete.");
                if (request.source.delete()&&completed!=null&&completed.equals(request.source)) completed=null;
            } catch (Throwable error) { failure=error; }
            final Throwable result=failure;
            MAIN.post(new Runnable() { public void run() {
                saving=false; Activity owner=game.get(); if (!foreground(owner)) {
                    pendingNotice=result==null?"MP4 saved.":"Saving failed. Open Export MP4 to save the retained file.";
                    pendingNoticeError=result!=null; return;
                }
                if (result==null) toast(owner,"MP4 saved."); else showError(owner,"Saving failed. The private MP4 is kept so you can try again. "+message(result));
            } });
        } }); return true;
    }
    private static String message(Throwable error) {
        String text=error.getMessage(); return text==null||text.length()==0?error.getClass().getSimpleName():text;
    }
    private static void showError(Activity activity,String reason) {
        if (usable(activity)) new AlertDialog.Builder(activity).setTitle("MP4 export").setMessage(reason==null?"The export could not be completed.":reason).setPositiveButton("OK",null).show();
    }
}
