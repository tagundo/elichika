package com.klab.lovelive.allstars.fovmod;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.PowerManager;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.ref.WeakReference;
import java.nio.charset.Charset;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Game-local export controls. Audio preparation and document copying use one
 * worker; Unity render work is requested through the native main-thread pump.
 * The progress panel is a View in the game window, so it cannot pause Unity by
 * stealing window focus. It is outside the Unity backbuffer being exported.
 */
public final class AndroidMVExport {
    private static final int SAVE_REQUEST = 0x534d;
    private static final int SAVE_QUEUE_REQUEST = 0x534e;
    private static final int MAX_RENDER_REPORT_BYTES = 12 * 1024;
    private static final int[] WIDTHS = {1280,1920,3840}, HEIGHTS = {720,1080,2160}, RATES = {30,60,120};
    private static final long QUERY_TIMEOUT_MS = 15000;
    private static final long OPEN_TIMEOUT_MS = 130000;
    private static final long BACKGROUND_SERVICE_TIMEOUT_MS = 5000;
    private static final long BACKGROUND_SURFACE_TIMEOUT_MS = 12000;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ExecutorService WORK = Executors.newSingleThreadExecutor(new ThreadFactory() {
        public Thread newThread(Runnable task) { return new Thread(task,"SIFAS-MV-Export-IO"); }
    });
    private static final ExecutorService DOWNLOAD_WORK = Executors.newSingleThreadExecutor(new ThreadFactory() {
        public Thread newThread(Runnable task) { return new Thread(task,"SIFAS-MV-Downloads"); }
    });
    private static final String DOWNLOAD_FOLDER="Download/sukusuta/MV/";
    private static final Set<UUID> downloadsInProgress=new HashSet<>();
    private static boolean downloadsRestored;
    private static WeakReference<Activity> game = new WeakReference<Activity>(null);
    private static long generation;
    private static boolean openWhenResumed, saveWhenResumed, querying, saving, completedWaiting;
    private static boolean gameStarted, gameResumed, gameChangingConfiguration;
    private static boolean queueWhenResumed, queueRunning;
    private static String restartRequired;
    private static int queueNumber,queueCount;
    private static ExportQueue queue;
    private static View panel;
    private static TextView status;
    private static ProgressBar progress;
    private static Session current;
    private static CombinedRun combinedRun;
    // In-memory "Combine into MP4s" plan; one group runs at a time through the
    // existing single-item queue path or the existing combined path.
    private static GroupPlan plan;
    private static FovMod.BackgroundDisplay backgroundDisplay;
    private static long nextServiceToken,serviceToken,displayGeneration;
    private static boolean serviceReady;
    private static String backgroundFailure;
    private static File completed;
    private static SaveRequest pendingSave;
    private static PendingQuery pendingQuery;
    private static String pendingNotice;
    private static boolean pendingNoticeError;
    private static View setupPanel;
    private static View queuePanel;

    private AndroidMVExport() {}

    private static native int nativeQuery(Object callback);
    private static native int nativeQueueSelection(Object callback);
    private static native int nativeQueueOpen(String selectionJson,Object callback);
    private static native long nativePrepare(String selectedSongJson,String cacheRoot,int fps);
    private static native String nativePreparedInfo(long prepared);
    private static native int nativeBegin(long prepared,AndroidMVEncoder encoder,int width,int height,int fps,Object listener);
    private static native void nativeRelease(long prepared);
    private static native void nativeCancel();
    private static native void nativeBackgroundSurfaceChanged();

    /** Started windows remain visible even when the other split pane takes focus. */
    public static void onGameStarted(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameStarted(activity); } }); return;
        }
        if (game.get()!=activity) {
            if (backgroundDisplay!=null) abandonBackgroundDisplay(backgroundDisplay.owner);
            if ((game.get()!=null||current!=null)&&!canAssembleInBackground())
                leaveGame("Android replaced the game window during export.");
            game=new WeakReference<Activity>(activity);
        }
        gameStarted=true; gameChangingConfiguration=false;
        if (!restoreBackgroundDisplay(false)) abortBackground("Unity could not restore its game window.");
        restoreAutomaticDownloads(activity);
        if (queueRunning&&current==null) openNext(activity);
        else if (plan!=null&&current==null&&combinedRun==null&&!queueRunning) advancePlan(activity);
    }

    public static void onGameResumed(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameResumed(activity); } }); return;
        }
        if (game.get()!=activity||!gameStarted) onGameStarted(activity);
        gameResumed=true;
        if (!restoreBackgroundDisplay(false)) abortBackground("Unity could not restore its game window.");
        MAIN.postDelayed(new Runnable() { public void run() {
            if (!foreground(activity)) return;
            if (current!=null) refreshProgress(activity);
            else if (saveWhenResumed) {
                saveWhenResumed=false; File previous=findCompleted(activity);
                if (previous!=null) offerSave(activity,previous); else toast(activity,"No completed MP4 is available.");
            }
            else if (openWhenResumed) {
                openWhenResumed=false; pendingNotice=null; completedWaiting=false; requestSetup(activity);
            }
            else if (queueWhenResumed) {
                queueWhenResumed=false; showQueue(activity);
                if (pendingNotice!=null) { toast(activity,pendingNotice); pendingNotice=null; }
            }
            else if (completedWaiting&&completed!=null&&completed.isFile()) { completedWaiting=false; offerSave(activity,completed); }
            else if (pendingNotice!=null) {
                String message=pendingNotice; boolean error=pendingNoticeError; pendingNotice=null;
                if (error) showError(activity,message); else toast(activity,message);
            }
        } },150);
    }

    /** Focus loss can leave the same Unity window visible and rendering. */
    public static void onGamePaused(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGamePaused(activity); } }); return;
        }
        if (game.get()!=activity) return;
        gameResumed=false;
        if (Build.VERSION.SDK_INT<24||!FovMod.isGlGameActivity(activity)||activity.isFinishing()) {
            leaveGame(activity.isFinishing()?"The game window closed during MP4 export.":null); return;
        }
        // A visible split pane keeps its existing window. For Home or lock,
        // attach before Android removes the original SurfaceView if possible.
        if (serviceToken!=0&&!activity.isChangingConfigurations()) {
            PowerManager power=(PowerManager)activity.getSystemService(Context.POWER_SERVICE);
            if (!activity.isInMultiWindowMode()||(power!=null&&!power.isInteractive())) ensureBackgroundDisplay(activity);
        }
    }

    public static void onGameStopped(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameStopped(activity); } }); return;
        }
        if (game.get()!=activity) return;
        gameStarted=false; gameResumed=false;
        gameChangingConfiguration=activity.isChangingConfigurations();
        if (gameChangingConfiguration) {
            if (!restoreBackgroundDisplay(false)) abortBackground("Unity could not restore the display before changing configuration.");
            return;
        }
        if ((!activity.isFinishing()&&ensureBackgroundDisplay(activity))||canAssembleInBackground()) removePanel();
        else {
            String reason=activity.isFinishing()?"The game window closed during MP4 export.":backgroundFailure;
            if (reason==null && (current!=null||queueRunning)) reason="Android did not start background export before the game became hidden.";
            leaveGame(reason);
        }
    }

    public static void onGameConfigurationChanged(final Activity activity) {
        // Layout is handled by the attached View. Reattach a progress panel if
        // the existing window replaced its decor during the configuration change.
        MAIN.post(new Runnable() { public void run() { if (visible(activity)) refreshProgress(activity); } });
    }

    /** Cancel transport when Unity is actually leaving its window. Native scene
     * restoration runs on the Unity thread; lifecycle callbacks never wait. */
    private static void leaveGame(String interruption) {
        gameStarted=false; gameResumed=false; gameChangingConfiguration=false; queueRunning=false;
        if (plan!=null) plan.stop(interruption==null?"Export cancelled.":interruption);
        if (setupPanel!=null) {
            closeSetup();
            try { nativeCancel(); } catch (Throwable ignored) {}
        }
        if (querying) { generation++; querying=false; }
        if (current!=null) cancel(current,interruption);
        else if (combinedRun!=null) finishCombined(combinedRun,null,interruption==null?QueueState.CANCELLED:QueueState.FAILED,
                interruption==null?"Export cancelled.":interruption);
        else if (plan!=null) finishPlan();
        else stopBackgroundExport();
        if (pendingQuery!=null) pendingQuery.cancel();
        removePanel();
    }
    public static void onGameDestroyed(final Activity activity) {
        if (Looper.myLooper()!=Looper.getMainLooper()) {
            MAIN.post(new Runnable() { public void run() { onGameDestroyed(activity); } }); return;
        }
        Session session=current;
        abandonBackgroundDisplay(activity);
        if (game.get()==activity) {
            if (canAssembleInBackground()) {
                gameStarted=false; gameResumed=false; gameChangingConfiguration=false; removePanel();
            } else leaveGame("The game window closed during MP4 export.");
            game=new WeakReference<Activity>(null);
        }
        if (canAssembleInBackground()) return;
        // A destroyed player cannot supply another frame to deliver its callback.
        if (session==null||current!=session||session.window.get()!=activity) return;
        cancel(session,"The game window closed during MP4 export.");
        if (current!=session||session.ending) return;
        if (session.nativeBeginRequested) {
            restartRequired="The game window closed during MP4 export. Restart the game before exporting again.";
        }
        failed(session,"The game window closed during MP4 export.");
    }

    private static boolean assembling() { return combinedRun!=null&&combinedRun.assembling; }
    private static boolean canAssembleInBackground() { return serviceToken!=0&&assembling(); }

    static boolean keepsBackgroundUnity(Activity activity) {
        return backgroundDisplay!=null&&backgroundDisplay.owner==activity&&!activity.isFinishing();
    }

    private static void startBackgroundExport(Activity activity) {
        if (Build.VERSION.SDK_INT<24||!FovMod.isGlGameActivity(activity)||serviceToken!=0) return;
        backgroundFailure=null;
        final long token=++nextServiceToken;
        serviceToken=token;
        if (!MVExportService.begin(activity,token)) {
            serviceToken=0;
            backgroundFailure="Android could not start the background export service.";
            return;
        }
        // Home can arrive before onStartCommand. Keep the render surface only
        // during this bounded handoff while Android starts the accepted service.
        MAIN.postDelayed(new Runnable() { public void run() {
            if (serviceToken!=token||serviceReady) return;
            serviceToken=0;
            MVExportService.end(token);
            backgroundServiceLost("Android did not start the background export service in time.");
        } },BACKGROUND_SERVICE_TIMEOUT_MS);
    }

    private static void stopBackgroundExport() {
        if (!restoreBackgroundDisplay(!gameStarted)) restartRequired="The Unity display could not be restored. Restart the game before exporting again.";
        long token=serviceToken;
        serviceToken=0; serviceReady=false;
        if (token!=0) MVExportService.end(token);
    }

    static void onBackgroundServiceReady(long token) {
        if (token==serviceToken&&token!=0) serviceReady=true;
    }

    static void onBackgroundServiceStopped(long token) {
        if (token!=serviceToken||token==0) return;
        serviceReady=false; serviceToken=0;
        backgroundServiceLost("Android stopped the background export service.");
    }

    private static void backgroundServiceLost(String reason) {
        backgroundFailure=reason;
        if (!gameStarted) {
            if (current!=null) cancel(current,reason);
            else finishBackgroundWithoutSession(QueueState.FAILED,reason);
        }
        else if (!restoreBackgroundDisplay(false)) abortBackground("Unity could not restore its game window.");
    }

    static void cancelFromBackgroundService(long token) {
        if (token!=serviceToken||token==0) return;
        if (current!=null) cancel(current);
        else finishBackgroundWithoutSession(QueueState.CANCELLED,"Export cancelled.");
    }

    private static boolean ensureBackgroundDisplay(Activity activity) {
        // A plan with groups left keeps Unity rendering while a combined group
        // assembles, so the next group can still start in the background.
        if (serviceToken==0||activity.isFinishing()||(assembling()&&!planContinues())||
                (!queueRunning&&current==null&&plan==null)) return false;
        if (backgroundDisplay!=null) return keepsBackgroundUnity(activity);
        FovMod.BackgroundDisplay carrier=null;
        try {
            final FovMod.BackgroundDisplay prepared=new FovMod.BackgroundDisplay(activity);
            carrier=prepared;
            final long display=++displayGeneration;
            backgroundDisplay=prepared;
            nativeBackgroundSurfaceChanged();
            if (!prepared.attach(new Runnable() { public void run() {
                MAIN.post(new Runnable() { public void run() {
                    if (backgroundDisplay==prepared&&displayGeneration==display) nativeBackgroundSurfaceChanged();
                } });
            } })) throw new IOException("Unity rejected the background render surface.");
            nativeBackgroundSurfaceChanged();
            backgroundFailure=null;
        } catch (Exception | LinkageError | OutOfMemoryError error) {
            Log.w("SIFAS-MV","Could not attach Android background display",error);
            backgroundFailure="Unity could not attach its background render surface. "+message(error);
            backgroundDisplay=null;
            if (carrier!=null) try { carrier.restore(null); }
            catch (Exception rollback) { Log.w("SIFAS-MV","Could not roll back Android background display",rollback); }
            return false;
        }
        final FovMod.BackgroundDisplay attached=carrier;
        MAIN.postDelayed(new Runnable() { public void run() {
            if (backgroundDisplay!=attached) return;
            if (attached.hasPresented()) return;
            // Kept only for a later plan group: release it rather than cancel the
            // assembly of a group whose clips are already rendered.
            if (assembling()) {
                if (!restoreBackgroundDisplay(!gameStarted)) restartRequired="The Unity display could not be restored. Restart the game before exporting again.";
                return;
            }
            abortBackground("Unity did not render to the background surface.");
        } },BACKGROUND_SURFACE_TIMEOUT_MS);
        return true;
    }

    private static boolean restoreBackgroundDisplay(boolean stopped) {
        FovMod.BackgroundDisplay previous=backgroundDisplay;
        if (previous==null) return true;
        backgroundDisplay=null;
        final long display=++displayGeneration;
        try {
            nativeBackgroundSurfaceChanged();
            previous.restore(stopped?null:new Runnable() { public void run() {
                if (displayGeneration==display&&backgroundDisplay==null&&game.get()==previous.owner)
                    nativeBackgroundSurfaceChanged();
            } });
            nativeBackgroundSurfaceChanged();
            return true;
        } catch (Exception | LinkageError error) {
            Log.w("SIFAS-MV","Could not restore the Unity window",error);
            return false;
        } finally {
            if (stopped) MAIN.postDelayed(new Runnable() { public void run() {
                if (displayGeneration!=display||gameStarted||game.get()!=previous.owner||!usable(previous.owner)) return;
                try { previous.pauseStoppedUnity(); }
                catch (Exception error) { Log.w("SIFAS-MV","Could not pause the stopped Unity player",error); }
            } },150);
        }
    }

    private static void abandonBackgroundDisplay(Activity owner) {
        FovMod.BackgroundDisplay previous=backgroundDisplay;
        if (previous==null||previous.owner!=owner) return;
        backgroundDisplay=null;
        ++displayGeneration;
        previous.close();
    }

    private static void abortBackground(String reason) {
        Session affected=current;
        if (affected==null) { finishBackgroundWithoutSession(QueueState.FAILED,reason); return; }
        cancel(affected,reason);
        if (current!=affected||assembling()) return;
        if (affected.nativeBeginRequested) restartRequired=reason+" Restart the game before exporting again.";
        failed(affected,reason);
    }

    private static void finishBackgroundWithoutSession(QueueState state,String reason) {
        queueRunning=false;
        if (plan!=null) plan.stop(reason);
        if (combinedRun!=null) { finishCombined(combinedRun,null,state,reason); return; }
        if (plan!=null) { finishPlan(); return; }
        stopBackgroundExport(); removePanel();
        Activity activity=game.get();
        if (foreground(activity)) { showQueue(activity); toast(activity,reason); }
        else { queueWhenResumed=true; pendingNotice=reason; }
    }

    /** Added to the original settings Activity by the incremental DEX updater. */
    public static void installSettingsButton(final Activity settings,LinearLayout parent) {
        Button button=new Button(settings); button.setText("Export MP4");
        parent.addView(button,new LinearLayout.LayoutParams(-1,-2));
        button.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
            Activity activity=game.get();
            if (!usable(activity)) { toast(settings,"Open the game and load an MV first."); return; }
            saveWhenResumed=false; queueWhenResumed=false; openWhenResumed=true; settings.finish();
        } });
        action(parent,"Export queue",new Runnable() { public void run() {
            if (!usable(game.get())) { toast(settings,"Open the game to see the export queue."); return; }
            openWhenResumed=false; saveWhenResumed=false; queueWhenResumed=true; settings.finish();
        } });
        final File previous=findCompleted(settings.getApplicationContext());
        if (previous!=null) {
            Button save=new Button(settings); save.setText("Save last completed MP4");
            parent.addView(save,new LinearLayout.LayoutParams(-1,-2));
            save.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
                Activity activity=game.get();
                if (!usable(activity)) { toast(settings,"Open the game to save the retained MP4."); return; }
                openWhenResumed=false; queueWhenResumed=false; saveWhenResumed=true; settings.finish();
            } });
            addRenderReportButton(settings,parent,previous,null);
        }
    }

    /** In-game controls stay in the existing Activity and window. */
    static void installInGameButtons(final Activity activity,LinearLayout parent,final Runnable close) {
        Button export=new Button(activity); export.setText("Export MP4"); parent.addView(export);
        export.setOnClickListener(new View.OnClickListener() { public void onClick(View view) {
            if (!foreground(activity)) return;
            close.run(); openWhenResumed=false; saveWhenResumed=false; queueWhenResumed=false; pendingNotice=null; completedWaiting=false; requestSetup(activity);
        } });
        action(parent,"Export queue",new Runnable() { public void run() { close.run(); showQueue(activity); } });
        final File previous=findCompleted(activity);
        if (previous!=null) {
            Button save=new Button(activity); save.setText("Save last completed MP4"); parent.addView(save);
            save.setOnClickListener(new View.OnClickListener() { public void onClick(View view) { close.run(); offerSave(activity,previous); } });
            addRenderReportButton(activity,parent,previous,close);
        }
    }

    /** The corner settings gesture remains inactive while an export owns the MV. */
    public static boolean isBusy() { return current!=null || combinedRun!=null || plan!=null || queueRunning || querying || saving; }

    private static boolean usable(Activity activity) {
        return activity!=null && !activity.isFinishing() && (Build.VERSION.SDK_INT<17 || !activity.isDestroyed());
    }
    private static boolean visible(Activity activity) { return usable(activity)&&gameStarted&&game.get()==activity; }
    private static boolean foreground(Activity activity) { return visible(activity)&&gameResumed; }
    private static boolean canDriveExport(Activity activity) {
        return visible(activity)||(usable(activity)&&game.get()==activity&&keepsBackgroundUnity(activity));
    }
    private static boolean retainsSession(Activity activity) {
        return canDriveExport(activity)||(usable(activity)&&gameChangingConfiguration&&game.get()==activity);
    }
    private static int dp(Context context,int value) { return (int)(value*context.getResources().getDisplayMetrics().density+0.5f); }
    private static void toast(Context context,String text) { Toast.makeText(context,text,Toast.LENGTH_LONG).show(); }
    private static void removePanel() {
        FovMod.dismissGamePanel(panel);
        panel=null; status=null; progress=null;
    }
    private static void overlay(Activity activity,String message,final Runnable cancel) {
        removePanel();
        LinearLayout box=new LinearLayout(activity); box.setOrientation(LinearLayout.VERTICAL);
        int pad=dp(activity,24);
        status=new TextView(activity); status.setTextColor(0xffffffff); status.setPadding(0,pad/2,0,pad/2); status.setText(message); box.addView(status);
        progress=new ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal); progress.setIndeterminate(true); box.addView(progress,new LinearLayout.LayoutParams(-1,-2));
        Button button=new Button(activity); button.setText(plan!=null?"Cancel all MP4s":current!=null&&current.item!=null&&current.combined==null?"Cancel queue":"Cancel"); box.addView(button);
        button.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) { cancel.run(); } });
        panel=FovMod.showGamePanel(activity,"Export MP4",box,cancel);
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
        final String timeoutMessage;
        boolean settled;
        final Runnable deadline=new Runnable() { public void run() {
            if (settled) return;
            try { nativeCancel(); } catch (Throwable ignored) {}
            complete(null,timeoutMessage);
        } };
        PendingQuery(SongCallback callback,String timeoutMessage) { this.callback=callback; this.timeoutMessage=timeoutMessage; }
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
    private interface Request { int submit(Object callback); }

    private static void query(SongCallback callback) {
        request(callback,new Request() { public int submit(Object request) { return nativeQuery(request); } },QUERY_TIMEOUT_MS,
                "Load an MV and try again when the game is ready.","The MV did not respond. Resume a loaded MV and try again.");
    }

    private static void request(SongCallback callback,Request dispatch,long timeout,String rejected,String timedOut) {
        if (pendingQuery!=null) pendingQuery.cancel();
        PendingQuery request=new PendingQuery(callback,timedOut); pendingQuery=request;
        MAIN.postDelayed(request.deadline,timeout);
        try { if (dispatch.submit(request)!=1) request.onFailed(rejected); }
        catch (UnsatisfiedLinkError error) { request.onFailed("This client does not include the MP4 export backend."); }
        catch (Throwable error) { request.onFailed(message(error)); }
    }
    private static void label(LinearLayout parent,String text) { TextView view=new TextView(parent.getContext()); view.setText(text); view.setTextColor(0xffffffff); parent.addView(view); }
    private static Button action(LinearLayout parent,String text,Runnable run) {
        Button button=new Button(parent.getContext()); button.setText(text); parent.addView(button);
        button.setOnClickListener(new View.OnClickListener() { public void onClick(View view) { run.run(); } });
        return button;
    }
    private static int pixelDimension(String text) {
        int value=Integer.parseInt(text.trim());
        if (value<16||value>32768||(value&1)!=0) throw new IllegalArgumentException("Use even pixels from 16 to 32768.");
        return value;
    }
    private static int[] dimensions(EditText width,EditText height) {
        final int w,h;
        try { w=pixelDimension(width.getText().toString()); }
        catch (IllegalArgumentException error) { width.setError("Use even pixels from 16 to 32768."); throw error; }
        try { h=pixelDimension(height.getText().toString()); }
        catch (IllegalArgumentException error) { height.setError("Use even pixels from 16 to 32768."); throw error; }
        MVExportContract.i420Bytes(w,h);
        if ((long)w*h>Integer.MAX_VALUE/4) { width.setError("Dimensions exceed the RGBA buffer integer range."); throw new IllegalArgumentException("RGBA buffer integer range exceeded"); }
        return new int[]{w,h};
    }
    private static boolean ready(JSONObject song) {
        Object value=song.opt("ready"); return Boolean.TRUE.equals(value) || value instanceof Number && ((Number)value).intValue()==1;
    }
    private static void showSetup(final Activity activity,JSONObject song) {
        if (!retainsSession(activity)) return;
        if (!ready(song)) { showError(activity,"Load a complete MV before exporting."); return; }
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        int pad=dp(activity,20); form.setPadding(pad,pad,pad,pad);
        long duration=song.optLong("music_length_ms",0)/1000;
        label(form,"Export the complete loaded MV with audio. The MV restarts from the beginning.");
        if (duration>0) label(form,String.format(Locale.US,"Duration: %d:%02d",duration/60,duration%60));
        final SharedPreferences preferences=activity.getSharedPreferences("mv_export",Context.MODE_PRIVATE);
        int legacyResolution=Math.max(0,Math.min(WIDTHS.length-1,preferences.getInt("resolution",0)));
        label(form,"Width (pixels; even)"); final EditText widthPixels=new EditText(activity);
        widthPixels.setInputType(InputType.TYPE_CLASS_NUMBER); widthPixels.setSingleLine(true); widthPixels.setTextColor(0xffffffff);
        widthPixels.setText(Integer.toString(preferences.getInt("width",WIDTHS[legacyResolution]))); form.addView(widthPixels);
        label(form,"Height (pixels; even)"); final EditText heightPixels=new EditText(activity);
        heightPixels.setInputType(InputType.TYPE_CLASS_NUMBER); heightPixels.setSingleLine(true); heightPixels.setTextColor(0xffffffff);
        heightPixels.setText(Integer.toString(preferences.getInt("height",HEIGHTS[legacyResolution]))); form.addView(heightPixels);
        label(form,"Frame rate"); final FovMod.InlineChoice rate=new FovMod.InlineChoice(activity,new String[]{"30 FPS","60 FPS","120 FPS"}); form.addView(rate);
        label(form,"Video codec"); final FovMod.InlineChoice codec=new FovMod.InlineChoice(activity,new String[]{"H.264 · broad compatibility","HEVC · device support required"}); form.addView(codec);
        label(form,"Offline export may encode slower than the selected FPS. Device reports are advisory; actual encoder startup decides.");
        rate.setSelection(Math.max(0,Math.min(RATES.length-1,preferences.getInt("rate",0))));
        codec.setSelection(Math.max(0,Math.min(1,preferences.getInt("codec",0))));
        final TextView advisory=new TextView(activity); advisory.setTextColor(0xffffffff); form.addView(advisory);
        final Runnable updateAdvisory=new Runnable() { public void run() {
            try {
                int width=pixelDimension(widthPixels.getText().toString()),height=pixelDimension(heightPixels.getText().toString());
                MVExportContract.i420Bytes(width,height);
                advisory.setText(AndroidMVEncoder.videoEncoderAdvisory(codec.getSelectedItemPosition()==0?AndroidMVEncoder.AVC:AndroidMVEncoder.HEVC,width,height));
            } catch (IllegalArgumentException error) { advisory.setText("Width and height must each be even pixel counts from 16 to 32768. Any aspect ratio is allowed."); }
        } };
        codec.setOnSelectionChanged(updateAdvisory);
        TextWatcher sizeChanged=new TextWatcher() {
            public void beforeTextChanged(CharSequence text,int start,int count,int after) {}
            public void onTextChanged(CharSequence text,int start,int before,int count) { updateAdvisory.run(); }
            public void afterTextChanged(Editable text) {}
        };
        widthPixels.addTextChangedListener(sizeChanged); heightPixels.addTextChangedListener(sizeChanged); updateAdvisory.run();
        label(form,"Video bitrate (Mbps)"); final EditText bitrate=new EditText(activity);
        bitrate.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL); bitrate.setSingleLine(true); bitrate.setTextColor(0xffffffff); bitrate.setText(preferences.getString("bitrate_mbps","5")); form.addView(bitrate);
        Button recommendation=new Button(activity); recommendation.setText("Use recommended bitrate"); form.addView(recommendation);
        recommendation.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) {
            try {
                int[] size=dimensions(widthPixels,heightPixels);
                double mbps=(double)size[0]*size[1]*RATES[rate.getSelectedItemPosition()]*(codec.getSelectedItemPosition()==0?0.14:0.09)/1000000.0;
                bitrate.setText(String.format(Locale.US,"%.2f",Math.min(Integer.MAX_VALUE/1000000.0,Math.max(0.25,mbps))));
            } catch (IllegalArgumentException error) { return; }
        } });
        final File previous=findCompleted(activity);
        if (previous!=null) { Button save=new Button(activity); save.setText("Save previous MP4"); form.addView(save);
            save.setOnClickListener(new View.OnClickListener() { public void onClick(View ignored) { offerSave(activity,previous); } }); }
        final Runnable close=new Runnable() { public void run() { FovMod.dismissGamePanel(setupPanel); setupPanel=null; } };
        action(form,"Export",new Runnable() { public void run() {
            ExportOptions options=readOptions(widthPixels,heightPixels,rate,codec,bitrate,preferences);
            if (options==null) return;
            close.run(); start(activity,options);
        } });
        action(form,"Add to export queue",new Runnable() { public void run() {
            ExportOptions options=readOptions(widthPixels,heightPixels,rate,codec,bitrate,preferences);
            if (options==null) return;
            close.run(); registerQueued(activity,options);
        } });
        action(form,"View export queue",new Runnable() { public void run() { close.run(); showQueue(activity); } });
        action(form,"Cancel",close);
        setupPanel=FovMod.showGamePanel(activity,"Export MP4",form,close);
    }

    private static final class ExportOptions {
        final int width,height,fps,bitrate;
        final String mime;

        ExportOptions(int width,int height,int fps,String mime,int bitrate) {
            MVExportContract.validateVideo(mime,width,height,fps,bitrate,1);
            if ((long)width*height>Integer.MAX_VALUE/4) throw new IllegalArgumentException("RGBA buffer integer range exceeded");
            this.width=width; this.height=height; this.fps=fps; this.mime=mime; this.bitrate=bitrate;
        }

        static ExportOptions read(JSONObject json) throws JSONException {
            return new ExportOptions(json.getInt("width"),json.getInt("height"),json.getInt("fps"),
                    json.getString("mime"),json.getInt("bitrate"));
        }

        JSONObject json() throws JSONException {
            return new JSONObject().put("width",width).put("height",height).put("fps",fps).put("mime",mime).put("bitrate",bitrate);
        }

        String description() {
            return String.format(Locale.US,"%d×%d · %d FPS · %s · %.6g Mbps",width,height,fps,
                    AndroidMVEncoder.AVC.equals(mime)?"H.264":"HEVC",bitrate/1000000.0);
        }
    }

    private static ExportOptions readOptions(EditText width,EditText height,FovMod.InlineChoice rate,
            FovMod.InlineChoice codec,EditText bitrate,SharedPreferences preferences) {
        final int[] size;
        try { size=dimensions(width,height); }
        catch (IllegalArgumentException error) { return null; }
        int rateIndex=rate.getSelectedItemPosition(),codecIndex=codec.getSelectedItemPosition();
        String text=bitrate.getText().toString().trim();
        final ExportOptions options;
        try {
            double mbps=Double.parseDouble(text.replace(',','.'));
            long bits=Math.round(mbps*1000000);
            if (Double.isNaN(mbps)||Double.isInfinite(mbps)||mbps<=0||bits<1||bits>Integer.MAX_VALUE) throw new IllegalArgumentException();
            options=new ExportOptions(size[0],size[1],RATES[rateIndex],codecIndex==0?AndroidMVEncoder.AVC:AndroidMVEncoder.HEVC,(int)bits);
        } catch (IllegalArgumentException error) {
            bitrate.setError("Enter a positive bitrate up to 2147.483647 Mbps (whole bits/sec)."); return null;
        }
        preferences.edit().putInt("width",options.width).putInt("height",options.height).putInt("rate",rateIndex)
                .putInt("codec",codecIndex).putString("bitrate_mbps",text).apply();
        return options;
    }

    private enum QueueState { WAITING, ACTIVE, COMPLETED, FAILED, CANCELLED }

    private static final class QueueItem {
        final UUID id;
        final String selection,title,description,selectionDescription,fileName,downloadName,detail;
        final ExportOptions options;
        final long fov;
        final QueueState state;
        final boolean autoDownload;
        final List<UUID> sources;

        QueueItem(UUID id,String selection,ExportOptions options,long fov,QueueState state,String detail,boolean autoDownload) throws JSONException {
            this(id,selection,options,fov,state,detail,autoDownload,Collections.emptyList());
        }

        QueueItem(UUID id,String selection,ExportOptions options,long fov,QueueState state,String detail,boolean autoDownload,
                List<UUID> sources) throws JSONException {
            JSONObject mv=new JSONObject(selection);
            int live=mv.getInt("live_id");
            int stage=mv.getInt("stage_id");
            if (live<=0 || stage<0 || !FovMod.validExportFov(fov)) throw new IllegalArgumentException("Invalid queued MV settings");
            this.id=id; this.selection=selection; this.options=options; this.fov=fov;
            this.state=state; this.detail=detail; this.autoDownload=autoDownload;
            if (!sources.isEmpty()&&(sources.size()<2||sources.size()>AndroidMVEncoder.MAX_SEGMENTS||
                    new HashSet<>(sources).size()!=sources.size()||sources.contains(id)))
                throw new IllegalArgumentException("Invalid combined MV selection");
            this.sources=Collections.unmodifiableList(new ArrayList<>(sources));
            if (isCombined()) {
                title="Combined MV · "+sources.size()+" clips";
                fileName="MV-Combined-"+id+".mp4";
                downloadName=String.format(Locale.ROOT,"Combined MV - %d clips - %dx%d %dfps %s %dbps - %s.mp4",
                        sources.size(),options.width,options.height,options.fps,AndroidMVEncoder.AVC.equals(options.mime)?"H264":"HEVC",
                        options.bitrate,id.toString().substring(0,8));
                description=options.description();
                selectionDescription="";
                return;
            }
            String cue=mv.optString("cue_name","");
            String song=mv.optString("song_title","");
            title=!song.isEmpty()?song:cue.isEmpty()?"MV "+live:cue;
            fileName="MV-"+live+"-"+id+".mp4";
            downloadName=downloadName(title,live,stage,mv.optInt("deck_type"),options,fov);
            String bounds=String.format(Locale.US,"FOV %.5f / %.5f",
                    Float.intBitsToFloat((int)fov),Float.intBitsToFloat((int)(fov>>>32)));
            description="Stage "+stage+" · "+options.description()+" · "+bounds;
            selectionDescription="Stage "+stage+" · "+bounds;
        }

        static QueueItem read(JSONObject json) throws JSONException {
            JSONArray group=json.optJSONArray("combined_sources");
            List<UUID> sources=new ArrayList<>();
            if (group!=null) for (int i=0;i<group.length();i++) sources.add(UUID.fromString(group.getString(i)));
            return new QueueItem(UUID.fromString(json.getString("id")),json.getString("selection"),
                    ExportOptions.read(json.getJSONObject("video")),json.getLong("fov"),
                    QueueState.valueOf(json.getString("state")),json.optString("detail",""),json.optBoolean("auto_download",false),sources);
        }

        JSONObject json() throws JSONException {
            JSONObject result=new JSONObject().put("id",id.toString()).put("selection",selection).put("video",options.json())
                    .put("fov",fov).put("state",state.name()).put("detail",detail).put("auto_download",autoDownload);
            if (isCombined()) {
                JSONArray group=new JSONArray();
                for (UUID source:sources) group.put(source.toString());
                result.put("combined_sources",group);
            }
            return result;
        }

        QueueItem changed(QueueState next,String reason) throws JSONException {
            return new QueueItem(id,selection,options,fov,next,reason==null?"":reason,
                    autoDownload||(next==QueueState.ACTIVE&&Build.VERSION.SDK_INT>=29),sources);
        }

        QueueItem withAutomaticDownload() throws JSONException {
            return new QueueItem(id,selection,options,fov,state,detail,true,sources);
        }

        boolean isCombined() { return !sources.isEmpty(); }
        File output(Context app) { return new File(new File(app.getFilesDir(),"MVExports/Queue"),fileName); }
        boolean hasOutput(Context app) { File path=output(app); return path.isFile()&&path.length()>0; }

        void discardInterruptedFiles(Context app) {
            File output=output(app);
            File[] partial=output.getParentFile().listFiles(new java.io.FilenameFilter() {
                public boolean accept(File dir,String name) { return name.startsWith("."+fileName+".")&&name.endsWith(".partial"); }
            });
            if (partial!=null) for (File leftover:partial) leftover.delete();
            if (output.isFile()&&output.length()==0) output.delete();
        }
    }

    private static final class ExportQueue {
        private static final String LIST="items_v1";
        final SharedPreferences storage;
        List<QueueItem> items;

        ExportQueue(Context app) throws IOException,JSONException {
            storage=app.getSharedPreferences("mv_export_queue",Context.MODE_PRIVATE);
            JSONArray saved=new JSONArray(storage.getString(LIST,"[]"));
            ArrayList<QueueItem> restored=new ArrayList<>(saved.length());
            boolean recovered=false;
            for (int index=0;index<saved.length();index++) {
                QueueItem item=QueueItem.read(saved.getJSONObject(index));
                if (item.state==QueueState.ACTIVE) {
                    item.discardInterruptedFiles(app);
                    // The encoder installs a non-empty output only after finalization.
                    item=item.changed(item.hasOutput(app)?QueueState.COMPLETED:QueueState.WAITING,"");
                    recovered=true;
                } else if (item.state==QueueState.COMPLETED&&!item.hasOutput(app)&&downloadReceipt(app,item)==null) {
                    item=item.changed(QueueState.FAILED,"The private MP4 is missing.");
                    recovered=true;
                }
                restored.add(item);
            }
            if (recovered) save(restored); else items=restored;
            File[] abandoned=combinedScratch(app).listFiles();
            if (abandoned!=null) WORK.execute(new Runnable() { public void run() {
                for (File folder:abandoned) if (folder.getName().startsWith("group-")) cleanCombinedScratch(folder);
            } });
        }

        void save(List<QueueItem> next) throws IOException,JSONException {
            JSONArray json=new JSONArray();
            for (QueueItem item:next) json.put(item.json());
            if (!storage.edit().putString(LIST,json.toString()).commit()) throw new IOException("Could not save the export queue.");
            items=next;
        }

        QueueItem change(QueueItem item,QueueState next,String reason) throws IOException,JSONException {
            List<QueueItem> updated=new ArrayList<>(items);
            for (int index=0;index<updated.size();index++) if (updated.get(index).id.equals(item.id)) {
                QueueItem changed=updated.get(index).changed(next,reason);
                updated.set(index,changed); save(updated); return changed;
            }
            throw new IOException("The queued MV entry changed.");
        }
    }

    private static ExportQueue exportQueue(Context context) throws IOException,JSONException {
        if (queue==null) queue=new ExportQueue(context.getApplicationContext());
        return queue;
    }

    private static String downloadName(String title,int live,int stage,int deck,ExportOptions video,long fov) {
        String normalized=Normalizer.normalize(title,Normalizer.Form.NFC);
        StringBuilder name=new StringBuilder();
        int bytes=0;
        boolean space=false;
        for (int offset=0;offset<normalized.length();) {
            int character=normalized.codePointAt(offset);
            offset+=Character.charCount(character);
            int type=Character.getType(character);
            if (Character.isWhitespace(character)||Character.isSpaceChar(character)||
                    type==Character.CONTROL||type==Character.FORMAT||type==Character.SURROGATE||
                    "/\\:*?\"<>|".indexOf(character)>=0) {
                space=name.length()>0;
                continue;
            }
            if (name.length()==0&&character=='.') continue;
            int size=character<=0x7f?1:character<=0x7ff?2:character<=0xffff?3:4;
            if (bytes+size+(space?1:0)>112) break;
            if (space) { name.append(' '); bytes++; space=false; }
            name.appendCodePoint(character); bytes+=size;
        }
        while (name.length()>0&&name.charAt(name.length()-1)=='.') name.setLength(name.length()-1);
        String prefix=name.length()==0||name.toString().equals("MV "+live)?"MV "+live:name+" - MV "+live;
        String deckName=deck==1?" Original":deck==2?" Custom":"";
        String codec=AndroidMVEncoder.AVC.equals(video.mime)?"H264":"HEVC";
        return String.format(Locale.ROOT,"%s - Stage %d%s - %dx%d %dfps %s %dbps - FOV %s-%s.mp4",
                prefix,stage,deckName,video.width,video.height,video.fps,codec,video.bitrate,
                Float.toString(Float.intBitsToFloat((int)fov)),Float.toString(Float.intBitsToFloat((int)(fov>>>32))));
    }

    private static SharedPreferences downloadJournal(Context app) {
        return app.getSharedPreferences("mv_download_delivery",Context.MODE_PRIVATE);
    }

    private static final class DownloadReceipt {
        final long row, size;
        final String name, digest;
        DownloadReceipt(long row,long size,String name,String digest) {
            this.row=row; this.size=size; this.name=name; this.digest=digest;
        }
    }

    private static DownloadReceipt downloadReceipt(Context app,QueueItem item) {
        if (!item.autoDownload) return null;
        SharedPreferences journal=downloadJournal(app);
        String key=item.id.toString();
        long row=journal.getLong(key+".row",0);
        long size=journal.getLong(key+".size",0);
        String name=journal.getString(key+".name","");
        String digest=journal.getString(key+".sha256","");
        return row>0&&size>0&&!name.isEmpty()&&digest.matches("[0-9a-f]{64}")?
                new DownloadReceipt(row,size,name,digest):null;
    }

    private static void restoreAutomaticDownloads(Context app) {
        if (downloadsRestored||Build.VERSION.SDK_INT<29) return;
        downloadsRestored=true;
        try {
            for (QueueItem item:exportQueue(app).items) {
                if (item.state==QueueState.COMPLETED&&item.autoDownload&&item.hasOutput(app)) moveToDownloads(app,item);
            }
        } catch (IOException|JSONException|RuntimeException error) {
            // The queue screen reports unreadable saved queue state.
        }
    }

    private static void moveToDownloads(Context context,QueueItem item) {
        if (Build.VERSION.SDK_INT<29||!downloadsInProgress.add(item.id)) return;
        Context app=context.getApplicationContext();
        DOWNLOAD_WORK.execute(new Runnable() { public void run() {
            SharedPreferences journal=downloadJournal(app);
            String key=item.id.toString();
            try {
                ScopedDownloads.move(app,item,journal);
                journal.edit().remove(key+".error").apply();
            } catch (IOException|RuntimeException error) {
                journal.edit().putString(key+".error",message(error)).apply();
            }
            MAIN.post(new Runnable() { public void run() {
                downloadsInProgress.remove(item.id);
                Activity activity=game.get();
                if (foreground(activity)&&queuePanel!=null&&setupPanel==queuePanel) showQueue(activity);
            } });
        } });
    }

    private static void requestDownload(Activity activity,ExportQueue entries,QueueItem item) {
        if (Build.VERSION.SDK_INT<29||downloadsInProgress.contains(item.id)||
                item.state!=QueueState.COMPLETED||!item.hasOutput(activity)) return;
        try {
            if (!item.autoDownload) {
                List<QueueItem> updated=new ArrayList<>(entries.items);
                int index=updated.indexOf(item);
                if (index<0) throw new IOException("The queued MV entry changed.");
                item=item.withAutomaticDownload();
                updated.set(index,item); entries.save(updated);
            }
            moveToDownloads(activity,item); showQueue(activity);
        } catch (IOException|JSONException error) { showError(activity,message(error)); }
    }

    private static void openDownload(Activity activity,DownloadReceipt receipt) {
        if (Build.VERSION.SDK_INT<29) return;
        Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(ScopedDownloads.uri(receipt.row),"video/mp4")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { activity.startActivity(intent); }
        catch (RuntimeException error) { toast(activity,DOWNLOAD_FOLDER+receipt.name); }
    }

    /** Owns only this application's Download rows. The private encoder file is
     * the retry source until both public readback and journal commit succeed. */
    private static final class ScopedDownloads {
        private static final String MIME="video/mp4";
        private static final String[] COLUMNS={
                MediaStore.MediaColumns._ID,MediaStore.MediaColumns.DISPLAY_NAME,MediaStore.MediaColumns.RELATIVE_PATH,
                MediaStore.MediaColumns.OWNER_PACKAGE_NAME,MediaStore.MediaColumns.MIME_TYPE,MediaStore.MediaColumns.IS_PENDING
        };

        private static Uri collection() {
            return MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
        }

        static Uri uri(long row) { return ContentUris.withAppendedId(collection(),row); }

        private static final class Row {
            final long id;
            final String name, folder, owner, mime;
            final boolean pending;
            Row(Cursor data) {
                id=data.getLong(0); name=data.getString(1); folder=data.getString(2);
                owner=data.getString(3); mime=data.getString(4); pending=data.getInt(5)==1;
            }
        }

        @SuppressWarnings("deprecation")
        private static Row query(Context app,Uri query,String selection,String[] arguments) throws IOException {
            try (Cursor result=app.getContentResolver().query(MediaStore.setIncludePending(query),COLUMNS,
                    selection,arguments,null)) {
                if (result==null) throw new IOException("Downloads did not return a verified result.");
                if (!result.moveToFirst()) return null;
                Row row=new Row(result);
                if (result.moveToNext()||row.id<=0||!app.getPackageName().equals(row.owner)||
                        !DOWNLOAD_FOLDER.equals(row.folder)||!MIME.equalsIgnoreCase(row.mime))
                    throw new IOException("Downloads returned an unexpected destination.");
                return row;
            }
        }

        private static Row read(Context app,long row) throws IOException {
            Row result=query(app,uri(row),null,null);
            if (result!=null&&result.id!=row) throw new IOException("Downloads returned a different MP4 row.");
            return result;
        }

        private static String marker(QueueItem item) { return "sifas-mv-pending-"+item.id+".mp4"; }

        private static Row reserve(Context app,QueueItem item) throws IOException {
            String pending=marker(item);
            String filter=MediaStore.MediaColumns.DISPLAY_NAME+"=? AND "+MediaStore.MediaColumns.RELATIVE_PATH+
                    "=? AND "+MediaStore.MediaColumns.OWNER_PACKAGE_NAME+"=? AND "+MediaStore.MediaColumns.IS_PENDING+"=1";
            Row recovered=query(app,collection(),filter,new String[]{pending,DOWNLOAD_FOLDER,app.getPackageName()});
            if (recovered!=null) return recovered;
            ContentValues values=new ContentValues();
            values.put(MediaStore.MediaColumns.DISPLAY_NAME,pending);
            values.put(MediaStore.MediaColumns.MIME_TYPE,MIME);
            values.put(MediaStore.MediaColumns.RELATIVE_PATH,DOWNLOAD_FOLDER);
            values.put(MediaStore.MediaColumns.IS_PENDING,1);
            Uri created=app.getContentResolver().insert(collection(),values);
            if (created==null) throw new IOException("Downloads could not reserve an MP4.");
            long id=ContentUris.parseId(created);
            Row row=id>0?read(app,id):null;
            if (row==null||!row.pending||!pending.equals(row.name)) throw new IOException("The reserved MP4 could not be verified.");
            return row;
        }

        private static MessageDigest sha256() {
            try { return MessageDigest.getInstance("SHA-256"); }
            catch (NoSuchAlgorithmException error) { throw new IllegalStateException("SHA-256 is unavailable.",error); }
        }

        private static String hash(InputStream input,OutputStream output,long length) throws IOException {
            MessageDigest digest=sha256();
            byte[] bytes=new byte[256*1024];
            long copied=0;
            int count;
            while ((count=input.read(bytes))!=-1) {
                copied+=count;
                if (copied>length) throw new IOException("The MP4 grew during transfer.");
                if (output!=null) output.write(bytes,0,count);
                digest.update(bytes,0,count);
            }
            if (copied!=length) throw new IOException("The MP4 transfer was incomplete.");
            final String digits="0123456789abcdef";
            StringBuilder text=new StringBuilder(64);
            for (byte value:digest.digest()) text.append(digits.charAt((value&255)>>>4)).append(digits.charAt(value&15));
            return text.toString();
        }

        private static String privateHash(File source,long length) throws IOException {
            try (InputStream input=new FileInputStream(source)) { return hash(input,null,length); }
        }

        private static String copy(ContentResolver resolver,File source,Uri target,long length) throws IOException {
            try (InputStream input=new FileInputStream(source)) {
                ParcelFileDescriptor file=resolver.openFileDescriptor(target,"rwt");
                if (file==null) throw new IOException("Downloads did not open the MP4 for writing.");
                try (ParcelFileDescriptor.AutoCloseOutputStream output=new ParcelFileDescriptor.AutoCloseOutputStream(file)) {
                    String digest=hash(input,output,length);
                    output.flush();
                    output.getFD().sync();
                    if (file.getStatSize()!=length) throw new IOException("The pending MP4 size could not be verified.");
                    return digest;
                }
            }
        }

        private static boolean finalName(String desired,String actual) {
            if (desired.equals(actual)) return true;
            String prefix=desired.substring(0,desired.length()-4)+" (";
            if (actual==null||!actual.startsWith(prefix)||!actual.endsWith(").mp4")) return false;
            String suffix=actual.substring(prefix.length(),actual.length()-5);
            return suffix.matches("[0-9]+");
        }

        private static void verifyPayload(Context app,Row row,long expected,String digest) throws IOException {
            try (InputStream input=app.getContentResolver().openInputStream(uri(row.id))) {
                if (input==null||!digest.equals(hash(input,null,expected)))
                    throw new IOException("The Downloads MP4 bytes differ from the private export.");
            }
        }

        private static void verifyPublishedSize(Context app,Row row,long expected) throws IOException {
            if (row==null||row.pending) throw new IOException("The MP4 was not published to Downloads.");
            try (ParcelFileDescriptor file=app.getContentResolver().openFileDescriptor(uri(row.id),"r")) {
                if (file==null||file.getStatSize()!=expected)
                    throw new IOException("The published MP4 size could not be verified.");
            }
        }

        private static void discardUnusedReservation(Context app,QueueItem item,long id) {
            try {
                Row row=read(app,id);
                if (row!=null&&row.pending&&marker(item).equals(row.name))
                    app.getContentResolver().delete(uri(id),null,null);
            } catch (IOException|RuntimeException ignored) {
                // Keep the recorded row for the next retry if deletion is uncertain.
            }
        }

        static void move(Context app,QueueItem item,SharedPreferences journal) throws IOException {
            File source=item.output(app);
            String key=item.id.toString();
            DownloadReceipt receipt=downloadReceipt(app,item);
            if (receipt!=null) {
                if (!source.exists()) return;
                Row published=read(app,receipt.row);
                if (published==null||!receipt.name.equals(published.name)||
                        !receipt.digest.equals(privateHash(source,receipt.size)))
                    throw new IOException("The previous Downloads receipt no longer matches the private MP4.");
                verifyPublishedSize(app,published,receipt.size);
                verifyPayload(app,published,receipt.size,receipt.digest);
            } else {
                long expected=source.length();
                if (!source.isFile()||expected<=0) throw new IOException("The private MP4 is unavailable.");
                long recorded=journal.getLong(key+".row",0);
                String name=journal.getString(key+".target",item.downloadName);
                Row row=recorded>0?read(app,recorded):null;
                if (row==null) {
                    if (journal.getBoolean(key+".publishing",false))
                        throw new IOException("The previous Downloads destination is unavailable. The private export is kept.");
                    row=reserve(app,item);
                    if (!journal.edit().putLong(key+".row",row.id).putString(key+".target",name).commit())
                        throw new IOException("Could not record the reserved Downloads destination.");
                }
                String digest;
                if (row.pending) {
                    if (!marker(item).equals(row.name)) throw new IOException("The pending MP4 belongs to a different export.");
                    Uri target=uri(row.id);
                    try {
                        digest=copy(app.getContentResolver(),source,target,expected);
                        verifyPayload(app,row,expected,digest);
                    }
                    catch (IOException|RuntimeException error) {
                        if (!journal.getBoolean(key+".publishing",false)) discardUnusedReservation(app,item,row.id);
                        throw error;
                    }
                    ContentValues values=new ContentValues();
                    values.put(MediaStore.MediaColumns.DISPLAY_NAME,name);
                    values.put(MediaStore.MediaColumns.IS_PENDING,0);
                    // If the provider committed and lost the response, the
                    // persisted row is reused and read back on the next retry.
                    if (!journal.edit().putBoolean(key+".publishing",true).commit())
                        throw new IOException("Could not record the Downloads publication attempt.");
                    app.getContentResolver().update(target,values,null,null);
                    row=read(app,row.id);
                } else {
                    digest=privateHash(source,expected);
                    verifyPayload(app,row,expected,digest);
                }
                if (row==null||!finalName(name,row.name))
                    throw new IOException("The published MP4 filename could not be verified.");
                verifyPublishedSize(app,row,expected);
                receipt=new DownloadReceipt(row.id,expected,row.name,digest);
            }
            if (!journal.edit().putLong(key+".row",receipt.row).putLong(key+".size",receipt.size)
                    .putString(key+".name",receipt.name).putString(key+".sha256",receipt.digest)
                    .remove(key+".publishing").remove(key+".target").commit())
                throw new IOException("Could not record the verified Downloads MP4.");
            if (source.exists()&&!source.delete()) throw new IOException("Could not remove the private MP4 after saving to Downloads.");
        }
    }

    private static void registerQueued(Activity activity,ExportOptions options) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        final long fov=FovMod.captureExportFov();
        if (!FovMod.validExportFov(fov)) { showError(activity,"Could not read the current FOV. Return to the MV and try again."); return; }
        final long ticket=++generation;
        querying=true;
        Runnable cancel=new Runnable() { public void run() {
            if (ticket!=generation) return;
            generation++; querying=false;
            if (pendingQuery!=null) pendingQuery.cancel();
            removePanel();
        } };
        overlay(activity,"Reading the selected MV, formation and graphics…",cancel);
        request(new SongCallback() {
            public void onSong(String selection) {
                if (ticket!=generation||!querying||!retainsSession(activity)) return;
                querying=false; removePanel();
                try {
                    ExportQueue entries=exportQueue(activity);
                    List<QueueItem> updated=new ArrayList<>(entries.items);
                    updated.add(new QueueItem(UUID.randomUUID(),selection,options,fov,QueueState.WAITING,"",false));
                    entries.save(updated);
                    toast(activity,"Added to the export queue.");
                } catch (Exception error) { showError(activity,message(error)); }
            }

            public void onFailed(String reason) {
                if (ticket!=generation||!querying) return;
                querying=false; removePanel();
                if (retainsSession(activity)) showError(activity,reason);
            }
        },new Request() { public int submit(Object request) { return nativeQueueSelection(request); } },QUERY_TIMEOUT_MS,
                "Load an MV before adding it to the queue.","The game did not return a complete MV selection.");
    }

    private static void closeSetup() {
        FovMod.dismissGamePanel(setupPanel); setupPanel=null;
        queuePanel=null;
    }

    private static void showQueue(Activity activity) {
        if (!foreground(activity)||current!=null||combinedRun!=null||plan!=null||querying) return;
        if (saving||pendingSave!=null) { queueWhenResumed=true; return; }
        final ExportQueue entries;
        try { entries=exportQueue(activity); }
        catch (Exception error) { showError(activity,"Could not read the export queue. "+message(error)); return; }
        if (queuePanel!=null&&setupPanel==queuePanel) closeSetup();
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        List<File> outputs=new ArrayList<>();
        boolean waiting=false;
        int sourceCount=0;
        for (QueueItem item:entries.items) {
            waiting|=!item.isCombined()&&item.state==QueueState.WAITING;
            if (canCombine(item)) sourceCount++;
            if (item.hasOutput(activity)&&!downloadsInProgress.contains(item.id)) outputs.add(item.output(activity));
        }
        if (entries.items.isEmpty()) label(form,"Open an MV, choose Export MP4, then add it to the queue.");
        if (waiting) action(form,"Export queued MVs",new Runnable() { public void run() { startQueue(activity); } });
        if (sourceCount>=2) action(form,"Combine into MP4s…",new Runnable() { public void run() { showCombineSetup(activity,entries); } });
        if (!outputs.isEmpty()) action(form,"Save all available MP4s…",new Runnable() { public void run() { offerQueueFolder(activity,outputs); } });
        for (int index=0;index<entries.items.size();index++) addQueueRow(activity,form,entries,index);
        Runnable close=new Runnable() { public void run() { closeSetup(); } };
        action(form,"Close",close);
        setupPanel=FovMod.showGamePanel(activity,"Export queue",form,close);
        queuePanel=setupPanel;
    }

    private static boolean canCombine(QueueItem item) { return !item.isCombined()&&item.state!=QueueState.ACTIVE; }

    /** Group builder: each group becomes one MP4. A group of two or more clips is
     * a combined MP4; a group of one clip exports that MV alone. */
    private static void showCombineSetup(Activity activity,ExportQueue entries) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        closeSetup();
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        label(form,"Each MP4 plays its clips in the order shown. An MP4 with one clip exports that MV alone; an empty MP4 is skipped.");
        final List<List<QueueItem>> groups=new ArrayList<>();
        groups.add(new ArrayList<QueueItem>());
        final int[] active={0};
        Button export=action(form,"Export 1 MP4",new Runnable() { public void run() { startGroupPlan(activity,entries,groups); } });
        Runnable back=new Runnable() { public void run() { closeSetup(); showQueue(activity); } };
        action(form,"Back to queue",back);
        LinearLayout ordered=new LinearLayout(activity); ordered.setOrientation(LinearLayout.VERTICAL); form.addView(ordered);
        Button newGroup=new Button(activity); newGroup.setText("New MP4"); form.addView(newGroup);
        LinearLayout available=new LinearLayout(activity); available.setOrientation(LinearLayout.VERTICAL); form.addView(available);
        Runnable refresh=new Runnable() { public void run() {
            int count=nonEmptyGroups(groups);
            export.setText(count==1?"Export 1 MP4":"Export "+count+" MP4s");
            export.setEnabled(count>=1);
            ordered.removeAllViews(); available.removeAllViews();
            for (int number=0;number<groups.size();number++) {
                final int groupIndex=number;
                final List<QueueItem> selected=groups.get(number);
                int pad=dp(activity,12);
                LinearLayout box=new LinearLayout(activity); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(0,pad,0,0); ordered.addView(box);
                boolean chosen=number==active[0];
                action(box,(chosen?"▶ ":"")+"MP4 #"+(number+1)+" · "+clipCount(selected.size())+(chosen?" · adding here":" · tap to add here"),new Runnable() { public void run() {
                    active[0]=groupIndex; refreshCombineOrder();
                } });
                label(box,groupNote(activity,selected));
                for (int index=0;index<selected.size();index++) {
                    final int position=index;
                    QueueItem item=selected.get(index);
                    label(box,(index+1)+". "+item.title);
                    label(box,item.selectionDescription);
                    LinearLayout controls=new LinearLayout(activity); box.addView(controls);
                    if (index>0) action(controls,"Up",new Runnable() { public void run() {
                        Collections.swap(selected,position,position-1); refreshCombineOrder();
                    } });
                    if (index+1<selected.size()) action(controls,"Down",new Runnable() { public void run() {
                        Collections.swap(selected,position,position+1); refreshCombineOrder();
                    } });
                    action(controls,"Remove",new Runnable() { public void run() { selected.remove(position); refreshCombineOrder(); } });
                }
            }
            final List<QueueItem> target=groups.get(active[0]);
            boolean full=target.size()>=AndroidMVEncoder.MAX_SEGMENTS;
            if (full) label(available,"An MP4 can contain up to "+AndroidMVEncoder.MAX_SEGMENTS+" clips. Choose New MP4 for more.");
            for (QueueItem item:entries.items) if (canCombine(item)&&!grouped(groups,item)) {
                label(available,item.title);
                label(available,item.description);
                action(available,"Add to MP4 #"+(active[0]+1),new Runnable() { public void run() {
                    target.add(item); refreshCombineOrder();
                } }).setEnabled(!full);
            }
        }
            private void refreshCombineOrder() { run(); }
        };
        newGroup.setOnClickListener(new View.OnClickListener() { public void onClick(View view) {
            groups.add(new ArrayList<QueueItem>()); active[0]=groups.size()-1; refresh.run();
        } });
        refresh.run();
        setupPanel=FovMod.showGamePanel(activity,"Combine into MP4s",form,back);
    }

    private static int nonEmptyGroups(List<List<QueueItem>> groups) {
        int count=0;
        for (List<QueueItem> group:groups) if (!group.isEmpty()) count++;
        return count;
    }

    private static boolean grouped(List<List<QueueItem>> groups,QueueItem item) {
        for (List<QueueItem> group:groups) if (group.contains(item)) return true;
        return false;
    }

    private static String clipCount(int count) { return count==1?"1 clip":count+" clips"; }

    /** The first clip of each MP4 decides its video settings; every MV keeps its saved FOV. */
    private static String groupNote(Context context,List<QueueItem> group) {
        if (group.isEmpty()) return "Video settings come from the first clip. Each MV keeps its saved FOV. Empty MP4s are skipped.";
        QueueItem first=group.get(0);
        if (group.size()==1) {
            String note="Uses "+first.options.description()+" from its only clip. The MV keeps its saved FOV.";
            return alreadyExported(context,first)?note+" It is already exported, so it will be skipped.":note;
        }
        return "All clips use "+first.options.description()+" from the first clip. Each MV keeps its saved FOV.";
    }

    /** A completed single export whose MP4 is still kept privately or in Downloads. */
    private static boolean alreadyExported(Context context,QueueItem item) {
        return item.state==QueueState.COMPLETED&&(item.hasOutput(context)||downloadReceipt(context.getApplicationContext(),item)!=null);
    }

    private static void addQueueRow(Activity activity,LinearLayout parent,ExportQueue entries,int index) {
        QueueItem item=entries.items.get(index);
        LinearLayout row=new LinearLayout(activity); row.setOrientation(LinearLayout.VERTICAL);
        int pad=dp(activity,12); row.setPadding(0,pad,0,pad); parent.addView(row);
        label(row,item.title);
        label(row,item.description);
        label(row,queueStatus(item));
        DownloadReceipt receipt=downloadReceipt(activity,item);
        if (receipt!=null) {
            label(row,DOWNLOAD_FOLDER+receipt.name);
            action(row,"Open MP4",new Runnable() { public void run() { openDownload(activity,receipt); } });
        }
        if (downloadsInProgress.contains(item.id)) {
            label(row,"Moving MP4 to Downloads…");
            return;
        }
        if (item.hasOutput(activity)) {
            if (item.isCombined()&&item.state==QueueState.ACTIVE) {
                action(row,"Retry saving result",new Runnable() { public void run() {
                    try { recordCombinedOutput(activity,entries,item); showQueue(activity); }
                    catch (Exception error) { showError(activity,message(error)); }
                } });
            }
            if (item.state==QueueState.COMPLETED&&Build.VERSION.SDK_INT>=29) {
                String error=downloadJournal(activity).getString(item.id+".error","");
                if (!error.isEmpty()) label(row,(receipt==null?"Downloads save failed · ":"Private file cleanup failed · ")+error);
                String moveLabel=receipt!=null?"Retry private file cleanup":
                        error.isEmpty()?"Move to Downloads":"Retry move to Downloads";
                action(row,moveLabel,new Runnable() {
                    public void run() { requestDownload(activity,entries,item); }
                });
            }
            action(row,"Save MP4…",new Runnable() { public void run() { closeSetup(); offerSave(activity,item.output(activity),true); } });
            action(row,"Remove completed entry…",new Runnable() { public void run() { confirmRemove(activity,entries,item); } });
            return;
        }
        if (receipt!=null) {
            addRenderReportButton(activity,row,item.output(activity),null);
            action(row,"Remove completed entry…",new Runnable() { public void run() { confirmRemove(activity,entries,item); } });
            return;
        }
        if (item.isCombined()) {
            action(row,"Retry combined export",new Runnable() { public void run() { retryCombined(activity,entries,item); } });
            action(row,"Remove",new Runnable() { public void run() { removeQueueItem(activity,entries,item); } });
            return;
        }
        if (item.state==QueueState.FAILED||item.state==QueueState.CANCELLED) action(row,"Return to queue",new Runnable() { public void run() {
            try { entries.change(item,QueueState.WAITING,""); showQueue(activity); }
            catch (Exception error) { showError(activity,message(error)); }
        } });
        if (item.state==QueueState.WAITING) {
            if (index>0) action(row,"Move up",new Runnable() { public void run() { moveQueueItem(activity,entries,index,index-1); } });
            if (index+1<entries.items.size()) action(row,"Move down",new Runnable() { public void run() { moveQueueItem(activity,entries,index,index+1); } });
        }
        action(row,"Remove",new Runnable() { public void run() { removeQueueItem(activity,entries,item); } });
    }

    private static String queueStatus(QueueItem item) {
        switch (item.state) {
            case WAITING: return "Waiting";
            case ACTIVE: return "Preparing";
            case COMPLETED: return "Completed";
            case CANCELLED: return "Cancelled";
            default: return item.detail.isEmpty()?"Failed":"Failed · "+item.detail;
        }
    }

    private static void moveQueueItem(Activity activity,ExportQueue entries,int from,int to) {
        try {
            List<QueueItem> updated=new ArrayList<>(entries.items);
            Collections.swap(updated,from,to); entries.save(updated); showQueue(activity);
        } catch (Exception error) { showError(activity,message(error)); }
    }

    private static void confirmRemove(Activity activity,ExportQueue entries,QueueItem item) {
        closeSetup();
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        boolean privateFile=item.hasOutput(activity);
        label(form,privateFile?"Remove this entry and delete its private MP4? Files already saved elsewhere will stay there.":
                "Remove this entry? The MP4 in Downloads will stay there.");
        Runnable back=new Runnable() { public void run() { closeSetup(); showQueue(activity); } };
        action(form,"Cancel",back);
        action(form,privateFile?"Delete private MP4 and remove":"Remove entry",new Runnable() { public void run() { removeQueueItem(activity,entries,item); } });
        setupPanel=FovMod.showGamePanel(activity,item.title,form,back);
    }

    private static void removeQueueItem(Activity activity,ExportQueue entries,QueueItem item) {
        if (downloadsInProgress.contains(item.id)) return;
        try {
            File output=item.output(activity);
            if (output.exists()&&!output.delete()) throw new IOException("Could not delete the private MP4.");
            new File(output.getPath()+".render-report.txt").delete();
            List<QueueItem> updated=new ArrayList<>(entries.items);
            updated.remove(item); entries.save(updated); showQueue(activity);
        } catch (Exception error) { showError(activity,message(error)); }
    }

    private static void startQueue(Activity activity) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        if (restartRequired!=null) { showError(activity,restartRequired); return; }
        queueNumber=0; queueCount=0;
        for (QueueItem item:queue.items) if (!item.isCombined()&&item.state==QueueState.WAITING) queueCount++;
        closeSetup(); queueRunning=true;
        startBackgroundExport(activity);
        openNext(activity);
    }

    private static File combinedScratch(Context app) { return new File(app.getFilesDir(),"MVExports/CombinedScratch"); }

    private static void cleanCombinedScratch(File folder) {
        File[] files=folder.listFiles();
        if (files!=null) for (File file:files) file.delete();
        folder.delete();
    }

    private static final class CombinedRun {
        final Context app;
        final QueueItem result;
        final List<QueueItem> selected;
        final List<AndroidMVEncoder.Segment> segments=new ArrayList<>();
        final File folder,stagedOutput;
        AndroidMVEncoder.Config audioConfig;
        boolean assembling;

        CombinedRun(Activity activity,QueueItem result,List<QueueItem> selected) throws IOException {
            app=activity.getApplicationContext(); this.result=result; this.selected=new ArrayList<>(selected);
            File destination=result.output(app).getParentFile();
            if (!destination.isDirectory()&&!destination.mkdirs()) throw new IOException("Cannot create the MP4 output folder");
            folder=new File(combinedScratch(app),"group-"+UUID.randomUUID());
            if (!folder.mkdirs()) throw new IOException("Cannot create private files for the combined MP4.");
            stagedOutput=new File(folder,"combined.mp4").getCanonicalFile();
        }
    }

    private static void retryCombined(Activity activity,ExportQueue entries,QueueItem group) {
        List<QueueItem> selected=new ArrayList<>();
        for (UUID source:group.sources) {
            QueueItem match=null;
            for (QueueItem item:entries.items) if (item.id.equals(source)&&canCombine(item)) { match=item; break; }
            if (match==null) {
                showError(activity,"A saved MV in this group is missing. Create a new group from the export queue.");
                return;
            }
            selected.add(match);
        }
        startCombined(activity,entries,group,selected);
    }

    private static void startCombined(Activity activity,ExportQueue entries,QueueItem previous,List<QueueItem> selected) {
        if (!foreground(activity)||isBusy()||pendingSave!=null||selected.size()<2) return;
        if (restartRequired!=null) { showError(activity,restartRequired); return; }
        CombinedRun run;
        try { run=prepareCombined(activity,entries,previous,selected); }
        catch (Exception error) {
            showError(activity,message(error));
            return;
        }
        combinedRun=run; queueRunning=true; queueCount=run.selected.size(); queueNumber=0;
        startBackgroundExport(activity);
        closeSetup(); openNextCombined(activity,run);
    }

    /** Same validation and ACTIVE combined queue entry for a new export or a retry. */
    private static CombinedRun prepareCombined(Activity activity,ExportQueue entries,QueueItem previous,List<QueueItem> selected)
            throws IOException,JSONException {
        CombinedRun run=null;
        try {
            List<UUID> order=new ArrayList<>();
            for (QueueItem source:selected) {
                if (!entries.items.contains(source)||!canCombine(source)) throw new IOException("A selected MV changed. Open the export queue again.");
                order.add(source.id);
            }
            QueueItem first=selected.get(0);
            QueueItem result=previous==null?new QueueItem(UUID.randomUUID(),first.selection,first.options,first.fov,
                    QueueState.ACTIVE,"",Build.VERSION.SDK_INT>=29,order):previous.changed(QueueState.ACTIVE,"");
            run=new CombinedRun(activity,result,selected);
            if (previous==null) {
                List<QueueItem> updated=new ArrayList<>(entries.items);
                updated.add(result); entries.save(updated);
            } else entries.change(previous,QueueState.ACTIVE,"");
            return run;
        } catch (IOException|JSONException|RuntimeException error) {
            if (run!=null) cleanCombinedScratch(run.folder);
            throw error;
        }
    }

    /** True while an unfinished group plan still has groups after the running one. */
    private static boolean planContinues() {
        return plan!=null&&plan.stopReason==null&&plan.next<plan.groups.size();
    }

    /** Bookkeeping for one "Combine into MP4s" run; Android-free so host tests can load it. */
    static final class GroupPlan {
        final Context app;
        final List<List<UUID>> groups;
        int next, exported, skipped, failed, cancelled;
        UUID single; // The one-clip group being exported through the queue path.
        String stopReason, firstFailure;

        GroupPlan(Context app,List<List<UUID>> groups) { this.app=app; this.groups=groups; }

        /** Java and native failures that leave the game unable to export until restart
         * (restartRequired, native quarantine, failed runtime setup) all say "restart". */
        static boolean requiresRestart(String reason) {
            return reason!=null&&reason.toLowerCase(Locale.ROOT).contains("restart");
        }

        void ended(boolean success,boolean wasCancelled,String reason) {
            if (success) exported++;
            else if (wasCancelled) cancelled++;
            else { failed++; if (firstFailure==null&&reason!=null&&!reason.isEmpty()) firstFailure=reason; }
        }

        void stop(String reason) { if (stopReason==null) stopReason=reason==null||reason.isEmpty()?"Export cancelled.":reason; }

        String summary() {
            StringBuilder text=new StringBuilder(String.format(Locale.US,"MP4s: %d exported · %d skipped · %d failed",exported,skipped,failed));
            int notExported=cancelled+groups.size()-next;
            if (notExported>0) text.append(String.format(Locale.US," · %d not exported",notExported));
            text.append('.');
            if (skipped>0) text.append(skipped==1?" The skipped MV was already exported.":" The skipped MVs were already exported.");
            if (stopReason!=null) text.append('\n').append(stopReason);
            else if (firstFailure!=null) text.append('\n').append(firstFailure);
            return text.toString();
        }
    }

    private static QueueItem queuedItem(UUID id) {
        for (QueueItem item:queue.items) if (item.id.equals(id)) return item;
        return null;
    }

    /** Runs every non-empty group in order. One group of two or more clips is the
     * unchanged single combined export. */
    private static void startGroupPlan(Activity activity,ExportQueue entries,List<List<QueueItem>> groups) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        if (restartRequired!=null) { showError(activity,restartRequired); return; }
        List<List<QueueItem>> chosen=new ArrayList<>();
        List<List<UUID>> order=new ArrayList<>();
        Set<UUID> seen=new HashSet<>();
        for (List<QueueItem> group:groups) {
            if (group.isEmpty()) continue;
            if (group.size()>AndroidMVEncoder.MAX_SEGMENTS) {
                showError(activity,"An MP4 can contain up to "+AndroidMVEncoder.MAX_SEGMENTS+" clips.");
                return;
            }
            List<UUID> ids=new ArrayList<>();
            for (QueueItem item:group) {
                if (!entries.items.contains(item)||!canCombine(item)||!seen.add(item.id)) {
                    showError(activity,"A selected MV changed. Open the export queue again.");
                    return;
                }
                ids.add(item.id);
            }
            chosen.add(new ArrayList<>(group));
            order.add(ids);
        }
        if (chosen.isEmpty()) return;
        if (chosen.size()==1&&chosen.get(0).size()>=2) { startCombined(activity,entries,null,chosen.get(0)); return; }
        closeSetup();
        plan=new GroupPlan(activity.getApplicationContext(),order);
        advancePlan(activity);
    }

    /** Starts the next runnable group, or ends the plan. Called with nothing running. */
    private static void advancePlan(Activity activity) {
        GroupPlan run=plan;
        if (run==null||current!=null||combinedRun!=null) return;
        while (run.stopReason==null&&run.next<run.groups.size()) {
            if (restartRequired!=null) { run.stop(restartRequired); break; }
            List<QueueItem> items=new ArrayList<>();
            for (UUID id:run.groups.get(run.next)) {
                QueueItem item=queuedItem(id);
                if (item==null||!canCombine(item)) { items=null; break; }
                items.add(item);
            }
            if (items==null) { run.next++; run.ended(false,false,"A selected MV changed or was removed from the queue."); continue; }
            // Never re-render or overwrite a completed single MP4 that still exists.
            if (items.size()==1&&alreadyExported(run.app,items.get(0))) { run.next++; run.skipped++; continue; }
            if (!canDriveExport(activity)) {
                if (retainsSession(activity)) return; // Configuration change: onGameStarted continues.
                run.stop("The game was hidden or closed before the remaining MP4s could start.");
                break;
            }
            run.next++;
            if (items.size()==1) {
                if (foreground(activity)) startBackgroundExport(activity);
                run.single=items.get(0).id; queueRunning=true; queueNumber=0; queueCount=1;
                openNext(activity);
                return;
            }
            CombinedRun combined;
            try { combined=prepareCombined(activity,queue,null,items); }
            catch (Exception error) { run.ended(false,false,message(error)); continue; }
            combinedRun=combined; queueRunning=true; queueCount=combined.selected.size(); queueNumber=0;
            if (foreground(activity)) startBackgroundExport(activity);
            openNextCombined(activity,combined);
            return;
        }
        finishPlan();
    }

    /** Ends the plan: release the background export and show the queue with a summary. */
    private static void finishPlan() {
        GroupPlan finished=plan;
        if (finished==null) return;
        plan=null; queueRunning=false;
        stopBackgroundExport(); removePanel();
        String summary=finished.summary();
        Activity activity=game.get();
        if (foreground(activity)) { showQueue(activity); toast(activity,summary); }
        else { queueWhenResumed=true; pendingNotice=summary; }
    }

    private static void openNextCombined(Activity activity,CombinedRun run) {
        if (current!=null||!queueRunning||!canDriveExport(activity)||run.assembling) return;
        int index=run.segments.size();
        try {
            QueueItem item=run.selected.get(index);
            current=new Session(activity,run.result.options,item,run);
            queueNumber=index+1;
            current.phase="Opening the registered MV…";
            showProgress(activity,current);
            current.fov=FovMod.applyExportFov(activity,item.fov);
            openQueuedScene(activity,current);
        } catch (Exception error) {
            if (current!=null) failed(current,message(error));
            else finishCombined(run,null,QueueState.FAILED,message(error));
        }
    }

    private static void openNext(Activity activity) {
        if (combinedRun!=null) { openNextCombined(activity,combinedRun); return; }
        final GroupPlan group=plan;
        if (!queueRunning||!canDriveExport(activity)) {
            queueRunning=false;
            if (group!=null) { group.single=null; group.stop("The game was hidden or closed before the remaining MP4s could start."); finishPlan(); return; }
            stopBackgroundExport(); return;
        }
        QueueItem next=null;
        if (group!=null) {
            // A one-clip group exports exactly its own item, whatever its previous state.
            QueueItem item=group.single==null?null:queuedItem(group.single);
            if (item!=null&&canCombine(item)) next=item;
            if (next==null) {
                queueRunning=false; group.single=null;
                group.ended(false,false,"A selected MV changed or was removed from the queue.");
                advancePlan(activity);
                return;
            }
        } else for (QueueItem item:queue.items) if (!item.isCombined()&&item.state==QueueState.WAITING) { next=item; break; }
        if (next==null) {
            queueRunning=false; stopBackgroundExport();
            if (foreground(activity)) showQueue(activity); else queueWhenResumed=true;
            return;
        }
        try {
            Session session=new Session(activity,next.options,next);
            queue.change(next,QueueState.ACTIVE,"");
            current=session;
            queueNumber++;
            session.phase="Opening the registered MV…";
            showProgress(activity,session);
            session.fov=FovMod.applyExportFov(activity,session.item.fov);
            openQueuedScene(activity,session);
        } catch (Exception error) {
            if (current!=null) failed(current,message(error));
            else if (group!=null&&plan==group) {
                queueRunning=false; group.single=null;
                group.ended(false,false,message(error));
                advancePlan(activity);
            }
            else {
                queueRunning=false; stopBackgroundExport();
                if (foreground(activity)) showError(activity,message(error));
                else { queueWhenResumed=true; pendingNotice=message(error); }
            }
        }
    }

    private static void openQueuedScene(Activity activity,Session session) {
        request(new SongCallback() {
            public void onSong(String selection) {
                if (current!=session) return;
                if (!retainsSession(activity)||session.cancelled) { failed(session,"Export cancelled"); return; }
                if (!session.item.selection.equals(selection)) { failed(session,"The loaded MV does not match the saved selection."); return; }
                if (FovMod.captureExportFov()!=session.item.fov) { failed(session,"The saved FOV changed while loading the MV."); return; }
                session.phase="Preparing the song audio…";
                updateProgress(session);
                queryForSession(session);
            }

            public void onFailed(String reason) { failed(session,reason); }
        },new Request() { public int submit(Object request) { return nativeQueueOpen(session.item.selection,request); } },OPEN_TIMEOUT_MS,
                "The game cannot open the queued MV from its current screen.","Timed out waiting for the registered MV to load.");
    }

    private static final class Session {
        final Context app; final int width,height,fps,bitrate; final String mime; final File output;
        final WeakReference<Activity> window;
        final QueueItem item;
        final CombinedRun combined;
        final File pcm;
        volatile AndroidMVEncoder.Config codecConfig;
        FovMod.ExportFovOverride fov;
        volatile boolean cancelled,nativeBeginRequested; volatile AndroidMVEncoder encoder;
        boolean ending;
        String interruption;
        long done,total; String phase="Preparing the song audio…";
        Session(Activity activity,ExportOptions options,QueueItem item) throws IOException {
            this(activity,options,item,null);
        }
        Session(Activity activity,ExportOptions options,QueueItem item,CombinedRun combined) throws IOException {
            app=activity.getApplicationContext(); window=new WeakReference<Activity>(activity); this.item=item; this.combined=combined;
            width=options.width; height=options.height; fps=options.fps; mime=options.mime; bitrate=options.bitrate;
            if (combined!=null) {
                String name="clip-"+combined.segments.size();
                output=new File(combined.folder,name+".mp4").getCanonicalFile();
                pcm=new File(combined.folder,name+".pcm").getCanonicalFile();
            } else {
                output=(item==null?new File(new File(app.getFilesDir(),"MVExports"),"MV-"+UUID.randomUUID()+".mp4"):item.output(app)).getCanonicalFile();
                pcm=null;
            }
            File folder=output.getParentFile();
            if (!folder.isDirectory()&&!folder.mkdirs()) throw new IOException("Cannot create the MP4 output folder");
            if (item!=null && output.exists() && (output.length()!=0 || !output.delete())) throw new IOException("The queued MP4 destination is already in use.");
        }
    }
    private static void start(final Activity activity,ExportOptions options) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        if (restartRequired!=null) { showError(activity,restartRequired); return; }
        final Session session;
        try { session=new Session(activity,options,null); }
        catch (Throwable error) { showError(activity,message(error)); return; }
        current=session; startBackgroundExport(activity); showProgress(activity,session);
        // Refresh the selection after configuration without changing windows.
        queryForSession(session);
    }

    private static void queryForSession(Session session) {
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
        AndroidMVEncoder.checkVideoEncoder(session.mime,session.width,session.height,session.fps,session.bitrate);
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
            AndroidMVEncoder.Config config=new AndroidMVEncoder.Config(session.mime,session.width,session.height,session.fps,
                    session.bitrate,videoFrames,sampleRate,channels,192000,audioFrames);
            if (session.combined!=null&&session.combined.audioConfig!=null) {
                AndroidMVEncoder.Config first=session.combined.audioConfig;
                if (sampleRate!=first.sampleRate||channels!=first.channels)
                    throw new IOException("The selected MVs use different audio sample rates or channel counts.");
            }
            if (session.combined!=null) session.codecConfig=config;
            encoder=session.combined==null?new AndroidMVEncoder(config,session.output):new AndroidMVEncoder(config,session.output,session.pcm);
            session.encoder=encoder;
            session.nativeBeginRequested=true;
            if (session.cancelled) throw new IOException("Export cancelled");
            if (nativeBegin(prepared,encoder,session.width,session.height,session.fps,new ExportCallback(session))!=1)
                throw new IOException("The loaded MV changed or the exporter is busy. Load the MV and try again.");
            consumed=true; prepared=0;
            if (session.cancelled) { nativeCancel(); encoder.cancel(); }
            MAIN.post(new Runnable() { public void run() { if (current==session&&!session.cancelled) { session.phase="Rendering the full MV…"; updateProgress(session); } } });
        } catch (Throwable error) { failure=error; }
        finally {
            if (!consumed) {
                session.nativeBeginRequested=false;
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
            if (serviceReady&&total>0&&total<=Integer.MAX_VALUE) MVExportService.progress(serviceToken,(int)done,(int)total);
        } }); }
        public void onFinished(final String path) { MAIN.post(new Runnable() { public void run() {
            if (current!=session) return;
            try {
                File actual=new File(path).getCanonicalFile();
                if (!actual.equals(session.output)||!actual.isFile()||actual.length()==0) throw new IOException("The completed MP4 path is invalid.");
                if (session.item!=null) { finishQueued(session,true,null); return; }
                completed=actual; current=null; stopBackgroundExport(); removePanel(); Activity activity=game.get();
                if (foreground(activity)) offerSave(activity,actual); else completedWaiting=true;
            } catch (Throwable error) { failed(session,message(error)); }
        } }); }
        public void onFailed(final String reason) { MAIN.post(new Runnable() { public void run() { failed(session,reason); } }); }
    }
    private static void cancel(Session session) { cancel(session,null); }

    private static void cancel(Session session,String interruption) {
        if (current!=session||session.cancelled) return;
        if (session.item!=null) queueRunning=false;
        session.interruption=interruption;
        session.cancelled=true; session.phase="Cancelling…"; updateProgress(session);
        if (session.combined==null||!session.combined.assembling) {
            try { nativeCancel(); } catch (Throwable ignored) {}
        }
        AndroidMVEncoder encoder=session.encoder; if (encoder!=null) encoder.cancel();
        if (pendingQuery!=null) pendingQuery.complete(null,interruption==null?"Export cancelled":interruption);
    }
    private static void showProgress(Activity activity,final Session session) {
        if (!visible(activity)) return;
        overlay(activity,session.phase,new Runnable() { public void run() { cancel(session); } }); updateProgress(session);
    }
    private static void refreshProgress(Activity activity) {
        if (current==null) return;
        if (panel==null||panel.getParent()==null||panel.getContext()!=activity) showProgress(activity,current);
        else updateProgress(current);
    }
    private static void updateProgress(Session session) {
        if (current!=session||status==null||progress==null) return;
        String phase=session.cancelled?"Cancelling…":session.ending?session.phase:session.total>0?
                String.format(Locale.US,"Rendering: %d / %d frames",session.done,session.total):session.phase;
        if (session.item!=null) phase=String.format(Locale.US,"%d / %d · %s\n%s",queueNumber,queueCount,
                session.combined!=null&&session.combined.assembling?session.combined.result.title:session.item.title,phase);
        if (plan!=null&&session.item!=null) phase=String.format(Locale.US,"MP4 %d / %d\n%s",plan.next,plan.groups.size(),phase);
        status.setText(phase);
        progress.setIndeterminate(session.total<=0);
        if (session.total>0) { progress.setMax(1000); progress.setProgress((int)Math.min(1000,session.done*1000/session.total)); }
    }
    private static void failed(Session session,String reason) {
        if (current!=session) return;
        final String failureReason=session.interruption==null?reason:session.interruption;
        if (session.combined!=null&&session.combined.assembling) { cancel(session); return; }
        if (session.item!=null) {
            if (session.ending) return;
            session.ending=true; queueRunning=false;
            try { nativeCancel(); } catch (Throwable ignored) {}
            AndroidMVEncoder encoder=session.encoder;
            if (encoder==null||encoder.isDone()) { finishQueued(session,false,failureReason); return; }
            session.phase="Finishing cleanup…"; updateProgress(session);
            encoder.cancel();
            WORK.execute(new Runnable() { public void run() {
                String failure=failureReason;
                String restart=null;
                try { encoder.awaitCompletion(60,TimeUnit.SECONDS); }
                catch (java.util.concurrent.ExecutionException expected) { /* Encoder cleanup completed. */ }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); restart="MP4 cleanup was interrupted. Restart the game before retrying."; }
                catch (java.util.concurrent.TimeoutException error) { restart="MP4 cleanup timed out. Restart the game before retrying."; }
                if (restart!=null) failure=restart;
                final String result=failure,restartMessage=restart;
                MAIN.post(new Runnable() { public void run() {
                    if (restartMessage!=null) restartRequired=restartMessage;
                    finishQueued(session,false,result);
                } });
            } });
            return;
        }
        current=null; stopBackgroundExport(); removePanel(); Activity activity=game.get();
        boolean userCancelled=session.cancelled&&session.interruption==null;
        if (foreground(activity)) { if (userCancelled) toast(activity,"Export cancelled."); else showError(activity,failureReason); }
        else { pendingNotice=userCancelled?"Export cancelled.":failureReason; pendingNoticeError=!userCancelled; }
    }

    private static void finishQueued(Session session,boolean success,String reason) {
        if (current!=session) return;
        boolean restored=session.fov==null||session.fov.restore();
        if (!restored) restartRequired="The previous FOV could not be restored. Restart the game before exporting again.";
        if (restartRequired!=null) reason=restartRequired;
        else if (session.interruption!=null) reason=session.interruption;
        QueueState next=restored&&success?QueueState.COMPLETED:
                restartRequired==null&&session.cancelled&&session.interruption==null?QueueState.CANCELLED:QueueState.FAILED;
        if (session.combined!=null) { finishCombinedClip(session,next,reason); return; }
        boolean recorded=false;
        try {
            QueueItem updated=queue.change(session.item,next,reason);
            recorded=true;
            if (next==QueueState.COMPLETED&&updated.autoDownload) moveToDownloads(session.app,updated);
        }
        catch (Exception error) { reason=message(error); }
        current=null; removePanel(); Activity activity=game.get();
        GroupPlan group=plan;
        if (group!=null&&session.item.id.equals(group.single)) {
            // A one-clip group ended. Failures move on to the next group unless
            // they already stop the queue: cancel, interruption, restart, or an
            // unrecorded result.
            group.single=null; queueRunning=false;
            group.ended(recorded&&next==QueueState.COMPLETED,next==QueueState.CANCELLED,reason);
            if (!recorded||restartRequired!=null||session.cancelled||GroupPlan.requiresRestart(reason))
                group.stop(restartRequired!=null?restartRequired:session.cancelled&&session.interruption==null?"Export cancelled.":reason);
            advancePlan(activity);
            return;
        }
        boolean continueQueue=recorded&&next==QueueState.COMPLETED&&queueRunning&&!session.cancelled&&retainsSession(activity);
        if (continueQueue) {
            if (canDriveExport(activity)) openNext(activity);
            return;
        }
        queueRunning=false; stopBackgroundExport();
        if (restartRequired!=null) reason=restartRequired;
        if (!foreground(activity)) { queueWhenResumed=true; if (!recorded||restartRequired!=null) pendingNotice=reason; return; }
        showQueue(activity);
        if (!recorded||restartRequired!=null) toast(activity,reason);
    }

    private static void finishCombinedClip(Session session,QueueState state,String reason) {
        CombinedRun run=session.combined;
        if (state!=QueueState.COMPLETED||session.cancelled) {
            if (state==QueueState.COMPLETED) state=session.interruption==null?QueueState.CANCELLED:QueueState.FAILED;
            finishCombined(run,null,state,reason);
            return;
        }
        try {
            AndroidMVEncoder.Config config=session.codecConfig;
            if (config==null||!session.pcm.isFile()||session.pcm.length()!=config.audioFrames*config.channels*2)
                throw new IOException("A rendered MV is missing its complete audio.");
            run.segments.add(new AndroidMVEncoder.Segment(session.output,session.pcm,config));
            if (run.audioConfig==null) run.audioConfig=config;
        } catch (Exception error) {
            finishCombined(run,null,QueueState.FAILED,message(error));
            return;
        }
        if (run.segments.size()<run.selected.size()) {
            current=null; removePanel();
            openNextCombined(game.get(),run);
            return;
        }
        run.assembling=true;
        session.fov=null; session.encoder=null; session.nativeBeginRequested=false;
        // A plan with more groups keeps any background display so the next group
        // can render while the game stays hidden; the plan's end restores it.
        if (!planContinues()&&!restoreBackgroundDisplay(!gameStarted)) restartRequired="The Unity display could not be restored. Restart the game before exporting again.";
        session.total=0; session.phase="Combining the rendered MVs into one MP4…"; updateProgress(session);
        WORK.execute(new Runnable() { public void run() {
            File output=null;
            String failure=null;
            try {
                if (session.cancelled) throw new IOException("Export cancelled.");
                AndroidMVEncoder encoder=AndroidMVEncoder.combine(new ArrayList<>(run.segments),run.stagedOutput);
                session.encoder=encoder;
                if (session.cancelled) encoder.cancel();
                boolean interrupted=false;
                try {
                    for (;;) {
                        try { output=encoder.awaitCompletion(Long.MAX_VALUE,TimeUnit.NANOSECONDS); break; }
                        catch (InterruptedException error) { interrupted=true; encoder.cancel(); }
                    }
                    if (interrupted) throw new IOException("The combined export was interrupted.");
                } finally { if (interrupted) Thread.currentThread().interrupt(); }
            } catch (Throwable error) {
                Throwable cause=error instanceof java.util.concurrent.ExecutionException&&error.getCause()!=null?error.getCause():error;
                failure=message(cause);
            }
            final File assembled=output;
            final String error=failure;
            MAIN.post(new Runnable() { public void run() {
                if (current!=session||combinedRun!=run) return;
                QueueState result=session.interruption!=null?QueueState.FAILED:
                        session.cancelled?QueueState.CANCELLED:error==null?QueueState.COMPLETED:QueueState.FAILED;
                finishCombined(run,assembled,result,session.interruption==null?error:session.interruption);
            } });
        } });
    }

    private static void recordCombinedOutput(Context context,ExportQueue entries,QueueItem item) throws IOException,JSONException {
        if (!item.isCombined()||!item.hasOutput(context)) throw new IOException("The completed combined MP4 is missing.");
        QueueItem completed=entries.change(item,QueueState.COMPLETED,"");
        if (completed.autoDownload) moveToDownloads(context,completed);
    }

    private static void finishCombined(CombinedRun run,File staged,QueueState state,String reason) {
        if (combinedRun!=run) return;
        boolean interrupted=current!=null&&current.combined==run&&current.cancelled,recorded=true;
        if (state==QueueState.COMPLETED) {
            try {
                File output=run.result.output(run.app);
                if (staged==null||!run.stagedOutput.equals(staged.getCanonicalFile())||!staged.isFile()||staged.length()==0||
                        output.exists()||!staged.renameTo(output))
                    throw new IOException("Could not finalize the combined MP4.");
            } catch (Exception error) { state=QueueState.FAILED; reason=message(error); }
        }
        try {
            if (state==QueueState.COMPLETED) recordCombinedOutput(run.app,queue,run.result);
            else queue.change(run.result,state,reason);
        } catch (Exception error) { reason=message(error); state=QueueState.FAILED; recorded=false; }
        WORK.execute(new Runnable() { public void run() { cleanCombinedScratch(run.folder); } });
        GroupPlan group=plan;
        if (group!=null) {
            // A combined group ended; the background export stays for the next group.
            current=null; combinedRun=null; queueRunning=false; removePanel();
            group.ended(state==QueueState.COMPLETED,state==QueueState.CANCELLED,reason);
            if (!recorded||interrupted||state==QueueState.CANCELLED||restartRequired!=null||GroupPlan.requiresRestart(reason))
                group.stop(restartRequired!=null?restartRequired:state==QueueState.CANCELLED?"Export cancelled.":reason);
            advancePlan(game.get());
            return;
        }
        current=null; combinedRun=null; queueRunning=false; stopBackgroundExport(); removePanel();
        Activity activity=game.get();
        String notice=state==QueueState.CANCELLED?"Combined export cancelled.":state==QueueState.FAILED?reason:null;
        if (foreground(activity)) {
            showQueue(activity);
            if (notice!=null) toast(activity,notice);
        } else {
            queueWhenResumed=true;
            if (notice!=null) pendingNotice=notice;
        }
    }

    private static final class SaveRequest {
        final List<File> sources;
        final Context app;
        final int code;
        final boolean retain;

        SaveRequest(Activity activity,List<File> sources,int code,boolean retain) {
            this.sources=new ArrayList<>(sources); this.code=code; this.retain=retain;
            app=activity.getApplicationContext();
        }
    }
    private static File findCompleted(Context context) {
        if (completed!=null&&completed.isFile()&&completed.length()>0) return completed;
        File[] files=new File(context.getFilesDir(),"MVExports").listFiles(); File latest=null;
        if (files!=null) for (File file:files) if (file.getName().startsWith("MV-")&&file.getName().endsWith(".mp4")&&file.isFile()&&file.length()>0)
            if (latest==null||file.lastModified()>latest.lastModified()) latest=file;
        completed=latest; return latest;
    }
    private static void addRenderReportButton(final Activity activity,LinearLayout parent,final File source,final Runnable close) {
        if (!new File(source.getPath()+".render-report.txt").isFile()) return;
        Button report=new Button(activity); report.setText("View render report"); parent.addView(report);
        report.setOnClickListener(new View.OnClickListener() { public void onClick(View view) {
            if (close!=null) close.run();
            showRenderReport(activity,source);
        } });
    }
    private static void showRenderReport(final Activity activity,File source) {
        if (!usable(activity)) return;
        final File report=new File(source.getPath()+".render-report.txt");
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        final TextView text=new TextView(activity); text.setTextColor(0xffffffff); text.setTextIsSelectable(true); text.setText("Loading render report…"); form.addView(text);
        final View[] viewer=new View[1]; final Runnable close=new Runnable() { public void run() { FovMod.dismissGamePanel(viewer[0]); } };
        Button done=new Button(activity); done.setText("Close"); form.addView(done);
        done.setOnClickListener(new View.OnClickListener() { public void onClick(View view) { close.run(); } });
        viewer[0]=FovMod.showGamePanel(activity,"Render report",form,close);
        WORK.execute(new Runnable() { public void run() {
            String result;
            try (InputStream input=new FileInputStream(report)) {
                byte[] bytes=new byte[MAX_RENDER_REPORT_BYTES+1]; int count=0,read;
                while (count<bytes.length && (read=input.read(bytes,count,bytes.length-count))!=-1) count+=read;
                result=new String(bytes,0,Math.min(count,MAX_RENDER_REPORT_BYTES),Charset.forName("UTF-8"));
                if (count>MAX_RENDER_REPORT_BYTES) result+="\n[Report truncated at 12 KiB.]";
                if (count==0) result="The render report is empty.";
            } catch (IOException error) { result="The render report could not be read: "+message(error); }
            final String loaded=result;
            MAIN.post(new Runnable() { public void run() {
                if (usable(activity) && viewer[0].getParent()!=null) text.setText(loaded);
            } });
        } });
    }
    private static void offerSave(final Activity activity,final File source) {
        offerSave(activity,source,false);
    }

    private static void offerSave(final Activity activity,final File source,boolean retain) {
        if (!foreground(activity)||!source.isFile()||source.length()==0) return;
        completedWaiting=false;
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        label(form,retain?"Save a copy of the MP4 to a folder or document provider.":
                "Save the MP4 to a folder or document provider. The private copy stays available until saving succeeds.");
        final View[] choice=new View[1]; final Runnable close=new Runnable() { public void run() { FovMod.dismissGamePanel(choice[0]); } };
        Runnable later=new Runnable() { public void run() { close.run(); if (retain) showQueue(activity); } };
        action(form,"Later",later);
        Button save=new Button(activity); save.setText("Save MP4"); form.addView(save);
        save.setOnClickListener(new View.OnClickListener() { public void onClick(View view) {
                if (saving||pendingSave!=null) { toast(activity,"A save request is already open."); return; }
                Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("video/mp4");
                intent.putExtra(Intent.EXTRA_TITLE,source.getName()); intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
                close.run();
                launchSave(activity,intent,new SaveRequest(activity,Collections.singletonList(source),SAVE_REQUEST,retain));
        } });
        addRenderReportButton(activity,form,source,close);
        choice[0]=FovMod.showGamePanel(activity,"MP4 export complete",form,later);
    }

    private static void offerQueueFolder(Activity activity,List<File> sources) {
        if (!foreground(activity)||isBusy()||pendingSave!=null) return;
        Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);
        closeSetup();
        launchSave(activity,intent,new SaveRequest(activity,sources,SAVE_QUEUE_REQUEST,true));
    }

    private static void launchSave(Activity activity,Intent intent,SaveRequest request) {
        pendingSave=request;
        if (request.retain) queueWhenResumed=true;
        try { activity.startActivityForResult(intent,request.code); }
        catch (RuntimeException error) {
            pendingSave=null; queueWhenResumed=false;
            showError(activity,"No document picker is available. The MP4 is kept for saving later.");
        }
    }

    private static void copyMP4(SaveRequest request,File source,Uri uri) throws IOException {
        long expected=source.length(),copied=0;
        if (expected<=0||!source.isFile()) throw new IOException("The private MP4 is unavailable.");
        try (InputStream input=new FileInputStream(source); OutputStream output=request.app.getContentResolver().openOutputStream(uri,"w")) {
            if (output==null) throw new IOException("The document provider did not open the destination.");
            byte[] block=new byte[1024*1024]; int count;
            while ((count=input.read(block))!=-1) { output.write(block,0,count); copied+=count; }
            output.flush();
        }
        if (copied!=expected) throw new IOException("The MP4 copy was incomplete.");
    }

    private static void copyToFolder(SaveRequest request,File source,Uri tree) throws IOException {
        Uri folder=DocumentsContract.buildDocumentUriUsingTree(tree,DocumentsContract.getTreeDocumentId(tree));
        Uri created=DocumentsContract.createDocument(request.app.getContentResolver(),folder,"video/mp4",source.getName());
        if (created==null) throw new IOException("The selected folder cannot create MP4 documents.");
        try { copyMP4(request,source,created); }
        catch (IOException|RuntimeException error) {
            try { DocumentsContract.deleteDocument(request.app.getContentResolver(),created); }
            catch (IOException|RuntimeException ignored) { /* A provider may not support deletion. */ }
            throw error;
        }
    }

    /** Actual game Activity override forwards only our SAF result here. */
    public static boolean handleActivityResult(final Activity activity,int requestCode,int resultCode,Intent data) {
        if (requestCode!=SAVE_REQUEST&&requestCode!=SAVE_QUEUE_REQUEST) return false;
        final SaveRequest request=pendingSave;
        if (request==null||requestCode!=request.code) { toast(activity,"Open Export MP4 to save the retained export."); return true; }
        pendingSave=null;
        final Uri uri=data==null?null:data.getData();
        if (resultCode!=Activity.RESULT_OK||uri==null) {
            // The owned completed file stays discoverable through Save previous
            // MP4. Cancelling the picker must not reopen another save prompt.
            if (!request.retain) completed=request.sources.get(0);
            return true;
        }
        saving=true;
        WORK.execute(new Runnable() { public void run() {
            int copied=0;
            Throwable failure=null;
            try {
                for (File source:request.sources) {
                    if (request.code==SAVE_QUEUE_REQUEST) copyToFolder(request,source,uri);
                    else copyMP4(request,source,uri);
                    copied++;
                }
                if (!request.retain) request.sources.get(0).delete();
            } catch (Throwable error) { failure=error; }
            final String notice=failure==null?(copied==1?"MP4 saved.":String.format(Locale.US,"%d MP4s saved.",copied)):
                    (copied==0?"Saving failed. ":String.format(Locale.US,"Saved %d of %d MP4s. ",copied,request.sources.size()))+
                    "Private copies are available to retry. "+message(failure);
            final boolean error=failure!=null;
            MAIN.post(new Runnable() { public void run() {
                saving=false;
                if (!error&&!request.retain&&request.sources.get(0).equals(completed)&&!completed.exists()) completed=null;
                Activity owner=game.get();
                if (!foreground(owner)) {
                    pendingNotice=notice; pendingNoticeError=error; return;
                }
                if (request.retain) { queueWhenResumed=false; showQueue(owner); toast(owner,notice); }
                else if (error) showError(owner,notice);
                else toast(owner,notice);
            } });
        } }); return true;
    }
    private static String message(Throwable error) {
        String text=error.getMessage(); return text==null||text.length()==0?error.getClass().getSimpleName():text;
    }
    private static void showError(Activity activity,String reason) {
        if (!usable(activity)) return;
        LinearLayout form=new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL);
        label(form,reason==null?"The export could not be completed.":reason);
        final View[] error=new View[1]; final Runnable close=new Runnable() { public void run() { FovMod.dismissGamePanel(error[0]); } };
        Button ok=new Button(activity); ok.setText("OK"); form.addView(ok);
        ok.setOnClickListener(new View.OnClickListener() { public void onClick(View view) { close.run(); } });
        error[0]=FovMod.showGamePanel(activity,"MP4 export",form,close);
    }
}
