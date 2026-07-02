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
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
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
    private lateinit var logScroll: ScrollView

    // Shown in a web tab when the server isn't running yet (instead of a raw
    // "webpage not available" browser error). Its button starts the server.
    private lateinit var offlineOverlay: View
    private var tabLayout: TabLayout? = null
    private var currentTab = 0
    // True between "start" being tapped and the server reporting it is running, so
    // the UI can show a "starting…" state instead of looking idle.
    private var starting = false

    // Lazily-created WebViews for the three local web UIs.
    private val webViews = HashMap<String, WebView>()
    // Tracks whether each WebView's last main-frame load failed (e.g. opened before
    // the server was up). Only those are reloaded on re-open, so re-opening a tab
    // with a running edit/extraction no longer wipes its live page state.
    private val webViewErrored = HashMap<String, Boolean>()

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
        consolePanel.findViewById<Button>(R.id.btn_share_log).setOnClickListener { shareLog() }
        consolePanel.findViewById<Button>(R.id.btn_clear_log).setOnClickListener { clearLog() }
        content.addView(consolePanel)

        offlineOverlay = buildOfflineOverlay()
        content.addView(offlineOverlay)
        offlineOverlay.visibility = View.GONE

        setupActions()
        setupTabs()
        toggle.setOnClickListener { onToggle() }

        logText.text = Bus.snapshot()
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
        ll.addView(TextView(this).apply {
            text = getString(R.string.offline_msg)
            gravity = Gravity.CENTER
        })
        ll.addView(Button(this).apply {
            text = getString(R.string.start_server)
            isAllCaps = false
            setOnClickListener { startServerUi() }
        })
        return ll
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

    override fun onResume() {
        super.onResume()
        Bus.logListener = { appendLog(it) }
        Bus.stateListener = { updateRunning(it) }
        logText.text = Bus.snapshot()
        updateRunning(Bus.serverRunning)
        refreshCdnLabel()
    }

    override fun onPause() {
        super.onPause()
        Bus.logListener = null
        Bus.stateListener = null
    }

    private fun onToggle() {
        if (Bus.serverRunning || starting) stopServerUi() else startServerUi()
    }

    private fun startServerUi() {
        if (Bus.serverRunning || starting) return
        starting = true
        ServerService.start(this)
        updateRunning(false)  // reflect the "starting…" state immediately
    }

    private fun stopServerUi() {
        starting = false
        ServerService.stop(this)
        updateRunning(false)
    }

    private fun updateRunning(running: Boolean) {
        if (running) starting = false
        toggle.setText(if (running || starting) R.string.stop_server else R.string.start_server)
        statusText.text = when {
            running -> getString(R.string.status_running)
            starting -> getString(R.string.status_starting)
            else -> getString(R.string.status_stopped)
        }
        // If a web tab is showing the offline overlay and the server just came up,
        // swap the overlay for the (now reachable) page.
        if (running && tabs[currentTab].url != null && offlineOverlay.visibility == View.VISIBLE) {
            showTab(currentTab)
        }
    }

    private fun appendLog(line: String) {
        logText.append(line)
        if (!line.endsWith("\n")) logText.append("\n")
        logScroll.post { logScroll.fullScroll(View.FOCUS_DOWN) }
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
        val codes = listOf("auto") + Lang.SUPPORTED
        val labels = arrayOf(getString(R.string.lang_auto), "English", "한국어", "日本語")
        val current = codes.indexOf(Lang.pref(this)).coerceAtLeast(0)
        AlertDialog.Builder(this)
            .setTitle("${getString(R.string.settings_title)} · ${getString(R.string.language)}")
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
        val txt = File(filesDir, "config.json").readText()
        when {
            Regex("\"cdn_cache\"\\s*:\\s*true").containsMatchIn(txt) -> true
            Regex("\"cdn_cache\"\\s*:\\s*false").containsMatchIn(txt) -> false
            else -> null
        }
    } catch (e: Exception) {
        null
    }

    private fun setupTabs() {
        val tl = findViewById<TabLayout>(R.id.tabs)
        tabLayout = tl
        tabs.forEach { tl.addTab(tl.newTab().setText(it.title)) }
        tl.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showTab(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })
        showTab(0)
    }

    private fun showTab(index: Int) {
        currentTab = index
        val tab = tabs[index]
        // Hide everything, then show the selected view (creating WebViews on demand).
        for (i in 0 until content.childCount) content.getChildAt(i).visibility = View.GONE
        when {
            tab.url == null -> consolePanel.visibility = View.VISIBLE
            // Server not up yet: show a friendly overlay with a Start button instead
            // of the WebView's raw "webpage not available" error page.
            !Bus.serverRunning -> offlineOverlay.visibility = View.VISIBLE
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
                loadUrl(url)
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
        val gap = (6 * resources.displayMetrics.density).toInt()
        for (a in loadActions()) {
            val advanced = a.optBoolean("advanced", false)
            // Insert a small caption when the (non-advanced) action group changes,
            // so the scrolling button row reads "Game data · General · Mod pages".
            if (!advanced) {
                val g = a.optString("group")
                if (g.isNotEmpty() && g != lastGroup) {
                    lastGroup = g
                    normalRow.addView(groupHeader(g))
                }
            }
            val b = Button(this)
            b.text = actionLabel(a)
            b.isAllCaps = false
            b.layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { marginEnd = gap }
            b.setOnClickListener { runAction(a) }
            if (advanced) {
                advRow.addView(b); hasAdvanced = true
            } else {
                normalRow.addView(b)
            }
            if (a.optString("id") == "cdn_cache_toggle") cdnButton = b
        }
        refreshCdnLabel()
        if (hasAdvanced) {
            advToggle.setOnClickListener {
                advScroll.visibility = if (advScroll.visibility == View.GONE) View.VISIBLE else View.GONE
            }
        } else {
            advToggle.visibility = View.GONE
        }
    }

    private fun groupHeader(resName: String): TextView {
        val tv = TextView(this)
        val resId = resources.getIdentifier(resName, "string", packageName)
        tv.text = if (resId != 0) getString(resId) else resName
        tv.textSize = 11f
        tv.alpha = 0.6f
        val d = resources.displayMetrics.density
        tv.setPadding((10 * d).toInt(), 0, (4 * d).toInt(), 0)
        tv.gravity = Gravity.CENTER_VERTICAL
        tv.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.MATCH_PARENT)
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
