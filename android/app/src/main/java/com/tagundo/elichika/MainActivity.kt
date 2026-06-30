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
import android.view.View
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
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

    // Lazily-created WebViews for the three local web UIs.
    private val webViews = HashMap<String, WebView>()

    // File picker for addon zips: copies the chosen file into Download/sukusta/addons,
    // where the dev-tools installers pick it up.
    private val pickAddon = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importAddon(uri)
    }

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
        setContentView(R.layout.activity_main)

        content = findViewById(R.id.content)
        statusText = findViewById(R.id.txt_status)
        toggle = findViewById(R.id.btn_toggle)

        consolePanel = layoutInflater.inflate(R.layout.panel_console, content, false)
        logText = consolePanel.findViewById(R.id.log_text)
        logScroll = consolePanel.findViewById(R.id.log_scroll)
        content.addView(consolePanel)

        setupActions()
        setupTabs()
        toggle.setOnClickListener { onToggle() }

        logText.text = Bus.snapshot()
        updateRunning(Bus.serverRunning)
        requestNotifications()
        ensureStorageAccess()
    }

    override fun onResume() {
        super.onResume()
        Bus.logListener = { appendLog(it) }
        Bus.stateListener = { updateRunning(it) }
        logText.text = Bus.snapshot()
        updateRunning(Bus.serverRunning)
    }

    override fun onPause() {
        super.onPause()
        Bus.logListener = null
        Bus.stateListener = null
    }

    private fun onToggle() {
        if (Bus.serverRunning) {
            ServerService.stop(this)
        } else {
            ServerService.start(this)
        }
    }

    private fun updateRunning(running: Boolean) {
        toggle.setText(if (running) R.string.stop_server else R.string.start_server)
        statusText.text = if (running) "● 127.0.0.1:8080" else "○ 중지됨"
    }

    private fun appendLog(line: String) {
        logText.append(line)
        if (!line.endsWith("\n")) logText.append("\n")
        logScroll.post { logScroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun setupTabs() {
        val tl = findViewById<TabLayout>(R.id.tabs)
        tabs.forEach { tl.addTab(tl.newTab().setText(it.title)) }
        tl.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showTab(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })
        showTab(0)
    }

    private fun showTab(index: Int) {
        val tab = tabs[index]
        // Hide everything, then show the selected view (creating WebViews on demand).
        for (i in 0 until content.childCount) content.getChildAt(i).visibility = View.GONE
        if (tab.url == null) {
            consolePanel.visibility = View.VISIBLE
        } else {
            val existed = webViews.containsKey(tab.url)
            val wv = webViewFor(tab.url)
            wv.visibility = View.VISIBLE
            // Reload on re-open: a tab first viewed before the server was up cached a
            // connection error; reloading now that it may be running recovers it.
            if (existed) wv.loadUrl(tab.url)
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
                // Keep all navigation (links, form submits) inside the WebView instead
                // of handing it to the system browser (Chrome), which is the default
                // when no WebViewClient is set.
                webViewClient = WebViewClient()
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
        for (a in loadActions()) {
            val b = Button(this)
            b.text = a.optString("label", a.optString("id"))
            b.setOnClickListener { runAction(a) }
            if (a.optBoolean("advanced", false)) {
                advRow.addView(b); hasAdvanced = true
            } else {
                normalRow.addView(b)
            }
        }
        if (hasAdvanced) {
            advToggle.setOnClickListener {
                advScroll.visibility = if (advScroll.visibility == View.GONE) View.VISIBLE else View.GONE
            }
        } else {
            advToggle.visibility = View.GONE
        }
    }

    private fun runAction(a: JSONObject) {
        when (a.optString("type")) {
            "url" -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(a.optString("url"))))
            "binary" -> {
                val argsArr = a.optJSONArray("args") ?: return
                val args = (0 until argsArr.length()).map { argsArr.getString(it) }
                ServerService.runAction(this, args, a.optBoolean("stop_server", true))
            }
            "import_zip" -> pickAddon.launch(arrayOf("application/zip", "application/octet-stream", "*/*"))
            else -> Bus.log("[action] 알 수 없는 액션 유형: ${a.optString("id")}")
        }
    }

    private fun loadActions(): List<JSONObject> {
        return try {
            val json = assets.open("actions.json").bufferedReader().use { it.readText() }
            val arr = JSONObject(json).getJSONArray("actions")
            (0 until arr.length()).map { arr.getJSONObject(it) }
        } catch (e: Exception) {
            Bus.log("[action] actions.json 로드 실패: ${e.message}")
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
            Bus.log("[가져오기] ${out.absolutePath} — '개발 도구' 탭에서 설치하세요.")
        } catch (e: Exception) {
            Bus.log("[가져오기] 실패: ${e.message}")
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
