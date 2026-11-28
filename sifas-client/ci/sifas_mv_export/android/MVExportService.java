package com.klab.lovelive.allstars.fovmod;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

/** Keeps an export started by the visible game alive when its window stops. */
public final class MVExportService extends Service {
    private static final String CHANNEL = "sifas.mv.export";
    private static final String START = "sifas.mv.export.START";
    private static final String CANCEL = "sifas.mv.export.CANCEL";
    private static final String TOKEN = "exportToken";
    private static final int NOTIFICATION_ID = 4117;

    // Service and export lifecycle both belong to the process main thread.
    private static long requestedToken;
    private static MVExportService instance;
    private long startingToken;
    private long activeToken;
    private boolean foreground;
    private PowerManager.WakeLock wakeLock;
    private long lastProgress;

    static boolean begin(Context context, long token) {
        if (token <= 0 || (requestedToken != 0 && requestedToken != token)) return false;
        if (requestedToken == token) return true;
        Context app = context.getApplicationContext();
        Intent start = new Intent(app, MVExportService.class).setAction(START).putExtra(TOKEN, token);
        requestedToken = token;
        try {
            ComponentName started = Build.VERSION.SDK_INT >= 26
                ? app.startForegroundService(start) : app.startService(start);
            if (started != null) return true;
        } catch (RuntimeException error) {
            Log.w("SIFAS-MV", "Background export service could not start", error);
        }
        clearRequest(token);
        return false;
    }

    private static void clearRequest(long token) {
        if (requestedToken == token) requestedToken = 0;
    }

    static void end(long token) {
        if (requestedToken != token || token <= 0) return;
        requestedToken = 0;
        // If onStartCommand has not arrived, let it meet the platform's
        // foreground deadline and stop itself immediately.
        if (instance != null && instance.activeToken == token) instance.releaseExport();
    }

    static void progress(long token, int done, int total) {
        MVExportService service = instance;
        if (service == null || token <= 0 || service.activeToken != token
                || total <= 0 || done < 0 || done > total) return;
        long now = SystemClock.elapsedRealtime();
        if (done < total && now - service.lastProgress < 1000) return;
        service.lastProgress = now;
        try {
            service.notifications().notify(NOTIFICATION_ID, service.notification(token, done, total));
        } catch (RuntimeException error) {
            Log.w("SIFAS-MV", "Could not update export notification", error);
        }
    }

    @Override public void onCreate() {
        super.onCreate();
        instance = this;
        startingToken = requestedToken;
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) {
            if (activeToken == 0) stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        long token = intent.getLongExtra(TOKEN, 0);
        if (CANCEL.equals(intent.getAction())) {
            if (token > 0 && token == activeToken && token == requestedToken)
                AndroidMVExport.cancelFromBackgroundService(token);
            if (activeToken == 0 && requestedToken == 0) stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        if (!START.equals(intent.getAction())) {
            if (activeToken == 0 && requestedToken == 0) stopSelfResult(startId);
            return START_NOT_STICKY;
        }
        try {
            if (!foreground) {
                if (Build.VERSION.SDK_INT >= 26) {
                    NotificationChannel channel = new NotificationChannel(CHANNEL, "MV export",
                        NotificationManager.IMPORTANCE_LOW);
                    notifications().createNotificationChannel(channel);
                }
                startForeground(NOTIFICATION_ID, notification(token == requestedToken ? token : 0, 0, 0));
                foreground = true;
            }
            if (token <= 0 || token != requestedToken) {
                if (requestedToken == 0) releaseExport();
                return START_NOT_STICKY;
            }
            if (activeToken == token) return START_NOT_STICKY;
            startingToken = token;
            PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
            if (power == null) throw new IllegalStateException("Power service unavailable");
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SIFAS:MVExport");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire();
            activeToken = token;
            lastProgress = 0;
        } catch (RuntimeException error) {
            Log.w("SIFAS-MV", "Background export service could not stay active", error);
            if (requestedToken > 0 && requestedToken != token) return START_NOT_STICKY;
            boolean inform = token > 0 && requestedToken == token;
            clearRequest(token);
            releaseExport();
            if (inform) AndroidMVExport.onBackgroundServiceStopped(token);
            return START_NOT_STICKY;
        }
        try {
            // A stale launch may have published a placeholder notification.
            notifications().notify(NOTIFICATION_ID, notification(token, 0, 0));
        } catch (RuntimeException error) {
            Log.w("SIFAS-MV", "Could not refresh export notification", error);
        }
        AndroidMVExport.onBackgroundServiceReady(token);
        return START_NOT_STICKY;
    }

    private NotificationManager notifications() {
        return (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
    }

    private Notification notification(long token, int done, int total) {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        builder.setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("Exporting MV")
            .setContentText("MP4 export in progress")
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setProgress(total, done, total == 0);
        if (token > 0) {
            Intent stop = new Intent(this, MVExportService.class).setAction(CANCEL)
                .setData(Uri.parse("sifas-mv-export://cancel/"+token)).putExtra(TOKEN, token);
            PendingIntent action = PendingIntent.getService(this, 0, stop, PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(new Notification.Action.Builder(android.R.drawable.ic_menu_close_clear_cancel,
                "Cancel", action).build());
        }
        return builder.build();
    }

    private void releaseWakeLock() {
        if (wakeLock != null) {
            if (wakeLock.isHeld()) wakeLock.release();
            wakeLock = null;
        }
    }

    private void releaseExport() {
        activeToken = 0;
        releaseWakeLock();
        if (foreground) {
            if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE);
            else stopForeground(true);
            foreground = false;
        }
        stopSelf();
    }

    @Override public void onDestroy() {
        long ended = activeToken != 0 ? activeToken : startingToken;
        startingToken = 0;
        activeToken = 0;
        releaseWakeLock();
        if (instance == this) instance = null;
        if (ended > 0 && requestedToken == ended) {
            requestedToken = 0;
            AndroidMVExport.onBackgroundServiceStopped(ended);
        }
        super.onDestroy();
    }
}
