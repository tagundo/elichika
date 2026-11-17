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
import android.view.KeyEvent;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewConfiguration;
import android.view.inputmethod.InputMethodManager;
import android.util.AtomicFile;
import android.util.Log;
import android.widget.Toast;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.WeakHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;

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
    private static WeakReference<GamePanel> gamePanel = new WeakReference<GamePanel>(null);

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
            public void onActivityResumed(Activity activity) {
                onGameActivity(activity);
                if (isGameActivity(activity)) AndroidMVExport.onGameResumed(activity);
            }
            public void onActivityStarted(Activity activity) {}
            public void onActivityPaused(Activity activity) {
                GameGesture gesture = gestures.get(activity);
                if (gesture != null) gesture.cancel();
                dismissGamePanelFor(activity);
                if (isGameActivity(activity)) AndroidMVExport.onGamePaused(activity);
            }
            public void onActivityStopped(Activity activity) {}
            public void onActivitySaveInstanceState(Activity activity, Bundle state) {}
            public void onActivityDestroyed(Activity activity) {
                GameGesture gesture = gestures.remove(activity);
                if (gesture != null) gesture.cancel();
                dismissGamePanelFor(activity);
                if (isGameActivity(activity)) AndroidMVExport.onGameDestroyed(activity);
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
        GamePanel panel = gamePanel.get();
        return panel != null && panel.getContext() == activity && panel.getParent() != null
            ? gesture.onPanelTouch(event) : gesture.onTouch(event);
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
        if (lang.startsWith("ko")) return "게임 화면 오른쪽 위를 2초간 길게 누르면 FOV 설정창을 열 수 있습니다. 저장하면 기존 게임 화면으로 돌아갑니다.";
        if (lang.startsWith("ja")) return "ゲーム画面の右上を2秒間長押しするとFOV設定を開けます。保存すると元のゲーム画面に戻ります。";
        if (lang.startsWith("zh")) return lang.contains("Hant") || lang.contains("TW")
            ? "在遊戲中長按右上角 2 秒即可開啟 FOV 設定。儲存後返回目前的遊戲。"
            : "在游戏中长按右上角 2 秒即可打开 FOV 设置。保存后返回当前游戏。";
        return "In game, hold the top-right corner for 2 seconds to open FOV settings. Save returns to the current game.";
    }

    /** Android-independent recognition state; a corner DOWN reserves its stream. */
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
                return state == TRACKING;
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
            return state == TRACKING;
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
        private static final int MAX_BUFFERED_EVENTS = 512;
        final WeakReference<Activity> activity;
        final WeakReference<View> decor;
        final CornerHold hold = new CornerHold();
        final ArrayList<MotionEvent> buffered = new ArrayList<MotionEvent>();
        boolean replaying, discarding;
        GameGesture(Activity owner, View view) {
            activity = new WeakReference<Activity>(owner);
            decor = new WeakReference<View>(view);
        }
        float edge(Activity owner) { return 64 * owner.getResources().getDisplayMetrics().density; }
        void cancel() {
            View view = decor.get();
            if (view != null) view.removeCallbacks(this);
            // No event from a reserved stream has reached Unity. Swallow its
            // remainder after pause/destroy rather than delivering an orphan UP.
            if (hold.tracking() || hold.consuming() || !buffered.isEmpty()) discarding = true;
            hold.cancel();
            clearBuffer();
        }
        void clearBuffer() {
            for (MotionEvent event : buffered) event.recycle();
            buffered.clear();
        }
        void replay(Activity owner, MotionEvent tail) {
            MotionEvent[] events = buffered.toArray(new MotionEvent[buffered.size()]);
            buffered.clear(); hold.cancel();
            View view = decor.get(); if (view != null) view.removeCallbacks(this);
            MotionEvent last = tail != null ? tail : events[events.length - 1];
            boolean ended = last.getActionMasked() == MotionEvent.ACTION_UP || last.getActionMasked() == MotionEvent.ACTION_CANCEL;
            replaying = true;
            try {
                for (MotionEvent event : events) owner.dispatchTouchEvent(event);
                if (tail != null) owner.dispatchTouchEvent(tail);
            } catch (RuntimeException error) {
                Log.e(TAG, "Buffered game touch replay failed", error);
                MotionEvent cancelled = MotionEvent.obtain(last); cancelled.setAction(MotionEvent.ACTION_CANCEL);
                try { owner.dispatchTouchEvent(cancelled); }
                catch (RuntimeException ignored) {}
                finally { cancelled.recycle(); }
                discarding = !ended;
            } finally {
                replaying = false;
                for (MotionEvent event : events) event.recycle();
            }
        }
        boolean onPanelTouch(MotionEvent event) {
            if (replaying) return false;
            int action = event.getActionMasked();
            if (action == MotionEvent.ACTION_DOWN) { cancel(); discarding = false; return false; }
            if (!discarding && !hold.consuming() && !hold.tracking()) return false;
            cancel();
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) discarding = false;
            return true;
        }
        boolean onTouch(MotionEvent event) {
            if (replaying) return false; // Run each saved event through the original dispatch chain once.
            int action = event.getActionMasked();
            if (action == MotionEvent.ACTION_DOWN) {
                cancel(); discarding = false;
            } else if (discarding) {
                if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) discarding = false;
                return true;
            }
            if (action != MotionEvent.ACTION_DOWN && hold.consuming())
                return hold.onEvent(action, 0, 0, 0, 0, 0, 0, 0);
            if (action != MotionEvent.ACTION_DOWN && !hold.tracking()) return false;
            Activity owner = activity.get(); View view = decor.get();
            if (owner == null || view == null) {
                boolean reserved = hold.tracking(); cancel();
                if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) discarding = false;
                return reserved;
            }
            float x = event.getX(), y = event.getY();
            float edge = edge(owner);
            int slop = 0;
            if (action == MotionEvent.ACTION_DOWN) {
                if (event.getPointerCount() != 1 || !CornerHold.inCorner(x, y, view.getWidth(), edge)) return false;
                slop = ViewConfiguration.get(owner).getScaledTouchSlop();
            }
            if (buffered.size() >= MAX_BUFFERED_EVENTS) {
                // Release a complete ordered prefix and this event before normal
                // passthrough resumes; never drop an UP or pointer transition.
                replay(owner,event); return true;
            }
            buffered.add(MotionEvent.obtain(event));
            hold.onEvent(action, event.getPointerCount(), x, y,
                view.getWidth(), edge, slop, SystemClock.uptimeMillis());
            if (action == MotionEvent.ACTION_DOWN) {
                if (hold.tracking()) view.postDelayed(this, CornerHold.HOLD_MS);
            } else if (!hold.tracking()) replay(owner,null);
            return true;
        }
        @Override public void run() {
            Activity owner = activity.get(); View view = decor.get();
            if (owner == null || view == null || owner.isFinishing() || owner.isDestroyed()
                    || !owner.hasWindowFocus()) { cancel(); return; }
            long now = SystemClock.uptimeMillis();
            if (!hold.onTimeout(now, view.getWidth(), edge(owner))) {
                if (hold.tracking()) view.postDelayed(this, hold.remaining(now));
                else if (!buffered.isEmpty()) replay(owner,null);
                return;
            }
            // The reserved hold never reaches Unity, so opening the menu cannot
            // first toggle the game's tap-to-pause control.
            clearBuffer();
            if (owner.isFinishing() || owner.isDestroyed() || !owner.hasWindowFocus()) return;
            try {
                if (!AndroidMVExport.isBusy()) showInGameSettings(owner);
            } catch (RuntimeException error) {
                Log.e(TAG, "FOV settings Activity could not be opened", error);
                Toast.makeText(owner, "FOV settings could not be opened. Check SIFAS-FOV logs.", Toast.LENGTH_LONG).show();
            }
        }
    }

    /** One View in the existing game window: no Activity, Dialog or PopupWindow. */
    static final class GamePanel extends FrameLayout {
        final Runnable onClose;
        final WeakReference<View> previousFocus;
        GamePanel(Activity owner,Runnable onClose) {
            super(owner); this.onClose=onClose; previousFocus=new WeakReference<View>(owner.getCurrentFocus());
            setClickable(true); setFocusableInTouchMode(true); setBackgroundColor(0xb0000000);
        }
        @Override public boolean dispatchKeyEvent(KeyEvent event) {
            if (event.getKeyCode()!=KeyEvent.KEYCODE_BACK) return super.dispatchKeyEvent(event);
            if (event.getAction()==KeyEvent.ACTION_UP && !event.isCanceled()) onClose.run();
            return true;
        }
    }
    static GamePanel showGamePanel(Activity owner,String title,View content,Runnable onClose) {
        GamePanel previous=gamePanel.get(); if (previous!=null) dismissGamePanel(previous);
        GamePanel cover=new GamePanel(owner,onClose);
        LinearLayout box=new LinearLayout(owner); box.setOrientation(LinearLayout.VERTICAL); box.setBackgroundColor(0xff20242a);
        int pad=(int)(16*owner.getResources().getDisplayMetrics().density+0.5f); box.setPadding(pad,pad,pad,pad);
        TextView heading=new TextView(owner); heading.setText(title); heading.setTextSize(20); heading.setTextColor(0xffffffff); box.addView(heading);
        ScrollView scroll=new ScrollView(owner); scroll.addView(content); box.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        FrameLayout.LayoutParams layout=new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER); layout.setMargins(pad,pad,pad,pad); cover.addView(box,layout);
        View decor=owner.getWindow().getDecorView();
        if (!(decor instanceof ViewGroup)) throw new IllegalStateException("Game window is unavailable");
        ((ViewGroup)decor).addView(cover,new ViewGroup.LayoutParams(-1,-1)); gamePanel=new WeakReference<GamePanel>(cover); cover.requestFocus();
        return cover;
    }
    static void dismissGamePanel(View panel) {
        if (panel==null) return;
        boolean current=gamePanel.get()==panel;
        if (current && panel.getWindowToken()!=null) {
            InputMethodManager keyboard=(InputMethodManager)panel.getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
            if (keyboard!=null) keyboard.hideSoftInputFromWindow(panel.getWindowToken(),0);
        }
        if (panel.getParent() instanceof ViewGroup) ((ViewGroup)panel.getParent()).removeView(panel);
        if (current) gamePanel=new WeakReference<GamePanel>(null);
        if (current && panel instanceof GamePanel) {
            View previous=((GamePanel)panel).previousFocus.get();
            if (previous!=null && previous.getWindowToken()!=null) previous.requestFocus();
        }
    }
    private static void dismissGamePanelFor(Activity owner) {
        GamePanel panel=gamePanel.get(); if (panel!=null && panel.getContext()==owner) dismissGamePanel(panel);
    }
    /** A cycle button keeps selection in the same window, unlike Spinner popups. */
    static final class InlineChoice extends Button {
        final String[] choices; int selected; Runnable changed;
        InlineChoice(Context context,String[] choices) {
            super(context); this.choices=choices; setSelection(0);
            setOnClickListener(new View.OnClickListener() { public void onClick(View view) { setSelection((selected+1)%InlineChoice.this.choices.length); } });
        }
        int getSelectedItemPosition() { return selected; }
        void setSelection(int value) { selected=Math.max(0,Math.min(choices.length-1,value)); setText(choices[selected]); if (changed!=null) changed.run(); }
        void setOnSelectionChanged(Runnable listener) { changed=listener; }
    }
    private static TextView settingText(LinearLayout form,String text) {
        TextView value=new TextView(form.getContext()); value.setText(text); value.setTextColor(0xffffffff); form.addView(value); return value;
    }
    private static Button settingButton(LinearLayout form,String text,View.OnClickListener listener) {
        Button button=new Button(form.getContext()); button.setText(text); button.setOnClickListener(listener); form.addView(button); return button;
    }
    private static String settingString(Map<?,?> strings,String key,String fallback) {
        Object value=strings==null?null:strings.get(key); return value instanceof String?(String)value:fallback;
    }
    private static Map<?,?> settingsStrings(String language) {
        try {
            java.lang.reflect.Method method=Class.forName("com.klab.lovelive.allstars.fovmod.FovSettingsActivity").getDeclaredMethod("strings",String.class);
            method.setAccessible(true); return (Map<?,?>)method.invoke(null,language);
        } catch (Exception ignored) { return null; }
    }
    private static String cameraStatus(Activity owner) {
        try (FileInputStream input=new FileInputStream(new File(owner.getFilesDir(),"fovmod_status.txt"))) {
            byte[] bytes=new byte[16384]; int count=input.read(bytes); return count>0?new String(bytes,0,count,UTF8):"No diagnostics yet.";
        } catch (Exception ignored) { return "No diagnostics yet."; }
    }
    private static int gridIndex(ArrayList<Float> values,float wanted) {
        int result=0; float distance=Float.MAX_VALUE;
        for (int i=0;i<values.size();i++) if (Math.abs(values.get(i)-wanted)<distance) { result=i; distance=Math.abs(values.get(i)-wanted); }
        return result;
    }
    private static void showInGameSettings(final Activity owner) {
        String language=preferences(owner).getString("lang",Locale.getDefault().getLanguage());
        final Map<?,?> strings=settingsStrings(language);
        final LinearLayout form=new LinearLayout(owner); form.setOrientation(LinearLayout.VERTICAL);
        final GamePanel[] panel=new GamePanel[1]; final Runnable close=new Runnable() { public void run() { dismissGamePanel(panel[0]); } };
        settingText(form,getMenuHint(owner));
        settingText(form,settingString(strings,"langLabel","Language"));
        final InlineChoice languages=new InlineChoice(owner,new String[]{"English","日本語","한국어"});
        languages.setSelection(language.startsWith("ja")?1:language.startsWith("ko")?2:0); form.addView(languages);
        languages.setOnSelectionChanged(new Runnable() { public void run() {
            preferences(owner).edit().putString("lang",new String[]{"en","ja","ko"}[languages.getSelectedItemPosition()]).apply();
            showInGameSettings(owner);
        } });
        settingText(form,settingString(strings,"zoom","Raise both to zoom in; lower both to widen. Default 0.75 / 1.0."));
        TreeMap<Float,Integer> grid=new TreeMap<Float,Integer>();
        for (int i=0;i<256;i++) { float value=imm8ToFloat(i); if (value>=0.5f && value<=2.0f) grid.put(value,i); }
        final ArrayList<Float> values=new ArrayList<Float>(grid.keySet()); final ArrayList<Integer> immediates=new ArrayList<Integer>(grid.values());
        final TextView minLabel=settingText(form,settingString(strings,"min","MinAspect (lower bound)"));
        final SeekBar min=new SeekBar(owner); min.setMax(values.size()-1); min.setProgress(gridIndex(values,decodeWord(getMinWord(owner)))); form.addView(min);
        final TextView maxLabel=settingText(form,settingString(strings,"max","MaxAspect (upper bound)"));
        final SeekBar max=new SeekBar(owner); max.setMax(values.size()-1); max.setProgress(gridIndex(values,decodeWord(getMaxWord(owner)))); form.addView(max);
        final Runnable labels=new Runnable() { public void run() {
            minLabel.setText(String.format(Locale.US,"%s = %.5f",settingString(strings,"min","MinAspect"),values.get(min.getProgress())));
            maxLabel.setText(String.format(Locale.US,"%s = %.5f",settingString(strings,"max","MaxAspect"),values.get(max.getProgress())));
        } };
        SeekBar.OnSeekBarChangeListener limits=new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar bar,int progress,boolean user) { labels.run(); }
            public void onStartTrackingTouch(SeekBar bar) {} public void onStopTrackingTouch(SeekBar bar) {}
        };
        min.setOnSeekBarChangeListener(limits); max.setOnSeekBarChangeListener(limits); labels.run();
        settingText(form,settingString(strings,"orient","Screen orientation"));
        final InlineChoice orientation=new InlineChoice(owner,new String[]{settingString(strings,"orAuto","Auto"),settingString(strings,"orLand","Landscape"),settingString(strings,"orPort","Portrait")});
        orientation.setSelection(getOrient(owner)==ORIENT_LANDSCAPE?1:getOrient(owner)==ORIENT_PORTRAIT?2:0); form.addView(orientation);
        settingText(form,settingString(strings,"orNote","Portrait may letterbox on some devices."));
        final CheckBox splash=new CheckBox(owner); splash.setText(settingString(strings,"splashChk","Speed up logos on launch")); splash.setTextColor(0xffffffff); splash.setChecked(getSplash(owner)==1); form.addView(splash);
        settingText(form,settingString(strings,"splashNote","Shortens the startup logo fade and hold."));
        settingButton(form,settingString(strings,"reset","Reset"),new View.OnClickListener() { public void onClick(View view) {
            min.setProgress(gridIndex(values,0.75f)); max.setProgress(gridIndex(values,1.0f)); orientation.setSelection(0); splash.setChecked(false);
        } });
        settingButton(form,"Save and close",new View.OnClickListener() { public void onClick(View view) {
            int before=getOrient(owner),selected=new int[]{ORIENT_AUTO,ORIENT_LANDSCAPE,ORIENT_PORTRAIT}[orientation.getSelectedItemPosition()];
            if (saveConfigAndCheck(owner,encodeFmovImm8(1,immediates.get(min.getProgress())),encodeFmovImm8(2,immediates.get(max.getProgress())),selected,splash.isChecked()?1:0)) {
                close.run();
                if (before!=selected) {
                    if (selected==ORIENT_AUTO) {
                        if (owner.getRequestedOrientation()!=-1) owner.setRequestedOrientation(-1);
                    } else applyOrientation(owner);
                }
            }
        } });
        AndroidMVExport.installInGameButtons(owner,form,close);
        settingButton(form,"Close",new View.OnClickListener() { public void onClick(View view) { close.run(); } });
        settingText(form,settingString(strings,"diag","Diagnostics")); settingText(form,cameraStatus(owner));
        panel[0]=showGamePanel(owner,getBuildTitle(owner),form,close);
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
        int requested = preference == ORIENT_PORTRAIT ? 1 : preference == ORIENT_LANDSCAPE ? 0 : Integer.MIN_VALUE;
        if (requested != Integer.MIN_VALUE && activity.getRequestedOrientation() != requested) activity.setRequestedOrientation(requested);
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
