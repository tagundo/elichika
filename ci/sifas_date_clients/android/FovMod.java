package com.klab.lovelive.allstars.fovmod;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.util.AtomicFile;
import android.util.Log;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.lang.ref.WeakReference;
import java.util.WeakHashMap;
import java.util.Locale;

/** App-private configuration bridge for the packaged SIFAS camera mod. */
public final class FovMod {
    public static final String PREFS = "fovmod";
    public static final String CFG_FILE = "fovmod.cfg";
    public static final int ORIENT_AUTO = 0;
    public static final int ORIENT_PORTRAIT = 1;
    public static final int ORIENT_LANDSCAPE = 2;
    private static final String TAG = "SIFAS-FOV";
    private static final int FMOV_BASE = 0x1e201000;
    private static final int FMOV_VARIABLE = (0xff << 13) | 0x1f;
    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static boolean nativeLoaded;
    private static String loadError;
    private static boolean initialized;
    private static final String FROM_GAME = "fovmod.from_game";
    private static final WeakHashMap<Activity, GameGesture> gestures = new WeakHashMap<Activity, GameGesture>();

    private FovMod() {}

    private static native int nativeConfigure(float min, float max, int splash, String filesDir);

    public static synchronized void init(Application app) {
        if (initialized) return;
        initialized = true;
        try {
            System.loadLibrary("fovmod");
            nativeLoaded = true;
        } catch (LinkageError error) {
            loadError = error.toString();
            Log.e(TAG, "Bundled native camera mod could not load", error);
            writeStatus(app, "ERROR native library unavailable: " + loadError);
        } catch (SecurityException error) {
            loadError = error.toString();
            Log.e(TAG, "Bundled native camera mod was not permitted to load", error);
            writeStatus(app, "ERROR native library unavailable: " + loadError);
        }
        app.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            public void onActivityCreated(Activity activity, Bundle state) { onGameActivity(activity); }
            public void onActivityResumed(Activity activity) { onGameActivity(activity); }
            public void onActivityStarted(Activity activity) {}
            public void onActivityPaused(Activity activity) {
                GameGesture gesture = gestures.get(activity);
                if (gesture != null) gesture.cancel();
            }
            public void onActivityStopped(Activity activity) {}
            public void onActivitySaveInstanceState(Activity activity, Bundle state) {}
            public void onActivityDestroyed(Activity activity) {
                GameGesture gesture = gestures.remove(activity);
                if (gesture != null) gesture.cancel();
            }
        });
    }

    private static boolean isGameActivity(Activity activity) {
        String name = activity.getClass().getName();
        return name.equals("com.klab.lovelive.allstars.global.GlobalUnsafeMainActivity")
            || name.equals("com.klab.lovelive.allstars.MainActivity");
    }

    static void onGameActivity(Activity activity) {
        if (!isGameActivity(activity)) return;
        ensureGesture(activity);
        applyOrientation(activity);
        configure(activity, false);
    }

    private static GameGesture ensureGesture(Activity activity) {
        GameGesture previous = gestures.get(activity);
        View view = activity.getWindow().getDecorView();
        if (previous == null || previous.decor.get() != view) {
            if (previous != null) previous.cancel();
            previous = new GameGesture(activity, view);
            gestures.put(activity, previous);
        }
        return previous;
    }

    /** Called only by the actual game Activity touch override, on the UI thread. */
    public static boolean handleGameTouch(Activity activity, MotionEvent event) {
        GameGesture gesture = gestures.get(activity);
        if (gesture == null) {
            if (!isGameActivity(activity)) return false;
            gesture = ensureGesture(activity);
        }
        return gesture.onTouch(event);
    }

    /** A menu opened over the game returns to the same Activity after saving. */
    public static boolean closeInGameSettings(Activity settings) {
        Intent intent = settings.getIntent();
        if (intent == null || !intent.getBooleanExtra(FROM_GAME, false)) return false;
        settings.finish();
        return true;
    }

    public static String getBuildLabel(Context context) {
        try {
            return buildLabelFromVersionName(context.getPackageManager()
                .getPackageInfo(context.getPackageName(), 0).versionName);
        } catch (PackageManager.NameNotFoundException error) {
            Log.e(TAG, "Installed client build metadata could not be read", error);
            return "Build unavailable";
        }
    }

    static String buildLabelFromVersionName(String version) {
        if (version == null || version.length() == 0) return "Build unavailable";
        String prefix = "3.12.0-fovmod.";
        if (version.startsWith(prefix)) {
            String build = version.substring(prefix.length());
            if (build.matches("[0-9]{4}\\.[0-9]{2}\\.[0-9]{2}\\.[1-9][0-9]?")) return build;
        }
        return version; // Legacy installs display their actual version, never a fixed build number.
    }

    public static String getBuildTitle(Context context) {
        return "SIFAS FoV  \u00b7  " + getBuildLabel(context);
    }

    public static String getMenuHint(Context context) {
        String lang = preferences(context).getString("lang", Locale.getDefault().getLanguage());
        if (lang.startsWith("ko")) return "게임 화면 오른쪽 위를 2초 동안 누르면 설정이 열립니다. 저장하면 기존 게임 화면으로 돌아갑니다.";
        if (lang.startsWith("ja")) return "ゲーム画面の右上を2秒間長押しすると設定が開きます。保存すると元のゲーム画面に戻ります。";
        if (lang.startsWith("zh")) return lang.contains("Hant") || lang.contains("TW")
            ? "在遊戲中長按右上角 2 秒即可開啟設定。儲存後返回目前的遊戲。"
            : "在游戏中长按右上角 2 秒即可打开设置。保存后返回当前游戏。";
        return "In game, hold the top-right corner for 2 seconds to open these settings. Save returns to the current game.";
    }

    /** Android-independent state machine; ordinary touches remain unconsumed. */
    static final class CornerHold {
        static final long HOLD_MS = 2000;
        private static final int IDLE = 0, TRACKING = 1, CONSUMING = 2;
        private int state;
        private float downX, downY, lastX, lastY;
        private long startedAt;
        private int slop;

        static boolean inCorner(float x, float y, int width, float edge) {
            return width > 0 && edge > 0 && x >= Math.max(0, width - edge)
                && x <= width && y >= 0 && y <= edge;
        }
        boolean tracking() { return state == TRACKING; }
        boolean consuming() { return state == CONSUMING; }
        void cancel() { state = IDLE; }
        long remaining(long now) {
            return Math.max(1, Math.min(HOLD_MS, HOLD_MS - (now - startedAt)));
        }
        boolean onEvent(int action, int pointers, float x, float y, int width,
                        float edge, int touchSlop, long now) {
            if (action == MotionEvent.ACTION_DOWN) {
                cancel();
                if (pointers == 1 && inCorner(x, y, width, edge)) {
                    state = TRACKING; downX = lastX = x; downY = lastY = y;
                    startedAt = now; slop = Math.max(0, touchSlop);
                }
                return false;
            }
            if (state == CONSUMING) {
                if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) cancel();
                return true;
            }
            if (state != TRACKING) return false;
            if (pointers != 1 || action == MotionEvent.ACTION_POINTER_DOWN
                    || action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_UP
                    || action == MotionEvent.ACTION_CANCEL || action == MotionEvent.ACTION_OUTSIDE) {
                cancel(); return false;
            }
            if (action == MotionEvent.ACTION_MOVE) {
                lastX = x; lastY = y;
                double dx = x - downX, dy = y - downY;
                if (!inCorner(x, y, width, edge) || dx * dx + dy * dy > (double)slop * slop) cancel();
            }
            return false;
        }
        boolean onTimeout(long now, int width, float edge) {
            if (state != TRACKING) return false;
            if (!inCorner(lastX, lastY, width, edge)) { cancel(); return false; }
            if (now - startedAt < HOLD_MS) return false;
            state = CONSUMING;
            return true;
        }
    }

    private static final class GameGesture implements Runnable {
        final WeakReference<Activity> activity;
        final WeakReference<View> decor;
        final CornerHold hold = new CornerHold();
        boolean sendingCancel;
        long downTime;
        float lastX, lastY;
        GameGesture(Activity owner, View view) {
            activity = new WeakReference<Activity>(owner);
            decor = new WeakReference<View>(view);
        }
        float edge(Activity owner) { return 64 * owner.getResources().getDisplayMetrics().density; }
        void cancel() {
            View view = decor.get();
            if (view != null) view.removeCallbacks(this);
            hold.cancel();
        }
        boolean onTouch(MotionEvent event) {
            if (sendingCancel) return false; // Forward our one synthetic CANCEL through the original engine chain.
            int action = event.getActionMasked();
            if (action != MotionEvent.ACTION_DOWN && !hold.tracking() && !hold.consuming()) return false;
            if (action != MotionEvent.ACTION_DOWN && hold.consuming())
                return hold.onEvent(action, 0, 0, 0, 0, 0, 0, 0);
            Activity owner = activity.get(); View view = decor.get();
            if (owner == null || view == null) { cancel(); return false; }
            lastX = event.getX(); lastY = event.getY();
            float edge = edge(owner);
            int slop = 0;
            if (action == MotionEvent.ACTION_DOWN) {
                cancel();
                if (event.getPointerCount() != 1 || !CornerHold.inCorner(lastX, lastY, view.getWidth(), edge)) return false;
                slop = ViewConfiguration.get(owner).getScaledTouchSlop();
            }
            boolean consumed = hold.onEvent(action, event.getPointerCount(), lastX, lastY,
                view.getWidth(), edge, slop, SystemClock.uptimeMillis());
            if (action == MotionEvent.ACTION_DOWN) {
                view.removeCallbacks(this); downTime = event.getDownTime();
                if (hold.tracking()) view.postDelayed(this, CornerHold.HOLD_MS);
            } else if (!hold.tracking()) view.removeCallbacks(this);
            return consumed;
        }
        @Override public void run() {
            Activity owner = activity.get(); View view = decor.get();
            if (owner == null || view == null || owner.isFinishing() || owner.isDestroyed()
                    || !owner.hasWindowFocus()) { cancel(); return; }
            long now = SystemClock.uptimeMillis();
            if (!hold.onTimeout(now, view.getWidth(), edge(owner))) {
                if (hold.tracking()) view.postDelayed(this, hold.remaining(now));
                return;
            }
            MotionEvent cancelled = MotionEvent.obtain(downTime, now, MotionEvent.ACTION_CANCEL, lastX, lastY, 0);
            sendingCancel = true;
            try {
                owner.dispatchTouchEvent(cancelled);
            } catch (RuntimeException error) {
                Log.e(TAG, "Game touch cancellation failed; FOV menu was not opened", error);
                hold.cancel();
                return;
            } finally {
                sendingCancel = false;
                cancelled.recycle();
            }
            if (owner.isFinishing() || owner.isDestroyed() || !owner.hasWindowFocus()) return;
            Intent intent = new Intent().setClassName(owner.getPackageName(),
                "com.klab.lovelive.allstars.fovmod.FovSettingsActivity").putExtra(FROM_GAME, true);
            try {
                owner.startActivity(intent);
            } catch (RuntimeException error) {
                Log.e(TAG, "FOV settings Activity could not be opened", error);
                Toast.makeText(owner, "FOV settings could not be opened. Check SIFAS-FOV logs.", Toast.LENGTH_LONG).show();
            }
        }
    }

    /** Called by the actual game Activity override for every engine request. */
    public static int resolveOrientation(Activity activity, int engineRequest) {
        int preference = getOrient(activity);
        if (preference == ORIENT_PORTRAIT) return 1;
        if (preference == ORIENT_LANDSCAPE) return 0;
        return engineRequest;
    }

    static void applyOrientation(Activity activity) {
        int preference = getOrient(activity);
        if (preference == ORIENT_PORTRAIT) activity.setRequestedOrientation(1);
        else if (preference == ORIENT_LANDSCAPE) activity.setRequestedOrientation(0);
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static int getMinWord(Context context) {
        int fallback = encodeFmov(1, 0.75f);
        int word = preferences(context).getInt("minWord", fallback);
        return validWord(word, 1) ? word : fallback;
    }

    public static int getMaxWord(Context context) {
        int fallback = encodeFmov(2, 1.0f);
        int word = preferences(context).getInt("maxWord", fallback);
        return validWord(word, 2) ? word : fallback;
    }

    public static int getOrient(Context context) {
        int value = preferences(context).getInt("orient", ORIENT_AUTO);
        return value >= ORIENT_AUTO && value <= ORIENT_LANDSCAPE ? value : ORIENT_AUTO;
    }

    public static int getSplash(Context context) {
        return preferences(context).getInt("splash", 0) == 1 ? 1 : 0;
    }

    public static void saveConfig(Context context, int minWord, int maxWord, int orientation, int splash) {
        saveConfigAndCheck(context, minWord, maxWord, orientation, splash);
    }

    public static boolean saveConfigAndCheck(Context context, int minWord, int maxWord, int orientation, int splash) {
        if (!validWord(minWord, 1) || !validWord(maxWord, 2)) {
            showFailure(context, "Invalid camera limits; settings were not saved.");
            return false;
        }
        float min = decodeWord(minWord), max = decodeWord(maxWord);
        if (min > max || orientation < ORIENT_AUTO || orientation > ORIENT_LANDSCAPE || (splash != 0 && splash != 1)) {
            showFailure(context, "Invalid camera settings; minimum must not exceed maximum.");
            return false;
        }
        boolean saved = preferences(context).edit().putInt("minWord", minWord).putInt("maxWord", maxWord)
            .putInt("orient", orientation).putInt("splash", splash).commit();
        if (!saved) {
            showFailure(context, "Camera settings could not be saved.");
            return false;
        }
        String config = String.format(Locale.ROOT, "min=%08x\nmax=%08x\norient=%d\nsplash=%d\n", minWord, maxWord, orientation, splash);
        if (!writePrivate(context, CFG_FILE, config)) {
            showFailure(context, "Camera configuration file could not be saved.");
            return false;
        }
        configure(context, true);
        return true;
    }

    private static synchronized void configure(Context context, boolean notifyError) {
        if (!nativeLoaded) {
            String message = "Native camera mod unavailable" + (loadError == null ? "" : ": " + loadError);
            writeStatus(context, "ERROR " + message);
            if (notifyError) Toast.makeText(context, message, Toast.LENGTH_LONG).show();
            return;
        }
        float min = decodeWord(getMinWord(context)), max = decodeWord(getMaxWord(context));
        if (min > max) {
            showFailure(context, "Saved camera limits are invalid; choose a minimum below the maximum.");
            return;
        }
        try {
            int result = nativeConfigure(min, max, getSplash(context), context.getFilesDir().getAbsolutePath());
            String state = result == 1 ? "APPLIED" : result == 0 ? "WAITING FOR GAME"
                : result == -1 ? "ERROR invalid configuration"
                : result == -2 ? "ERROR unsupported packaged game image"
                : result == -3 ? "ERROR game initialization worker unavailable"
                : result == -4 ? "ERROR timed out waiting for game" : "ERROR unexpected native result";
            String status = String.format(Locale.ROOT, "%s native=%d min=%.5f max=%.5f orientation=%d splash=%d", state, result, min, max, getOrient(context), getSplash(context));
            // The native worker owns successful/pending status transitions. Rewriting
            // a returned WAITING result here could overwrite its later APPLIED result.
            if (result < 0) {
                writeStatus(context, status);
                Log.e(TAG, status);
                if (notifyError) Toast.makeText(context, "Camera mod configuration failed (" + result + "). Details are shown in Settings.", Toast.LENGTH_LONG).show();
            } else {
                Log.i(TAG, status);
            }
        } catch (LinkageError error) {
            Log.e(TAG, "Native camera configuration failed", error);
            writeStatus(context, "ERROR native configuration: " + error);
            if (notifyError) Toast.makeText(context, "Camera mod could not be configured. Details are shown in Settings.", Toast.LENGTH_LONG).show();
        } catch (RuntimeException error) {
            Log.e(TAG, "Camera configuration failed", error);
            writeStatus(context, "ERROR configuration: " + error);
            if (notifyError) Toast.makeText(context, "Camera mod could not be configured. Details are shown in Settings.", Toast.LENGTH_LONG).show();
        }
    }

    private static void showFailure(Context context, String message) {
        Log.e(TAG, message);
        writeStatus(context, "ERROR " + message);
        Toast.makeText(context, message, Toast.LENGTH_LONG).show();
    }

    private static void writeStatus(Context context, String status) {
        writePrivate(context, "fovmod_status.txt", status + "\n");
    }

    private static boolean writePrivate(Context context, String name, String text) {
        AtomicFile file = new AtomicFile(new File(context.getFilesDir(), name));
        FileOutputStream stream = null;
        try {
            stream = file.startWrite();
            stream.write(text.getBytes(UTF8));
            file.finishWrite(stream);
            return true;
        } catch (Exception error) {
            if (stream != null) file.failWrite(stream);
            Log.e(TAG, "Could not write app-private " + name, error);
            return false;
        }
    }

    private static boolean validWord(int word, int register) {
        float value = decodeWord(word);
        return (word & ~FMOV_VARIABLE) == FMOV_BASE && (word & 31) == register
            && value >= 0.5f && value <= 2.0f;
    }

    private static float decodeWord(int word) { return imm8ToFloat((word >>> 13) & 0xff); }

    public static int encodeFmov(int register, float value) {
        int immediate = floatToImm8(value);
        if (immediate < 0) throw new IllegalArgumentException("value not FMOV-encodable: " + value);
        return encodeFmovImm8(register, immediate);
    }

    public static int encodeFmovImm8(int register, int immediate) {
        return FMOV_BASE | ((immediate & 0xff) << 13) | (register & 31);
    }

    public static int floatToImm8(float value) {
        for (int immediate = 0; immediate < 256; immediate++) {
            if (imm8ToFloat(immediate) == value) return immediate;
        }
        return -1;
    }

    public static float imm8ToFloat(int immediate) {
        int sign = (immediate >>> 7) & 1;
        int bit6 = (immediate >>> 6) & 1;
        int exponent = ((1 - bit6) << 7) | ((bit6 == 1 ? 31 : 0) << 2) | ((immediate >>> 4) & 3);
        int fraction = (immediate & 15) << 19;
        return Float.intBitsToFloat((sign << 31) | (exponent << 23) | fraction);
    }
}
