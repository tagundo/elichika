package com.tagundo.elichika

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.OpenableColumns
import android.provider.Settings
import android.text.Layout
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.widget.NestedScrollView
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.google.android.material.tabs.TabLayout
import com.google.android.material.color.MaterialColors
import org.json.JSONObject
import java.io.File
import kotlin.math.ceil

/**
 * Thin shell UI. Everything the user can do is either a service action declared
 * in assets/actions.json (Console tab) or a page served by the Go server / the
 * two Python tool web UIs. The tool and 3D tabs share one WebView. No server/tool
 * logic lives here, so new features show up after a rebuild without touching this file.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var content: FrameLayout
    private lateinit var statusText: TextView
    private lateinit var preparationProgress: ProgressBar
    private lateinit var toggle: Button

    private lateinit var consolePanel: View
    private lateinit var logText: TextView
    private lateinit var logScroll: NestedScrollView
    private lateinit var logPanel: View
    private lateinit var logToggle: Button
    private var logExpanded = false
    private var logRefreshPending = false
    private var advancedExpanded = false

    // Shown in a web tab when the server isn't running yet (instead of a raw
    // "webpage not available" browser error). Its button starts the server.
    private lateinit var offlineOverlay: View
    private lateinit var offlineMessage: TextView
    private lateinit var offlineAction: Button
    private var tabLayout: TabLayout? = null
    private var currentTab = 0
    private var adaptiveHeader: LinearLayout? = null
    private var serverControls: LinearLayout? = null
    private var inlineHeader = false
    private var headerReflowPending = false
    private var headerDisposed = false
    private var headerLayoutObserver: ViewTreeObserver.OnGlobalLayoutListener? = null
    // Bus also owns pending-start state, shared across resized/recreated windows.

    // Lazily-created WebViews for the three local web UIs.
    private val webViews = HashMap<String, WebView>()
    // Tracks whether each WebView's last main-frame load failed (e.g. opened before
    // the server was up). Only those are reloaded on re-open, so re-opening a tab
    // with a running edit/extraction no longer wipes its live page state.
    private val webViewErrored = HashMap<String, Boolean>()
    private val savedWebViews = HashMap<String, Bundle>()
    private lateinit var viewerFullscreen: ViewerFullscreen
    private lateinit var assetNavigation: AssetNavigationBridge

    // File picker for addon zips: copies the chosen file into Download/sukusta/addons,
    // where the dev-tools installers pick it up.
    private val pickAddon = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importAddon(uri)
    }

    // the CDN-cache toggle button, relabelled to show the current on/off state.
    private var cdnButton: Button? = null

    private data class Tab(val id: String, val title: String, val url: String?,
                           val localTools: Boolean = false, val section: String? = null,
                           val managementPage: Boolean = false)
    private val webToolsUrl by lazy { AssetNavigationBridge.pageUrl(Lang.effective(this)) }

    private val tabs by lazy {
        listOf(
            Tab(TAB_CONSOLE, getString(R.string.tab_console), null),
            // The server has no /webui/ index — the panels live at /webui/admin/ and
            // /webui/user/. Point at the admin panel (server config, CDN cache, etc.).
            Tab("server", getString(R.string.tab_webui), "http://127.0.0.1:8080/webui/admin/", managementPage = true),
            Tab("account", getString(R.string.tab_user), "http://127.0.0.1:8080/webui/user/", managementPage = true),
            Tab("server-content", getString(R.string.tab_dev), "http://127.0.0.1:8772/", localTools = true),
            Tab(TAB_ASSET_TOOLS, getString(R.string.tab_mod), webToolsUrl, localTools = true, section = "tools"),
            Tab(TAB_MODEL_VIEWER, getString(R.string.tab_model), webToolsUrl, localTools = true, section = "viewer"),
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Lang.applyToApp(this)
        setContentView(R.layout.activity_main)

        // Mirror the console to a user-visible log file so it can be attached when
        // reporting a bug (needs storage access; fails silently until granted).
        Bus.attachLogFile(File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            "sukusta/logs/elichika.log"))

        content = findViewById(R.id.content)
        statusText = findViewById(R.id.txt_status)
        preparationProgress = findViewById(R.id.progress_preparing)
        toggle = findViewById(R.id.btn_toggle)
        viewerFullscreen = ViewerFullscreen(this,
            listOf(findViewById(R.id.app_header), findViewById(R.id.tabs))) { view ->
            tabs[currentTab].section == "viewer" && webViews[webToolsUrl] === view && view.visibility == View.VISIBLE
        }
        assetNavigation = AssetNavigationBridge(this, ::onAssetSection)

        consolePanel = layoutInflater.inflate(R.layout.panel_console, content, false)
        logText = consolePanel.findViewById(R.id.log_text)
        logScroll = consolePanel.findViewById(R.id.log_scroll)
        logPanel = consolePanel.findViewById(R.id.log_panel)
        logToggle = consolePanel.findViewById(R.id.btn_toggle_log)
        consolePanel.findViewById<Button>(R.id.btn_share_log).setOnClickListener { shareLog() }
        consolePanel.findViewById<Button>(R.id.btn_clear_log).setOnClickListener { clearLog() }
        logToggle.setOnClickListener { setLogExpanded(!logExpanded) }
        setLogExpanded(savedInstanceState?.getBoolean("log_expanded", false) ?: false)
        advancedExpanded = savedInstanceState?.getBoolean("advanced_expanded", false) ?: false
        content.addView(consolePanel)

        offlineOverlay = buildOfflineOverlay()
        content.addView(offlineOverlay)
        offlineOverlay.visibility = View.GONE

        setupActions()
        savedInstanceState?.getBundle("web_views")?.let { states ->
            states.keySet().forEach { url -> states.getBundle(url)?.let { savedWebViews[url] = it } }
        }
        val restoredTab = savedInstanceState?.getString("current_tab_id")?.let { id -> tabs.indexOfFirst { it.id == id } }
            ?.takeIf { it >= 0 } ?: (savedInstanceState?.getInt("current_tab", 0) ?: 0)
        setupTabs(restoredTab)
        setupAdaptiveHeader()
        toggle.setOnClickListener { onToggle() }

        updateRunning(Bus.serverRunning)
        requestNotifications()
        ensureStorageAccess()
        showGuideOnce()
    }

    override fun onBackPressed() {
        if (viewerFullscreen.exit()) return
        // Let the active WebView consume Back (navigate its own history) first, then
        // fall back to the Console tab, and only then exit the app.
        val tab = tabs[currentTab]
        if (tab.url != null) {
            val wv = webViews[tab.url]
            if (wv != null && wv.visibility == View.VISIBLE && wv.canGoBack()) {
                wv.goBack(); return
            }
        }
        if (currentTab != 0) { tabLayout?.getTabAt(0)?.select(); return }
        @Suppress("DEPRECATION") super.onBackPressed()
    }

    private fun buildOfflineOverlay(): View {
        val ll = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        offlineMessage = TextView(this).apply {
            text = getString(R.string.offline_msg)
            gravity = Gravity.CENTER
        }
        ll.addView(offlineMessage)
        offlineAction = Button(this).apply {
            text = getString(R.string.start_server)
            isAllCaps = false
            setOnClickListener { startServerUi() }
        }
        ll.addView(offlineAction)
        return ll
    }

    private fun updateOfflineOverlay(forTools: Boolean) {
        if (!forTools) {
            offlineMessage.setText(R.string.offline_msg)
            offlineAction.setText(R.string.start_server)
            offlineAction.isEnabled = true
            offlineAction.setOnClickListener { startServerUi() }
            return
        }
        val preparing = PyServers.isPreparing()
        val failed = PyServers.hasPreparationError()
        offlineMessage.setText(if (failed && !preparing) R.string.tools_prepare_failed else R.string.tools_preparing)
        offlineAction.setText(if (failed) R.string.tools_retry else R.string.tools_open)
        offlineAction.isEnabled = !preparing
        offlineAction.setOnClickListener { PyServers.prepareAsync(applicationContext) }
    }

    private fun updateToolsState() {
        if (tabs[currentTab].managementPage) {
            showTab(currentTab)
            return
        }
        if (tabs[currentTab].localTools && offlineOverlay.visibility == View.VISIBLE) {
            if (PyServers.isStarted()) showTab(currentTab) else updateOfflineOverlay(true)
        }
    }

    private fun showGuideOnce() {
        val prefs = getSharedPreferences("elichika", MODE_PRIVATE)
        if (prefs.getBoolean("seen_guide", false)) return
        prefs.edit().putBoolean("seen_guide", true).apply()
        showGuide()
    }

    private fun showGuide() {
        AlertDialog.Builder(this)
            .setTitle(R.string.guide_title)
            .setMessage(R.string.guide_body)
            .setPositiveButton(R.string.close, null)
            .show()
    }

    private fun shareLog() {
        val full = Bus.snapshot()
        val text = if (full.length > 60_000) full.substring(full.length - 60_000) else full
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_SUBJECT, "elichika log")
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(send, getString(R.string.btn_share_log)))
    }

    private fun clearLog() {
        Bus.clear()
        logText.text = ""
    }

    private fun setLogExpanded(expanded: Boolean) {
        logExpanded = expanded
        logPanel.visibility = if (expanded) View.VISIBLE else View.GONE
        logToggle.setText(if (expanded) R.string.hide_log else R.string.show_log)
        // Keep collecting logs in Bus while collapsed without rendering them in
        // the menu. Opening the panel always shows the latest complete buffer.
        logText.text = if (expanded) Bus.snapshot() else ""
        if (expanded) logScroll.post { logScroll.scrollTo(0, logText.height) }
    }

    override fun onStart() {
        super.onStart()
        viewerFullscreen.onStart()
        // A split-screen window may be paused while still visible. Keep its status
        // and console subscribed until it is actually stopped.
        Bus.addListener(this, { appendLog(it) }, { updateRunning(it) }, { updateToolsState() })
        if (logExpanded) logText.text = Bus.snapshot()
        updateRunning(Bus.serverRunning)
        updateToolsState()
        refreshCdnLabel()
    }

    override fun onStop() {
        viewerFullscreen.onStop()
        Bus.removeListener(this)
        ManagementServer.releaseUi(this)
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        viewerFullscreen.reapply()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && ::viewerFullscreen.isInitialized) viewerFullscreen.reapply()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        viewerFullscreen.reapply()
        scheduleHeaderReflow()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("current_tab", currentTab)
        outState.putString("current_tab_id", tabs[currentTab].id)
        outState.putBoolean("log_expanded", logExpanded)
        outState.putBoolean("advanced_expanded", advancedExpanded)
        val states = Bundle()
        savedWebViews.forEach { (url, state) -> states.putBundle(url, state) }
        webViews.forEach { (url, webView) ->
            states.putBundle(url, Bundle().also { webView.saveState(it) })
        }
        outState.putBundle("web_views", states)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        if (isFinishing) ManagementServer.releaseUi(this)
        headerDisposed = true
        headerLayoutObserver?.let { observer ->
            adaptiveHeader?.viewTreeObserver?.takeIf { it.isAlive }
                ?.removeOnGlobalLayoutListener(observer)
        }
        headerLayoutObserver = null
        Bus.removeListener(this)
        viewerFullscreen.dispose()
        assetNavigation.dispose()
        webViews.values.forEach { webView ->
            content.removeView(webView)
            webView.destroy()
        }
        webViews.clear()
        super.onDestroy()
    }

    private fun onToggle() {
        if (Bus.serverRunning || Bus.serverStarting) stopServerUi() else startServerUi()
    }

    private fun startServerUi() {
        if (Bus.serverRunning || Bus.serverStarting) return
        Bus.setStarting(true)
        ServerService.start(this)
        updateRunning(false)  // reflect the "starting…" state immediately
    }

    private fun stopServerUi() {
        Bus.setStarting(false)
        ServerService.stop(this)
        updateRunning(false)
    }

    private fun updateRunning(running: Boolean) {
        val phase = Bus.preparationPhase
        val preparing = phase == AssetInstaller.PreparationPhase.PREPARING ||
            phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA
        toggle.setText(if (running || Bus.serverStarting) R.string.stop_server else R.string.start_server)
        val dataProgress = Bus.payloadProgress.takeIf { phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA }
        statusText.text = when {
            dataProgress != null -> getString(R.string.status_data_update_percent, dataProgress.percent)
            phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA -> getString(R.string.status_updating_game_data)
            phase == AssetInstaller.PreparationPhase.PREPARING -> getString(R.string.status_preparing)
            running && !Bus.serverReady -> getString(R.string.status_server_loading)
            running -> getString(R.string.status_running)
            Bus.serverStartupFailed -> getString(R.string.status_server_start_failed)
            phase == AssetInstaller.PreparationPhase.FAILED -> getString(R.string.status_preparation_failed)
            Bus.serverStarting -> getString(R.string.status_starting)
            else -> getString(R.string.status_stopped)
        }
        statusText.contentDescription = dataProgress?.let {
            getString(R.string.progress_work_detail, it.percent, PayloadProgress.stageLabel(this, it.stage), it.completed, it.total)
        } ?: statusText.text
        preparationProgress.visibility = if (preparing || (running && !Bus.serverReady) ||
            (Bus.serverStarting && phase != AssetInstaller.PreparationPhase.FAILED)) View.VISIBLE else View.GONE
        scheduleHeaderReflow()
        // If a web tab is showing the offline overlay and the server just came up,
        // swap the overlay for the (now reachable) page.
        if (tabs[currentTab].managementPage) {
            showTab(currentTab)
        } else if (((running && Bus.serverReady) || (tabs[currentTab].localTools && PyServers.isStarted())) &&
            tabs[currentTab].url != null && offlineOverlay.visibility == View.VISIBLE) {
            showTab(currentTab)
        }
    }

    private fun appendLog(line: String) {
        if (logExpanded && !logRefreshPending) {
            val follow = !logScroll.canScrollVertically(1)
            logRefreshPending = true
            logScroll.postOnAnimation {
                logRefreshPending = false
                if (logExpanded) {
                    // Coalesce bursts and use the bounded buffer. A queued event
                    // already included when opening the log is never duplicated.
                    logText.text = Bus.snapshot()
                    // scrollTo affects only the log viewport, preserving the
                    // outer action list's position while new messages arrive.
                    if (follow) logScroll.post { if (logExpanded) logScroll.scrollTo(0, logText.height) }
                }
            }
        }
        if (line.contains("cdn_cache:")) refreshCdnLabel()
    }

    /** Resolve a localized action label from its label_id resource, falling back to json. */
    private fun actionLabel(a: JSONObject): String {
        val id = a.optString("label_id")
        if (id.isNotEmpty()) {
            val resId = resources.getIdentifier(id, "string", packageName)
            if (resId != 0) return getString(resId)
        }
        return a.optString("label", a.optString("id"))
    }

    /** Relabel the CDN-cache button to show the current state read from config.json. */
    private fun refreshCdnLabel() {
        val b = cdnButton ?: return
        b.text = when (readCdnCache()) {
            true -> getString(R.string.cdn_on)
            false -> getString(R.string.cdn_off)
            else -> getString(R.string.act_cdn_cache)
        }
    }

    private fun showSettings() {
        val items = arrayOf(
            getString(R.string.settings_ui_language),
            getString(R.string.settings_gamedata_language),
            getString(R.string.settings_auto_stop)
        )
        AlertDialog.Builder(this)
            .setTitle(R.string.settings_title)
            .setItems(items) { _, which ->
                when (which) {
                    0 -> showUiLanguageSetting()
                    1 -> showGamedataLanguageSetting()
                    2 -> showAutoStopSetting()
                }
            }
            .setNegativeButton(R.string.close, null)
            .show()
    }

    private fun showAutoStopSetting() {
        val input = android.widget.EditText(this).apply {
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
            setText(ServerSettings.autoStopMinutes(this@MainActivity).toString())
            selectAll()
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.settings_auto_stop)
            .setMessage(R.string.auto_stop_hint)
            .setView(input)
            .setPositiveButton(R.string.save, null)
            .setNegativeButton(R.string.cancel, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val minutes = input.text.toString().toIntOrNull()
                if (minutes == null || minutes !in 0..ServerSettings.MAX_AUTO_STOP_MINUTES) {
                    input.error = getString(R.string.auto_stop_invalid)
                } else {
                    ServerSettings.setAutoStopMinutes(this, minutes)
                    dialog.dismiss()
                }
            }
        }
        dialog.show()
    }

    private fun showUiLanguageSetting() {
        val codes = listOf("auto") + Lang.SUPPORTED
        val labels = arrayOf(getString(R.string.lang_auto), "English", "한국어", "日本語")
        val current = codes.indexOf(Lang.pref(this)).coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle("${getString(R.string.settings_title)} · ${getString(R.string.settings_ui_language)}")
            .setSingleChoiceItems(labels, current) { dialog, which ->
                Lang.setPref(this, codes[which])
                Lang.writeWebuiLanguage(this, filesDir)
                dialog.dismiss()
                Bus.log(getString(R.string.log_settings_lang, codes[which], getString(R.string.restart_hint)))
                Lang.applyToApp(this) // recreates the activity to apply the new locale
            }
            .setNegativeButton(R.string.close, null)
            .show()
    }

    // Which game-data languages the server loads at startup (config.json "locales").
    // Loading one region instead of all four cuts server start time; the value is the
    // same comma string locale.init() parses.
    private val gamedataLocaleValues = listOf("ja,en,zh,ko", "ja", "en", "ko", "zh")

    private fun showGamedataLanguageSetting() {
        val labels = arrayOf(
            getString(R.string.gamedata_all),
            getString(R.string.gamedata_ja),
            getString(R.string.gamedata_en),
            getString(R.string.gamedata_ko),
            getString(R.string.gamedata_zh)
        )
        val current = gamedataLocaleValues.indexOf(readLocales()).coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle("${getString(R.string.settings_title)} · ${getString(R.string.settings_gamedata_language)}")
            .setSingleChoiceItems(labels, current) { dialog, which ->
                writeLocales(gamedataLocaleValues[which])
                dialog.dismiss()
                Bus.log(getString(R.string.log_settings_gamedata, labels[which], getString(R.string.restart_hint)))
            }
            .setNegativeButton(R.string.close, null)
            .show()
    }

    /** Read config.json's "locales" value (default = all four). */
    private fun readLocales(): String = try {
        ServerConfig.gameDataLocales(this)
    } catch (e: Exception) {
        "ja,en,zh,ko"
    }

    /** Write config.json's "locales" value, replacing it or inserting it if absent. */
    private fun writeLocales(value: String) {
        try {
            ServerConfig.setGameDataLocales(this, value)
        } catch (_: Exception) {
        }
    }

    private fun showAbout() {
        val version = runCatching {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0).versionName
        }.getOrNull()
        AlertDialog.Builder(this)
            .setTitle("${getString(R.string.about_title)} · elichika ${version ?: ""}")
            .setMessage(getString(R.string.about_body))
            .setPositiveButton(R.string.close, null)
            .show()
    }

    private fun readCdnCache(): Boolean? = try {
        ServerConfig.read(filesDir).opt("cdn_cache") as? Boolean
    } catch (e: Exception) {
        null
    }

    private fun setupTabs(selectedTab: Int) {
        val tl = findViewById<TabLayout>(R.id.tabs)
        tabLayout = tl
        tabs.forEach { tl.addTab(tl.newTab().setText(it.title).setTag(it.id)) }
        tl.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showTab(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) = showTab(tab.position)
        })
        val index = selectedTab.coerceIn(tabs.indices)
        tl.getTabAt(index)?.select()
    }

    /** Keep both chrome views stable; only their measured arrangement changes. */
    private fun setupAdaptiveHeader() {
        val header = findViewById<LinearLayout>(R.id.app_header)
        val navigation = requireNotNull(tabLayout)
        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPaddingRelative(header.paddingStart, header.paddingTop, header.paddingEnd, header.paddingBottom)
        }
        // Both groups share the same day/night surface, including their gap.
        // The theme's primary color remains the selected-tab accent.
        val surface = MaterialColors.getColor(header, com.google.android.material.R.attr.colorSurface)
        header.setBackgroundColor(surface)
        controls.setBackgroundColor(surface)
        navigation.setBackgroundColor(surface)
        val originalControls = (0 until header.childCount).map(header::getChildAt)
        header.removeAllViews()
        originalControls.forEach { controls.addView(it) }
        (navigation.parent as ViewGroup).removeView(navigation)
        header.setPadding(0, 0, 0, 0)
        header.orientation = LinearLayout.VERTICAL
        header.gravity = Gravity.CENTER_VERTICAL
        header.addView(controls, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        header.addView(navigation, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        toggle.minimumHeight = maxOf(toggle.minimumHeight, headerDp(44))
        navigation.minimumHeight = maxOf(navigation.minimumHeight, headerDp(44))
        val strip = navigation.getChildAt(0) as? ViewGroup
        strip?.let { group ->
            for (index in 0 until group.childCount) {
                val tab = group.getChildAt(index)
                tab.minimumHeight = maxOf(tab.minimumHeight, headerDp(44))
            }
        }
        adaptiveHeader = header
        serverControls = controls
        headerLayoutObserver = ViewTreeObserver.OnGlobalLayoutListener { scheduleHeaderReflow() }
            .also { header.viewTreeObserver.addOnGlobalLayoutListener(it) }
        scheduleHeaderReflow()
    }

    private fun headerDp(value: Int): Int = ceil(value * resources.displayMetrics.density.toDouble()).toInt()

    private fun horizontalMargins(view: View): Int =
        (view.layoutParams as? ViewGroup.MarginLayoutParams)?.let { it.leftMargin + it.rightMargin } ?: 0

    private fun naturalHeaderTextWidth(view: TextView): Int {
        val text = view.transformationMethod?.getTransformation(view.text, view) ?: view.text
        val label = ceil(Layout.getDesiredWidth(text, view.paint).toDouble()).toInt() +
            view.compoundPaddingLeft + view.compoundPaddingRight
        val emMinimum = if (view.minEms > 0) view.minEms * view.lineHeight else 0
        return maxOf(label, view.minimumWidth, view.minWidth.coerceAtLeast(0), emMinimum,
            view.background?.minimumWidth ?: 0)
    }

    private fun headerTextViews(view: View): Sequence<TextView> = sequence {
        if (view is TextView && view.visibility != View.GONE) yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(headerTextViews(view.getChildAt(index)))
    }

    private fun naturalTabWidth(tab: View): Int {
        val label = headerTextViews(tab).firstOrNull { it.text.isNotEmpty() }
            ?: return maxOf(headerDp(44), tab.minimumWidth, tab.measuredWidth)
        var width = naturalHeaderTextWidth(label) + horizontalMargins(label)
        var ancestor = label.parent
        while (ancestor is View && ancestor !== tab) {
            width += ancestor.paddingLeft + ancestor.paddingRight + horizontalMargins(ancestor)
            ancestor = (ancestor as View).parent
        }
        return maxOf(headerDp(44), tab.minimumWidth,
            width + tab.paddingLeft + tab.paddingRight) + horizontalMargins(tab)
    }

    private fun scheduleHeaderReflow() {
        val header = adaptiveHeader ?: return
        if (headerReflowPending || headerDisposed) return
        headerReflowPending = true
        header.postOnAnimation {
            headerReflowPending = false
            if (headerDisposed || isFinishing || isDestroyed) return@postOnAnimation
            val navigation = tabLayout ?: return@postOnAnimation
            val controls = serverControls ?: return@postOnAnimation
            // ViewerFullscreen owns visibility. A resize must never restore or
            // rearrange hidden chrome while its WebView fills the window.
            if (header.visibility != View.VISIBLE || navigation.visibility != View.VISIBLE || header.width <= 0) return@postOnAnimation
            val strip = navigation.getChildAt(0) as? ViewGroup ?: return@postOnAnimation
            if (strip.childCount != tabs.size) return@postOnAnimation
            val controlsWidth = controls.paddingLeft + controls.paddingRight +
                (0 until controls.childCount).sumOf { index ->
                    val child = controls.getChildAt(index)
                    if (child.visibility == View.GONE) 0 else {
                        val width = if (child is TextView) naturalHeaderTextWidth(child)
                            else maxOf(child.layoutParams.width.coerceAtLeast(0), child.minimumWidth,
                                child.background?.minimumWidth ?: 0)
                        width + horizontalMargins(child)
                    }
                }
            val tabsWidth = navigation.paddingLeft + navigation.paddingRight + strip.paddingLeft + strip.paddingRight +
                (0 until strip.childCount).sumOf { naturalTabWidth(strip.getChildAt(it)) }
            val gap = headerDp(8)
            val fits = controlsWidth + gap + tabsWidth <= header.width - header.paddingLeft - header.paddingRight
            if (fits == inlineHeader) return@postOnAnimation
            inlineHeader = fits
            header.orientation = if (fits) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
            // Keep the whole tab group at the end of a wide header. The server
            // row absorbs spare width as its status and progress change.
            controls.layoutParams = LinearLayout.LayoutParams(
                if (fits) 0 else ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, if (fits) 1f else 0f)
            statusText.layoutParams = (statusText.layoutParams as LinearLayout.LayoutParams).apply {
                width = ViewGroup.LayoutParams.WRAP_CONTENT
                weight = 1f
            }
            navigation.layoutParams = LinearLayout.LayoutParams(
                if (fits) ViewGroup.LayoutParams.WRAP_CONTENT else ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                marginStart = if (fits) gap else 0
            }
        }
    }

    private fun effectiveTabUrl(tab: Tab): String? {
        if (!tab.managementPage) return tab.url
        val path = tab.url?.let { Uri.parse(it).path } ?: return null
        val base = if (Bus.serverRunning || Bus.serverStarting) {
            if (!Bus.serverReady) return null
            runCatching {
                ServerReadiness.endpoint(ServerConfig.read(filesDir).optString("server_address", "0.0.0.0:8080"))
                    ?.let { "${it.protocol}://${it.authority}" }
            }.getOrNull()
        } else ManagementServer.url()?.trimEnd('/')
        return base?.let { it + path }
    }

    private fun sameWebOrigin(first: String?, second: String): Boolean {
        if (first == null) return false
        val a = Uri.parse(first)
        val b = Uri.parse(second)
        return a.scheme == b.scheme && a.encodedAuthority == b.encodedAuthority
    }

    private fun updateManagementOverlay() {
        val failed = ManagementServer.hasError() || PyServers.hasPreparationError()
        val preparing = ManagementServer.isPreparing() || PyServers.isPreparing() || Bus.serverStarting || Bus.serverRunning
        val cause = ManagementServer.errorMessage()
        offlineMessage.text = getString(if (failed) R.string.management_prepare_failed else R.string.management_preparing) +
            (cause?.let { "\n\n$it" } ?: "")
        offlineAction.setText(R.string.tools_retry)
        offlineAction.isEnabled = failed && !preparing
        offlineAction.setOnClickListener {
            if (!PyServers.isStarted()) PyServers.prepareAsync(applicationContext)
            ManagementServer.requestUi(applicationContext, this, retry = true)
        }
    }

    private fun showTab(index: Int) {
        if (index != currentTab) viewerFullscreen.exit()
        currentTab = index
        val tab = tabs[index]
        if (tab.managementPage) ManagementServer.requestUi(applicationContext, this)
        else ManagementServer.releaseUi(this)
        val targetUrl = effectiveTabUrl(tab)
        // Keep a shared WebView visible while its section changes. A transient
        // GONE/VISIBLE cycle can blur editing fields or suspend its renderer.
        val destination: View = when {
            tab.url == null -> consolePanel
            !(if (tab.managementPage) targetUrl != null else if (tab.localTools) PyServers.isStarted() else Bus.serverReady) -> {
                if ((tab.localTools || tab.managementPage) && !PyServers.isStarted() && !PyServers.isPreparing() && !PyServers.hasPreparationError()) {
                    PyServers.prepareAsync(applicationContext)
                }
                if (tab.managementPage) {
                    updateManagementOverlay()
                } else updateOfflineOverlay(tab.localTools)
                offlineOverlay
            }
            else -> {
                val destinationUrl = targetUrl ?: tab.url!!
                val existed = webViews.containsKey(tab.url)
                val wv = webViewFor(tab.url, tab.section, destinationUrl)
                // Only reload if the previous load actually failed (e.g. the tab was
                // first opened before the server was up). A successful page is left as
                // is, so returning to a tab mid-edit keeps the running job's UI.
                if (existed && (webViewErrored[tab.url] == true ||
                    (tab.managementPage && wv.url != null && !sameWebOrigin(wv.url, destinationUrl)) ||
                    (tab.section != null && !AssetNavigationBridge.isEmbeddedDocument(Uri.parse(wv.url ?: ""))))) {
                    wv.loadUrl(documentUrl(destinationUrl, tab.section))
                } else if (tab.section != null) assetNavigation.showSection(wv, tab.section)
                wv
            }
        }
        for (i in 0 until content.childCount) {
            val child = content.getChildAt(i)
            child.visibility = if (child === destination) View.VISIBLE else View.GONE
        }
    }

    private fun documentUrl(url: String, section: String?): String =
        if (section == null) url else "$url#$section"

    private fun onAssetSection(view: WebView, section: String, ready: Boolean) {
        val current = tabs[currentTab]
        if (current.section == null || webViews[webToolsUrl] !== view || view.visibility != View.VISIBLE) return
        if (ready) {
            assetNavigation.showSection(view, current.section)
        } else {
            val target = tabs.indexOfFirst { it.section == section }
            if (target >= 0 && target != currentTab) tabLayout?.getTabAt(target)?.select()
        }
    }

    private fun webViewFor(url: String, section: String? = null, initialUrl: String = url): WebView {
        val management = tabs.any { it.url == url && it.managementPage }
        return webViews.getOrPut(url) {
            WebView(this).apply {
                layoutParams = FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT
                )
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                // Follow the system light/dark theme. With the WebUIs declaring
                // `color-scheme: light dark`, the WebView uses their own light/dark
                // styles per the system setting instead of force-darkening.
                if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
                    WebSettingsCompat.setAlgorithmicDarkeningAllowed(settings, true)
                }
                if (url == webToolsUrl) {
                    // The trusted local editor schedules timeline voice/music
                    // after Play, often after WebView's short gesture window.
                    settings.mediaPlaybackRequiresUserGesture = false
                    viewerFullscreen.attach(this)
                    assetNavigation.attach(this)
                }
                // Keep all navigation (links, form submits) inside the WebView instead
                // of handing it to the system browser (Chrome), which is the default
                // when no WebViewClient is set. Also track main-frame load failures so
                // showTab() only reloads tabs that errored (see webViewErrored).
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: android.webkit.WebResourceRequest): Boolean =
                        assetNavigation.shouldOverride(view, request) || viewerFullscreen.shouldOverride(view, request)

                    override fun onPageStarted(view: WebView?, u: String?, favicon: android.graphics.Bitmap?) {
                        if (view != null) {
                            viewerFullscreen.onPageStarted(view)
                            assetNavigation.onPageStarted(view)
                        }
                        if (u != null && (management || u.startsWith(url))) webViewErrored[url] = false
                    }
                    override fun onPageFinished(view: WebView?, u: String?) {
                        if (view != null) {
                            viewerFullscreen.onPageFinished(view)
                            assetNavigation.onPageFinished(view)
                            tabs[currentTab].takeIf { it.url == url }?.section?.let {
                                assetNavigation.showSection(view, it)
                            }
                        }
                    }
                    override fun onReceivedError(
                        view: WebView?,
                        request: android.webkit.WebResourceRequest?,
                        error: android.webkit.WebResourceError?,
                    ) {
                        if (request?.isForMainFrame == true) webViewErrored[url] = true
                    }
                }
                content.addView(this)
                val state = savedWebViews.remove(url)
                if (state == null || restoreState(state) == null || (management && !sameWebOrigin(this.url, initialUrl))) {
                    loadUrl(documentUrl(initialUrl, section))
                }
            }
        }
    }

    private fun setupActions() {
        val normalRow = consolePanel.findViewById<android.widget.LinearLayout>(R.id.actions_row)
        val advRow = consolePanel.findViewById<android.widget.LinearLayout>(R.id.advanced_row)
        val advScroll = consolePanel.findViewById<View>(R.id.advanced_scroll)
        val advToggle = consolePanel.findViewById<Button>(R.id.btn_advanced)
        var hasAdvanced = false
        var lastGroup = ""
        var normalGrid: ConsoleActionGrid? = null
        val advancedGrid = actionGrid(advRow)
        for (a in loadActions()) {
            val advanced = a.optBoolean("advanced", false)
            // Headers remain separate while each group's existing buttons reflow
            // from one to three columns as the actual content width changes.
            if (!advanced) {
                val g = a.optString("group")
                if (normalGrid == null || g != lastGroup) {
                    lastGroup = g
                    if (g.isNotEmpty()) normalRow.addView(groupHeader(g))
                    normalGrid = actionGrid(normalRow)
                }
            }
            val b = Button(this)
            b.text = actionLabel(a)
            b.tag = a.optString("id")
            b.isAllCaps = false
            b.setSingleLine(false)
            b.maxLines = Int.MAX_VALUE
            b.ellipsize = null
            b.minimumHeight = maxOf(b.minimumHeight,
                resources.getDimensionPixelSize(R.dimen.console_action_min_touch_height))
            b.gravity = Gravity.START or Gravity.CENTER_VERTICAL
            b.setPadding((16 * resources.displayMetrics.density).toInt(),
                b.paddingTop, (16 * resources.displayMetrics.density).toInt(), b.paddingBottom)
            b.layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            b.setOnClickListener { runAction(a) }
            if (advanced) {
                advancedGrid.addView(b); hasAdvanced = true
            } else {
                normalGrid!!.addView(b)
            }
            if (a.optString("id") == "cdn_cache_toggle") cdnButton = b
        }
        refreshCdnLabel()
        if (hasAdvanced) {
            fun updateAdvanced() {
                advScroll.visibility = if (advancedExpanded) View.VISIBLE else View.GONE
                advToggle.setText(if (advancedExpanded) R.string.hide_advanced else R.string.show_advanced)
            }
            updateAdvanced()
            advToggle.setOnClickListener { advancedExpanded = !advancedExpanded; updateAdvanced() }
        } else {
            advToggle.visibility = View.GONE
        }
    }

    private fun actionGrid(parent: LinearLayout): ConsoleActionGrid =
        ConsoleActionGrid(this).also { grid ->
            parent.addView(grid, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        }

    private fun groupHeader(resName: String): TextView {
        val tv = TextView(this)
        val resId = resources.getIdentifier(resName, "string", packageName)
        tv.text = if (resId != 0) getString(resId) else resName
        tv.textSize = 14f
        tv.setTypeface(tv.typeface, android.graphics.Typeface.BOLD)
        ViewCompat.setAccessibilityHeading(tv, true)
        val d = resources.displayMetrics.density
        tv.setPadding((4 * d).toInt(), (12 * d).toInt(), (4 * d).toInt(), (4 * d).toInt())
        tv.gravity = Gravity.CENTER_VERTICAL
        tv.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        return tv
    }

    private fun runAction(a: JSONObject) {
        when (a.optString("type")) {
            "url" -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(a.optString("url"))))
            "binary" -> confirmAndRunBinary(a)
            "import_zip" -> pickAddon.launch(arrayOf("application/zip", "application/octet-stream", "*/*"))
            "settings" -> showSettings()
            "about" -> showAbout()
            "guide" -> showGuide()
            "reset_server" -> confirmResetServer()
            else -> Bus.log("[action] unknown action type: ${a.optString("id")}")
        }
    }

    /** Confirm expensive/destructive actions (big downloads, or stopping a running
     *  server) before launching; run others straight away. */
    private fun confirmAndRunBinary(a: JSONObject) {
        val id = a.optString("id")
        // The full archive download lets you pick a region (GL / JP / Both).
        if (id == "download_archive") { confirmDownloadArchive(a); return }
        val stops = a.optBoolean("stop_server", true)
        val isBigDownload = id == "download_packs"
        if (!isBigDownload && !(stops && Bus.serverRunning)) { runBinary(a); return }
        val msg = buildString {
            when (id) {
                "download_archive" -> append(getString(R.string.confirm_download_archive))
                "download_packs" -> append(getString(R.string.confirm_download_packs))
            }
            if (stops && Bus.serverRunning) {
                if (isNotEmpty()) append("\n\n")
                append(getString(R.string.confirm_stops_server))
            }
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_title)
            .setMessage(msg)
            .setPositiveButton(R.string.confirm_continue) { _, _ -> runBinary(a) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    /**
     * "Reset server": removes every installed mod by restoring the bundled vanilla
     * game data, and resets all accounts (logins kept). Destructive and cannot be
     * undone, so it takes a two-step confirmation before anything runs.
     */
    private fun confirmResetServer() {
        AlertDialog.Builder(this)
            .setTitle(R.string.reset_server_title)
            .setMessage(R.string.reset_server_msg)
            .setPositiveButton(R.string.confirm_continue) { _, _ ->
                AlertDialog.Builder(this)
                    .setTitle(R.string.reset_server_title)
                    .setMessage(R.string.reset_server_msg2)
                    .setPositiveButton(R.string.reset_server_go) { _, _ ->
                        ServerService.resetServer(this)
                    }
                    .setNegativeButton(R.string.cancel, null)
                    .show()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun runBinary(a: JSONObject) {
        val argsArr = a.optJSONArray("args") ?: return
        val args = (0 until argsArr.length()).map { argsArr.getString(it) }
        ServerService.runAction(this, args, a.optBoolean("stop_server", true))
    }

    /** Full archive download: pick a region, then run download_archive with it. */
    private fun confirmDownloadArchive(a: JSONObject) {
        val labels = arrayOf(
            getString(R.string.region_gl),
            getString(R.string.region_jp),
            getString(R.string.region_both),
        )
        val regions = arrayOf("gl", "jp", "both")
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_download_archive) // Wi-Fi recommendation
            .setItems(labels) { _, which ->
                ServerService.runAction(
                    this, listOf("download_archive", regions[which]),
                    a.optBoolean("stop_server", true))
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun loadActions(): List<JSONObject> {
        return try {
            val json = assets.open("actions.json").bufferedReader().use { it.readText() }
            val arr = JSONObject(json).getJSONArray("actions")
            (0 until arr.length()).map { arr.getJSONObject(it) }
        } catch (e: Exception) {
            Bus.log(getString(R.string.log_actions_load_failed, e.message ?: ""))
            emptyList()
        }
    }

    private fun importAddon(uri: Uri) {
        try {
            val name = queryName(uri) ?: "addon_${System.currentTimeMillis()}.zip"
            val dir = File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                "sukusta/addons"
            ).apply { mkdirs() }
            val out = File(dir, name)
            contentResolver.openInputStream(uri)?.use { input ->
                out.outputStream().use { input.copyTo(it) }
            }
            Bus.log(getString(R.string.log_import_ok, out.absolutePath))
            Toast.makeText(this, R.string.toast_import_ok, Toast.LENGTH_LONG).show()
        } catch (e: Exception) {
            Bus.log(getString(R.string.log_import_failed, e.message ?: ""))
        }
    }

    private fun queryName(uri: Uri): String? {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (i >= 0) return c.getString(i)
            }
        }
        return null
    }

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    /**
     * The pack cache + sukusta tree live in the shared Download/ folder (like Termux),
     * which on Android 11+ requires the "All files access" special permission. Prompt
     * the user to grant it in Settings; on Android 10 fall back to the legacy runtime
     * WRITE permission.
     */
    private fun ensureStorageAccess() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (Environment.isExternalStorageManager()) return
            AlertDialog.Builder(this)
                .setTitle(R.string.perm_title)
                .setMessage(R.string.perm_msg)
                .setPositiveButton(R.string.perm_open) { _, _ ->
                    val pkg = Uri.parse("package:$packageName")
                    val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, pkg)
                    try {
                        startActivity(intent)
                    } catch (e: Exception) {
                        startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                    }
                }
                .setNegativeButton(R.string.perm_later, null)
                .show()
        } else if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), 2)
        }
    }

    companion object {
        internal const val TAB_CONSOLE = "console"
        internal const val TAB_ASSET_TOOLS = "asset-tools"
        internal const val TAB_MODEL_VIEWER = "model-viewer"
    }
}
