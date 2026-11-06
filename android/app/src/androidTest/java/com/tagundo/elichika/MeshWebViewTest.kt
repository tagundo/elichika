package com.tagundo.elichika

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.view.KeyEvent
import android.webkit.WebView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.tabs.TabLayout
import org.json.JSONObject
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Exercise the bundled JS in the device's real WebView, including older providers. */
@RunWith(AndroidJUnit4::class)
class MeshWebViewTest {
    @Test
    fun meshEditorLoadsAndWorksInTheInstalledWebView() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        // Instrumentation runs this test on a worker. Do not copy the payload or
        // initialize Chaquopy on the main thread just to open the editing page.
        AssetInstaller.install(context) {}
        PyServers.ensureStarted(context, context.filesDir)
        assertTrue("Embedded tool servers must start", PyServers.isStarted())
        val models = waitForTools().getJSONObject("roots").getString("models")
        val preferences = context.getSharedPreferences("elichika", Context.MODE_PRIVATE)
        val hadGuide = preferences.contains("seen_guide")
        val seenGuide = preferences.getBoolean("seen_guide", false)
        preferences.edit().putBoolean("seen_guide", true).commit()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        val activity = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ) as MainActivity
        try {
            lateinit var webView: WebView
            instrumentation.runOnMainSync {
                activity.findViewById<TabLayout>(R.id.tabs).getTabAt(4)!!.select()
                webView = descendants(activity.findViewById(R.id.content))
                    .filterIsInstance<WebView>().first { it.visibility == View.VISIBLE }
            }
            waitForDom(webView, "Mesh Baker tool button") {
                "var b=document.querySelector('#tool-list button[data-id=\"mesh_baker\"]');" +
                    "return JSON.stringify({ok:!!b,ready:document.readyState,title:document.title});"
            }
            val requireWideUi = InstrumentationRegistry.getArguments().getString("requireWideUi") == "true"
            val viewport = waitForDom(webView, "the actual Android WebView viewport") {
                "return JSON.stringify({ok:document.readyState==='complete'" + (if (requireWideUi) "&&innerWidth>=1200" else "") +
                    ",width:innerWidth,height:innerHeight,dpr:devicePixelRatio,coarse:matchMedia('(pointer:coarse)').matches,desktop:document.documentElement.classList.contains('elichika-desktop')});"
            }
            assertFalse("Android must keep its touch UI without the macOS desktop class", viewport.getBoolean("desktop"))
            if (requireWideUi) assertTrue("The wide pass must use a real 1200+ CSS-pixel WebView", viewport.getInt("width") >= 1200)
            evaluate(webView, "document.querySelector('#tool-list button[data-id=\"mesh_baker\"]').click();return JSON.stringify({ok:true});")
            val editor = waitForDom(webView, "body-part controls and visible Save button") {
                """
                var buttons=document.querySelectorAll('#tool-form .body-part-choice');
                var expert=document.querySelector('#tool-form .expert-options');
                var save=document.querySelector('#tool-form .run-btn');
                var waist=document.getElementById('part-tab-torso');
                if(window.innerWidth>=1200&&save)save.scrollIntoView({block:'center'});
                var rect=save?save.getBoundingClientRect():null;
                var hit=rect?document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2):null;
                var visible=!!rect&&rect.width>=44&&rect.height>=44&&rect.top>=0&&
                  rect.bottom<=window.innerHeight+1&&rect.left>=0&&rect.right<=window.innerWidth+1;
                return JSON.stringify({ok:buttons.length===8&&!!waist&&!!expert&&!!save&&visible&&
                  !save.disabled&&(hit===save||save.contains(hit)),parts:buttons.length,
                  expertOpen:expert?expert.open:true,targetSpec:!!document.querySelector('[data-name="target_spec"]'),
                  saveVisible:visible,saveEnabled:!!save&&!save.disabled});
                """.trimIndent()
            }
            assertEquals(8, editor.getInt("parts"))
            assertFalse("Expert controls should start closed", editor.getBoolean("expertOpen"))
            assertFalse("The beginner editor must not expose a target-spec text box", editor.getBoolean("targetSpec"))
            assertTrue(editor.getBoolean("saveVisible"))
            assertTrue(editor.getBoolean("saveEnabled"))
            evaluate(webView, "document.getElementById('part-tab-torso').click();return JSON.stringify({ok:true});")
            waitForDom(webView, "waist selection event handler") {
                "return JSON.stringify({ok:document.getElementById('part-tab-torso').getAttribute('aria-selected')==='true'" +
                    "&&!document.getElementById('part-card-torso').hidden});"
            }
            // A fresh official install need not have extracted any models yet.
            // Check an existing library without creating or modifying user folders.
            val modelDirectory = File(models)
            if (modelDirectory.isDirectory) {
                evaluate(webView, "document.querySelector('#tool-form [data-name=\"in_path\"]').parentNode.querySelector('button').click();return JSON.stringify({ok:true});")
                waitForDom(webView, "model-folder browser") {
                    "var picker=document.getElementById('picker');var path=document.getElementById('picker-crumb').textContent;" +
                        "return JSON.stringify({ok:!picker.classList.contains('hidden')&&path===" + JSONObject.quote(modelDirectory.canonicalPath) + ",path:path});"
                }
                evaluate(webView, "document.getElementById('picker-cancel').click();return JSON.stringify({ok:true});")
            }
            editor.put("existingModelFolderChecked", modelDirectory.isDirectory)
            editor.put("actualViewport", viewport)
            if (requireWideUi) editor.put("wideTools", exerciseWideTools(webView))
            println("MESH_WEBVIEW_REPORT=" + editor.toString())
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
            preferences.edit().apply {
                if (hadGuide) putBoolean("seen_guide", seenGuide) else remove("seen_guide")
            }.commit()
        }
    }

    private fun exerciseWideTools(webView: WebView): JSONObject {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val directory = File(context.cacheDir, "wide-tools-qa-${System.nanoTime()}")
        assertTrue("Create only this test's private synthetic output directory", directory.mkdir())
        val source = File(directory, "neutral-rig.unity")
        val fixture = instrumentation.context.assets.open("viewer_rig.unity").use { it.readBytes() }
        source.writeBytes(fixture)
        try {
            assertFalse("Wide asset tools must leave the game server stopped", Bus.serverRunning || Bus.serverStarting)
            evaluate(webView, "var form=document.getElementById('tool-form');" +
                "var source=form.querySelector('[data-name=\"in_path\"]'),output=form.querySelector('[data-name=\"out_dir\"]');" +
                "source.value=" + JSONObject.quote(source.absolutePath) + ";output.value=" + JSONObject.quote(directory.absolutePath) + ";" +
                "source.dispatchEvent(new Event('change',{bubbles:true}));output.dispatchEvent(new Event('change',{bubbles:true}));" +
                "document.getElementById('part-tab-head').click();return JSON.stringify({ok:true});")
            waitForDom(webView, "the neutral Unity model's actual supported head control") {
                "var card=document.getElementById('part-card-head');return JSON.stringify({ok:!card.disabled&&!card.hidden});"
            }
            val before = evaluate(webView, "var amount=document.querySelector('#part-card-head input[type=number]');" +
                "amount.value='115';amount.dispatchEvent(new Event('change',{bubbles:true}));" +
                "var save=document.querySelector('#tool-form .run-btn');save.scrollIntoView({block:'center'});" +
                "var rect=save.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);" +
                "if(save.disabled||rect.width<44||rect.height<44||rect.top<0||rect.bottom>innerHeight+1||!(hit===save||save.contains(hit)))" +
                "throw new Error('The real wide Save action must remain a visible unobstructed 44px touch target');" +
                "var values=collectParams();save.click();return JSON.stringify({ok:true,params:values,save:{width:rect.width,height:rect.height}});")
            val done = waitForDom(webView, "actual embedded Python mesh output and the completed results console") {
                "return JSON.stringify({ok:!!state.jobId&&state.es===null&&state.savedModelPaths.length===1&&" +
                    "!document.getElementById('console').classList.contains('hidden')&&!document.getElementById('console-view-model').hidden," +
                    "outputs:state.savedModelPaths,title:document.getElementById('console-title').textContent,log:document.getElementById('log').textContent});"
            }
            val output = File(done.getJSONArray("outputs").getString(0))
            assertEquals("Only the test's output directory may receive the saved model", directory.canonicalFile, output.canonicalFile.parentFile)
            assertTrue("The real Save action must finish a nonempty serialized model", output.isFile && output.length() > 0)
            assertTrue("Asset tools must preserve the selected original fixture", source.readBytes().contentEquals(fixture))
            assertFalse("A 115% head edit must create different serialized data", output.readBytes().contentEquals(fixture))
            val layout = evaluate(webView, "function bounds(target){var r=target.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};}" +
                "var layout=document.querySelector('.tools-console-layout'),main=layout.querySelector('main'),console=document.getElementById('console')," +
                "io=document.querySelector('#tool-form .tool-io'),settings=document.querySelector('#tool-form .tool-settings');" +
                "var m=bounds(main),c=bounds(console),i=bounds(io),s=bounds(settings);" +
                "var noOverflow=document.documentElement.scrollWidth<=innerWidth+1;" +
                "return JSON.stringify({ok:true,viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio,coarse:matchMedia('(pointer:coarse)').matches}," +
                "display:getComputedStyle(layout).display,consolePosition:getComputedStyle(console).position,main:m,console:c,files:i,settings:s,noOverflow:noOverflow," +
                "params:collectParams(),desktop:document.documentElement.classList.contains('elichika-desktop')});")
            assertTrue("The actual wide Android viewport must activate the shared wide tools layout", layout.getJSONObject("viewport").getInt("width") >= 1360)
            assertEquals("grid", layout.getString("display"))
            assertEquals("sticky", layout.getString("consolePosition"))
            assertFalse(layout.getBoolean("desktop"))
            assertTrue("Completed results must sit beside the tool instead of covering its controls",
                layout.getJSONObject("main").getDouble("right") <= layout.getJSONObject("console").getDouble("left") + 1)
            assertTrue("Files and edit settings must use the available wide columns",
                layout.getJSONObject("files").getDouble("right") <= layout.getJSONObject("settings").getDouble("left") + 1)
            assertTrue("The completed console must remain visible within the actual WebView",
                layout.getJSONObject("console").getDouble("top") >= 0 &&
                    layout.getJSONObject("console").getDouble("bottom") <= layout.getJSONObject("viewport").getInt("height") + 1)
            assertTrue("Wide tools must not add horizontal overflow", layout.getBoolean("noOverflow"))
            assertEquals("Running and displaying results preserves the selected source and edited values",
                before.getJSONObject("params").toString(), layout.getJSONObject("params").toString())
            assertFalse("Mesh-only editing must leave game accounts and services untouched", Bus.serverRunning || Bus.serverStarting)
            val viewerWindow = exerciseWideViewerWindow(webView, source)
            val report = JSONObject().put("layout", layout).put("job", done).put("saveControl", before.getJSONObject("save"))
                .put("wideViewerWindow", viewerWindow)
                .put("sourcePreserved", true).put("sourceSha256", sha256(fixture)).put("outputSha256", sha256(output.readBytes()))
                .put("outputBytes", output.length()).put("gameServerRemainedStopped", true)
            File(context.cacheDir, "mesh-wide-tools-report.json").writeText(report.toString(2))
            instrumentation.waitForIdleSync()
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            assertTrue("Capture the actual completed wide Android window", screenshot != null)
            screenshot?.let { bitmap ->
                File(context.cacheDir, "mesh-wide-tools.png").outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
                bitmap.recycle()
            }
            return report
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun exerciseWideViewerWindow(webView: WebView, source: File): JSONObject {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        fun openSource() {
            evaluate(webView, "document.getElementById('viewer-auto-face').checked=false;openModelViewer([" + JSONObject.quote(source.absolutePath) + "]);return JSON.stringify({ok:true});")
            waitForDom(webView, "the same neutral model in the real wide three-pane viewer") {
                "var s=ModelViewer.getState();return JSON.stringify({ok:s.loaded&&!s.loading&&s.stats.vertices===6&&" +
                    "!document.getElementById('viewer-files-resizer').hidden&&!document.getElementById('viewer-panel-resizer').hidden});"
            }
        }
        fun metrics() = evaluate(webView, "function box(id){var r=document.getElementById(id).getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,height:r.height};}" +
            "function handle(id){var e=document.getElementById(id),r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {visible:!e.hidden&&r.width>0&&r.height>0," +
            "hittable:hit===e||e.contains(hit),width:r.width,height:r.height,min:Number(e.getAttribute('aria-valuemin')),max:Number(e.getAttribute('aria-valuemax'))};}" +
            "return JSON.stringify({ok:true,width:innerWidth,coarse:matchMedia('(pointer:coarse)').matches,files:box('viewer-files-panel'),stage:box('viewer-stage'),panel:box('viewer-control-panel')," +
            "filesHandle:handle('viewer-files-resizer'),panelHandle:handle('viewer-panel-resizer'),modelId:ModelViewer.getState().modelId," +
            "storedFiles:Number(localStorage.getItem('elichika.viewer.files-width.v1')||0),storedPanel:Number(localStorage.getItem('elichika.viewer.panel-width.v1')||0)," +
            "overflow:document.documentElement.scrollWidth>innerWidth+1});")
        fun key(id: String, key: Int) {
            instrumentation.runOnMainSync { webView.requestFocus() }
            evaluate(webView, "var handle=document.getElementById(" + JSONObject.quote(id) + ");handle.focus();" +
                "if(document.activeElement!==handle)throw new Error('The real Android keyboard must focus the actual width separator');return JSON.stringify({ok:true});")
            instrumentation.sendKeyDownUpSync(key)
        }
        openSource()
        evaluate(webView, "document.getElementById('viewer-panel-width-reset').click();return JSON.stringify({ok:true});")
        val initial = waitForDom(webView, "default wide viewer widths") {
            "return JSON.stringify({ok:Math.abs(document.getElementById('viewer-files-panel').getBoundingClientRect().width-196)<1&&" +
                "Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-304)<1});"
        }.let { metrics() }
        assertTrue(initial.getInt("width") >= 1200)
        assertFalse("Three panes must fit the real Android WebView", initial.getBoolean("overflow"))
        assertTrue("Keep a usable model canvas", initial.getJSONObject("stage").getDouble("width") >= 320)
        assertEquals("Keep the file/model gutter", 12.0, initial.getJSONObject("stage").getDouble("left") - initial.getJSONObject("files").getDouble("right"), 1.0)
        assertEquals("Keep the model/adjustment gutter", 12.0, initial.getJSONObject("panel").getDouble("left") - initial.getJSONObject("stage").getDouble("right"), 1.0)
        for (name in listOf("filesHandle", "panelHandle")) {
            val handle = initial.getJSONObject(name)
            assertTrue("Both actual splitters must be visible and unobstructed: $handle", handle.getBoolean("visible") && handle.getBoolean("hittable"))
            assertTrue("Keep the existing 24px-wide, full-height splitter hit area", handle.getDouble("width") >= 24 && handle.getDouble("height") >= 48)
        }
        key("viewer-files-resizer", KeyEvent.KEYCODE_DPAD_RIGHT)
        waitForDom(webView, "the file width changed by a real Android right-arrow key") {
            "return JSON.stringify({ok:Number(localStorage.getItem('elichika.viewer.files-width.v1'))===212&&Math.abs(document.getElementById('viewer-files-panel').getBoundingClientRect().width-212)<1});"
        }
        key("viewer-panel-resizer", KeyEvent.KEYCODE_DPAD_LEFT)
        waitForDom(webView, "the adjustment width changed by a real Android left-arrow key") {
            "return JSON.stringify({ok:Number(localStorage.getItem('elichika.viewer.panel-width.v1'))===320&&Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-320)<1});"
        }
        val changed = metrics()
        assertEquals("Keyboard resizing must retain the loaded model", initial.getString("modelId"), changed.getString("modelId"))
        instrumentation.runOnMainSync { webView.reload() }
        waitForDom(webView, "the genuinely reloaded tools page before reopening the same model") {
            "return JSON.stringify({ok:document.readyState==='complete'&&typeof openModelViewer==='function'&&!!window.ModelViewer&&!ModelViewer.getState().loaded});"
        }
        openSource()
        waitForDom(webView, "persisted widths after an actual WebView reload and reopen") {
            "return JSON.stringify({ok:Math.abs(document.getElementById('viewer-files-panel').getBoundingClientRect().width-212)<1&&Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-320)<1});"
        }
        val restored = metrics()
        assertEquals(212, restored.getInt("storedFiles")); assertEquals(320, restored.getInt("storedPanel"))
        evaluate(webView, "var button=document.getElementById('viewer-panel-width-reset');button.scrollIntoView({block:'center'});var r=button.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);" +
            "if(r.height<44||!(hit===button||button.contains(hit)))throw new Error('Default layout must remain a real 44px Android touch action');button.click();return JSON.stringify({ok:true});")
        waitForDom(webView, "Default layout restores both actual widths and clears both preferences") {
            "return JSON.stringify({ok:!localStorage.getItem('elichika.viewer.files-width.v1')&&!localStorage.getItem('elichika.viewer.panel-width.v1')&&" +
                "Math.abs(document.getElementById('viewer-files-panel').getBoundingClientRect().width-196)<1&&Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-304)<1});"
        }
        return JSONObject().put("initial", initial).put("actualAndroidKeyboard", changed).put("reloaded", restored).put("defaultReset", metrics())
            .put("source", source.absolutePath).put("scope", "Real wm-sized Android WebView and Android KeyEvent input; touch dragging is covered separately on host")
    }

    private fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun waitForTools(): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var failure = ""
        while (System.nanoTime() < deadline) {
            val connection = URL("http://127.0.0.1:8770/api/tools").openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 3000
                connection.readTimeout = 3000
                return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            } catch (error: Exception) {
                failure = error.toString()
                Thread.sleep(100)
            } finally { connection.disconnect() }
        }
        throw AssertionError("Tool HTTP server did not become ready: $failure")
    }

    private fun waitForDom(webView: WebView, description: String, script: () -> String): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = evaluate(webView, script())
            if (last.optBoolean("ok")) return last
            Thread.sleep(100)
        }
        fail("Timed out waiting for $description: $last")
        return last
    }

    private fun evaluate(webView: WebView, body: String): JSONObject {
        val result = AtomicReference<String>()
        val done = CountDownLatch(1)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            // Deliberately use ES5 syntax: Chromium 74 must parse the test too.
            webView.evaluateJavascript("(function(){try{$body}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();") {
                result.set(it)
                done.countDown()
            }
        }
        assertTrue("WebView JS callback timed out", done.await(15, TimeUnit.SECONDS))
        val decoded = JSONTokener(result.get()).nextValue()
        val value = JSONObject(decoded as? String ?: throw AssertionError("Unexpected JS result: ${result.get()}"))
        if (value.optString("error").isNotEmpty() && !value.optBoolean("ok", true)) throw AssertionError("WebView JS failed: $value")
        return value
    }

    private fun descendants(view: View): Sequence<View> = sequence {
        yield(view)
        if (view is ViewGroup) for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
    }
}
