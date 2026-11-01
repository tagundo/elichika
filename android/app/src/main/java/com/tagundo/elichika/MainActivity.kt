package com.tagundo.elichika

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.OpenableColumns
import android.provider.Settings
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.widget.NestedScrollView
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.google.android.material.tabs.TabLayout
import org.json.JSONObject
import java.io.File

/**
 * Thin shell UI. Everything the user can do is either a service action declared
 * in assets/actions.json (Console tab) or a page served by the Go server / the
 * two Python tool web UIs (the three WebView tabs). No server/tool logic lives
 * here, so new features show up after a rebuild without touching this file.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var content: FrameLayout
    private lateinit var statusText: TextView
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
    // Bus also owns pending-start state, shared across resized/recreated windows.

    // Lazily-created WebViews for the three local web UIs.
    private val webViews = HashMap<String, WebView>()
    // Tracks whether each WebView's last main-frame load failed (e.g. opened before
    // the server was up). Only those are reloaded on re-open, so re-opening a tab
    // with a running edit/extraction no longer wipes its live page state.
    private val webViewErrored = HashMap<String, Boolean>()
    private val savedWebViews = HashMap<String, Bundle>()

    // File picker for addon zips: copies the chosen file into Download/sukusta/addons,
    // where the dev-tools installers pick it up.
    private val pickAddon = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importAddon(uri)
    }

    // the CDN-cache toggle button, relabelled to show the current on/off state.
    private var cdnButton: Button? = null

    private data class Tab(val title: String, val url: String?)

    private val tabs by lazy {
        listOf(
            Tab(getString(R.string.tab_console), null),
            // The server has no /webui/ index — the panels live at /webui/admin/ and
            // /webui/user/. Point at the admin panel (server config, CDN cache, etc.).
            Tab(getString(R.string.tab_webui), "http://127.0.0.1:8080/webui/admin/"),
            Tab(getString(R.string.tab_user), "http://127.0.0.1:8080/webui/user/"),
            Tab(getString(R.string.tab_dev), "http://127.0.0.1:8772/"),
            Tab(getString(R.string.tab_mod), "http://127.0.0.1:8770/"),
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
        toggle = findViewById(R.id.btn_toggle)

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
        setupTabs(savedInstanceState?.getInt("current_tab", 0) ?: 0)
        toggle.setOnClickListener { onToggle() }

        updateRunning(Bus.serverRunning)
        requestNotifications()
        ensureStorageAccess()
        showGuideOnce()
    }

    override fun onBackPressed() {
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
        if (currentTab >= 3 && offlineOverlay.visibility == View.VISIBLE) {
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
        // A split-screen window may be paused while still visible. Keep its status
        // and console subscribed until it is actually stopped.
        Bus.addListener(this, { appendLog(it) }, { updateRunning(it) }, { updateToolsState() })
        if (logExpanded) logText.text = Bus.snapshot()
        updateRunning(Bus.serverRunning)
        updateToolsState()
        refreshCdnLabel()
    }

    override fun onStop() {
        Bus.removeListener(this)
        super.onStop()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("current_tab", currentTab)
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
        Bus.removeListener(this)
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
        toggle.setText(if (running || Bus.serverStarting) R.string.stop_server else R.string.start_server)
        statusText.text = when {
            running -> getString(R.string.status_running)
            Bus.serverStarting -> getString(R.string.status_starting)
            else -> getString(R.string.status_stopped)
        }
        // If a web tab is showing the offline overlay and the server just came up,
        // swap the overlay for the (now reachable) page.
        if ((running || (currentTab >= 3 && PyServers.isStarted())) &&
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
        tabs.forEach { tl.addTab(tl.newTab().setText(it.title)) }
        tl.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showTab(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })
        val index = selectedTab.coerceIn(tabs.indices)
        tl.getTabAt(index)?.select()
        showTab(index)
    }

    private fun showTab(index: Int) {
        currentTab = index
        val tab = tabs[index]
        // Hide everything, then show the selected view (creating WebViews on demand).
        for (i in 0 until content.childCount) content.getChildAt(i).visibility = View.GONE
        when {
            tab.url == null -> consolePanel.visibility = View.VISIBLE
            // The editors prepare independently. Server/account pages retain
            // their Start server action while the local tools show preparation.
            !(if (index >= 3) PyServers.isStarted() else Bus.serverRunning) -> {
                offlineOverlay.visibility = View.VISIBLE
                if (index >= 3 && !PyServers.isPreparing() && !PyServers.hasPreparationError()) {
                    PyServers.prepareAsync(applicationContext)
                }
                updateOfflineOverlay(index >= 3)
            }
            else -> {
                val existed = webViews.containsKey(tab.url)
                val wv = webViewFor(tab.url)
                wv.visibility = View.VISIBLE
                // Only reload if the previous load actually failed (e.g. the tab was
                // first opened before the server was up). A successful page is left as
                // is, so returning to a tab mid-edit keeps the running job's UI.
                if (existed && webViewErrored[tab.url] == true) wv.loadUrl(tab.url)
            }
        }
    }

    private fun webViewFor(url: String): WebView {
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
                // Keep all navigation (links, form submits) inside the WebView instead
                // of handing it to the system browser (Chrome), which is the default
                // when no WebViewClient is set. Also track main-frame load failures so
                // showTab() only reloads tabs that errored (see webViewErrored).
                webViewClient = object : WebViewClient() {
                    override fun onPageStarted(view: WebView?, u: String?, favicon: android.graphics.Bitmap?) {
                        if (u != null && u.startsWith(url)) webViewErrored[url] = false
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
                if (state == null || restoreState(state) == null) loadUrl(url)
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
}
