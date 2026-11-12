package com.tagundo.elichika

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URI
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Run separately after the existing no-Go viewer suite; the host then force-stops the app. */
@RunWith(AndroidJUnit4::class)
class OfflineManagementWebViewTest {
    @Test
    fun settingsAndUserPanelsOpenWithGameServerStopped() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        val evidence = File(context.filesDir, "offline-management-native.json")
        val report = JSONObject().put("status", "RUNNING")
        var activity: MainActivity? = null
        try {
            requireHarnessPermissions(context)
            assertGameFlagsOff()
            val initialPids = realGoPids()
            assertEquals("This separate test must begin without any old Go children", emptyList<Int>(), initialPids)
            assertEquals("Standalone preparation must not eagerly start management", null, ManagementServer.currentPid())
            report.put("initialGoPids", JSONArray(initialPids))
                .put("pythonToolsInitiallyStarted", PyServers.isStarted())
            preferences.edit().putBoolean("seen_guide", true).commit()
            val launched = instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ) as MainActivity
            activity = launched
            instrumentation.runOnMainSync { NativeTabsQa.tab(launched, "server").select() }
            val settingsView = waitForWebView(launched)
            val settings = waitForLoginDom(settingsView, "admin_password", "/webui/admin/login")
            assertTrue("Management tabs must prepare the real embedded tools", PyServers.isStarted())
            val base = ManagementServer.url() ?: throw AssertionError("The management address was not published")
            val parsed = URI(base)
            assertEquals("http", parsed.scheme)
            assertEquals("127.0.0.1", parsed.host)
            assertTrue("Management uses its own ephemeral loopback port", parsed.port in 1..65535)
            val gamePort = ServerReadiness.endpoint(ServerConfig.read(context.filesDir)
                .optString("server_address", "0.0.0.0:8080"))?.port
            assertFalse("The management listener must not take the configured game port", parsed.port == gamePort)
            assertEquals(base, settings.getString("origin"))
            val owned = ownedManagementProcess(context)
            report.put("management", JSONObject().put("url", base).put("host", parsed.host).put("port", parsed.port))
                .put("ownedProcess", owned)
            val settingsNavigation = assertMenuRoundTripsRetainSession(
                launched, "server", settingsView, "admin_password", base, owned.getInt("pid"))
            val settingsImage = screenshot(launched, "offline-management-settings.png")

            instrumentation.runOnMainSync { NativeTabsQa.tab(launched, "account").select() }
            val userView = waitForWebView(launched)
            val user = waitForLoginDom(userView, "user_password", "/webui/user/login")
            assertEquals(base, user.getString("origin"))
            assertEquals("Both tabs must reuse the same owned management process",
                owned.getInt("pid"), ownedManagementProcess(context).getInt("pid"))
            val userNavigation = assertMenuRoundTripsRetainSession(
                launched, "account", userView, "user_password", base, owned.getInt("pid"))
            val userImage = screenshot(launched, "offline-management-user.png")
            val excluded = JSONObject()
            for (path in listOf("/login/login", "/api/bootstrap", "/static/offline-fixture.pack")) {
                val status = readStatus(base + path)
                assertEquals("The offline listener must not expose game/CDN routes: $path", 404, status)
                excluded.put(path, status)
            }
            assertGameFlagsOff()
            report.put("panels", JSONObject()
                .put("settings", settings.put("tabId", "server").put("loginFormLoaded", true))
                .put("user", user.put("tabId", "account").put("loginFormLoaded", true)))
                .put("screenshots", JSONObject().put("settings", settingsImage).put("user", userImage))
                .put("menuRoundTrips", JSONObject().put("settings", settingsNavigation).put("user", userNavigation))
                .put("excludedRoutes", excluded)
                .put("checks", JSONObject().put("gameFlagsStayedOff", true)
                    .put("onlyOwnedManagementProcess", true).put("loopbackEphemeral", true)
                    .put("gameApiExcluded", true).put("pythonToolsPrepared", true)
                    .put("noUiWriteRequests", true).put("menuRoundTripsKeepOwnedProcess", true)
                    .put("menuRoundTripsKeepDocumentAndDraft", true))
                .put("hostCleanupRequired", "Force-stop app after this separate instrumentation and assert ALL Go PIDs are gone")
                .put("status", "PASS")
            evidence.writeText(report.toString(2))
            println("OFFLINE_MANAGEMENT_NATIVE_REPORT=$report")
        } catch (failure: Throwable) {
            report.put("status", "FAIL").put("error", failure.message?.take(1000) ?: failure.javaClass.simpleName)
            evidence.writeText(report.toString(2))
            throw failure
        } finally {
            instrumentation.runOnMainSync { activity?.finish() }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun requireHarnessPermissions(context: Context) {
        // The existing device harness already grants these. Revoking a newly
        // granted permission could kill instrumentation, so this read-only test
        // checks that setup without changing the operator's permission choices.
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.Q) permissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        for (permission in permissions) {
            assertEquals("The device harness must grant $permission", PackageManager.PERMISSION_GRANTED,
                context.checkSelfPermission(permission))
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            assertTrue("The device harness must grant All files access", Environment.isExternalStorageManager())
        }
    }

    private fun assertGameFlagsOff() {
        assertFalse("Opening management must leave the game server stopped", Bus.serverRunning)
        assertFalse("Opening management must not queue a game server start", Bus.serverStarting)
        assertFalse("The game HTTP listener must stay unready", Bus.serverReady)
    }

    private fun assertMenuRoundTripsRetainSession(activity: MainActivity, panel: String, original: WebView,
                                                 inputId: String, origin: String, pid: Int): JSONArray {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val marker = "menu-roundtrip-$panel-${System.nanoTime()}"
        val before = evaluate(original, "var input=document.getElementById(${JSONObject.quote(inputId)});" +
            "var old=input.value;input.value=${JSONObject.quote(marker)};" +
            "window.__managementMenuRoundTrip=${JSONObject.quote(marker)};return JSON.stringify({value:old});")
        val witnesses = JSONArray()
        try {
            for (away in listOf("console", "server-content", "asset-tools", "model-viewer")) {
                instrumentation.runOnMainSync { NativeTabsQa.tab(activity, away).select() }
                instrumentation.waitForIdleSync()
                assertGameFlagsOff()
                assertEquals("Switching to $away must retain the management origin", origin, ManagementServer.url())
                assertEquals("Switching to $away must not stop the owned management process", pid, ManagementServer.currentPid())
                assertFalse("Menu changes must not restart management preparation", ManagementServer.isPreparing())
                instrumentation.runOnMainSync { NativeTabsQa.tab(activity, panel).select() }
                val returned = waitForWebView(activity)
                assertSame("Returning from $away must preserve the $panel WebView", original, returned)
                val state = evaluate(returned, "return JSON.stringify({origin:location.origin," +
                    "draft:document.getElementById(${JSONObject.quote(inputId)}).value," +
                    "documentMarker:window.__managementMenuRoundTrip});")
                assertEquals("Returning from $away must retain the origin", origin, state.getString("origin"))
                assertEquals("Returning from $away must retain the unsent form input", marker, state.getString("draft"))
                assertEquals("Returning from $away must not reload the document", marker, state.getString("documentMarker"))
                assertEquals("Returning from $away must retain the same sole owned process", pid,
                    ownedManagementProcess(activity).getInt("pid"))
                witnesses.put(JSONObject().put("viaTab", away).put("sameOwnedPid", true)
                    .put("sameOrigin", true).put("sameWebView", true).put("sameDocument", true).put("draftPreserved", true))
            }
            return witnesses
        } finally {
            // Only an unsent test draft is used; no authentication/configuration write is submitted.
            evaluate(original, "document.getElementById(${JSONObject.quote(inputId)}).value=" +
                JSONObject.quote(before.getString("value")) + ";delete window.__managementMenuRoundTrip;return JSON.stringify({restored:true});")
        }
    }

    private fun realGoPids(): List<Int> {
        val process = ProcessBuilder("/system/bin/pidof", "libelichika.so").redirectErrorStream(true).start()
        assertTrue("Process inspection must finish", process.waitFor(5, TimeUnit.SECONDS))
        val output = process.inputStream.bufferedReader().use { it.readText().trim() }
        assertTrue("pidof must report a match or no process", process.exitValue() in 0..1)
        if (process.exitValue() != 0 || output.isEmpty()) return emptyList()
        return output.split(Regex("\\s+")).map { it.toInt() }.sorted()
    }

    private fun ownedManagementProcess(context: Context): JSONObject {
        assertGameFlagsOff()
        val pid = ManagementServer.currentPid() ?: throw AssertionError("Management has no owned live PID")
        val arguments = File("/proc/$pid/cmdline").readBytes().toString(Charsets.UTF_8)
            .split('\u0000').filter { it.isNotEmpty() }
        val expectedBinary = File(context.applicationInfo.nativeLibraryDir, "libelichika.so").absolutePath
        assertEquals("Only the bundled management role may own this PID", listOf(expectedBinary, "management"), arguments)
        val status = File("/proc/$pid/status").readLines()
        val parent = status.single { it.startsWith("PPid:") }.substringAfter(':').trim().toInt()
        assertEquals("The management process must be this app's direct child", android.os.Process.myPid(), parent)
        val all = realGoPids()
        assertEquals("Do not hide unrelated or duplicate Go processes", listOf(pid), all)
        return JSONObject().put("pid", pid).put("ppid", parent).put("argv", JSONArray(arguments))
            .put("allGoPids", JSONArray(all)).put("binaryPath", expectedBinary)
    }

    private fun waitForWebView(activity: MainActivity): WebView {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(600)
        while (System.nanoTime() < deadline) {
            assertGameFlagsOff()
            var view: WebView? = null
            instrumentation.runOnMainSync {
                view = descendants(activity.findViewById(R.id.content))
                    .filterIsInstance<WebView>().firstOrNull { it.visibility == View.VISIBLE }
            }
            view?.let { return it }
            if ((ManagementServer.hasError() && !ManagementServer.isPreparing()) ||
                (PyServers.hasPreparationError() && !PyServers.isPreparing())) {
                throw AssertionError(ManagementServer.errorMessage() ?: "Standalone tool preparation failed")
            }
            Thread.sleep(100)
        }
        throw AssertionError("The management tab did not open its real WebView after standalone preparation")
    }

    private fun waitForLoginDom(view: WebView, inputId: String, path: String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            assertGameFlagsOff()
            last = evaluate(view, "return JSON.stringify({url:location.href,origin:location.origin,path:location.pathname," +
                "ready:document.readyState==='complete',loginForm:!!document.getElementById('login_form')," +
                "passwordInput:!!document.getElementById(" + JSONObject.quote(inputId) + ")," +
                "bodyVisible:!!document.body&&document.body.clientWidth>0&&document.body.clientHeight>0});")
            if (last.optBoolean("ready") && last.optBoolean("loginForm") && last.optBoolean("passwordInput") &&
                last.optBoolean("bodyVisible") && last.optString("path") == path) return last
            Thread.sleep(100)
        }
        throw AssertionError("The real $path login form did not load: $last")
    }

    private fun evaluate(view: WebView, body: String): JSONObject {
        val result = AtomicReference<String>()
        val done = CountDownLatch(1)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            view.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({error:String(e)});}})();") {
                result.set(it)
                done.countDown()
            }
        }
        assertTrue("WebView JavaScript callback must finish", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        return JSONObject(decoded as? String ?: throw AssertionError("The WebView did not return its DOM state"))
    }

    private fun screenshot(activity: MainActivity, name: String): JSONObject {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        Thread.sleep(250)
        instrumentation.runOnMainSync { assertTrue("No system dialog may obscure the page", activity.hasWindowFocus()) }
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
            ?: throw AssertionError("Capture the actual device framebuffer")
        try {
            val image = File(instrumentation.targetContext.filesDir, name)
            image.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
            return JSONObject().put("file", name).put("bytes", image.length())
                .put("width", bitmap.width).put("height", bitmap.height)
        } finally { bitmap.recycle() }
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }

    private fun readStatus(value: String): Int {
        val connection = URL(value).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        return try {
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.instanceFollowRedirects = false
            connection.requestMethod = "GET"
            connection.responseCode
        } finally { connection.disconnect() }
    }
}
