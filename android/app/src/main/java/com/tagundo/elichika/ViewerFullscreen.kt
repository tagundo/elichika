package com.tagundo.elichika

import android.app.Activity
import android.net.Uri
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import java.util.UUID

/** Window presentation only: the existing viewer WebView and its renderer never move or reload. */
@Suppress("DEPRECATION")
internal class ViewerFullscreen(
    private val activity: Activity,
    private val chrome: List<View>,
    private val isActiveViewer: (WebView) -> Boolean,
) {
    private data class PreviousUi(
        val fullscreenFlag: Int,
        val systemUi: Int,
        val barBehavior: Int,
        val statusVisible: Boolean?,
        val navigationVisible: Boolean?,
        val visibility: List<Int>,
        val focus: View?,
    )

    private val attached = HashSet<WebView>()
    private val legacyTokens = HashMap<WebView, String>()
    private var started = false
    private var disposed = false
    private var requestGeneration = 0
    private var pending: WebView? = null
    private var owner: WebView? = null
    private var previous: PreviousUi? = null
    private val bars = WindowInsetsCompat.Type.statusBars() or WindowInsetsCompat.Type.navigationBars()

    fun attach(view: WebView) {
        if (disposed || !attached.add(view)) return
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(view, BRIDGE, setOf(ORIGIN)) { source, message, origin, mainFrame, _ ->
                if (mainFrame && trustedOrigin(origin) && message.type == WebMessageCompat.TYPE_STRING) {
                    command(source, message.data)
                }
            }
        }
    }

    fun onStart() { started = true }

    fun onStop() {
        started = false
        exit()
    }

    /** Includes navigation to another local tool: fullscreen belongs to one live viewer document. */
    fun onPageStarted(view: WebView) {
        legacyTokens.remove(view)
        if (owner === view || pending === view) exit()
    }

    fun onPageFinished(view: WebView) {
        if (!trustedView(view)) return
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            // WebView 74 predates origin-scoped message listeners. A consumed,
            // main-frame URL supplies the same two commands, without exposing
            // a Java object (or an arbitrary native operation) to page frames.
            val token = UUID.randomUUID().toString()
            legacyTokens[view] = token
            view.evaluateJavascript("""
                (function(){
                  if(location.origin!=="$ORIGIN"||location.pathname!=="/")return;
                  var capability='$token';
                  window.$BRIDGE={postMessage:function(command){
                    if(command==='enter'||command==='exit')location.href='$SCHEME://'+command+'?token='+capability;
                  }};
                })();
            """.trimIndent(), null)
        }
        publish(view, settled = false)
    }

    /** Always consume our private scheme, including rejected requests from untrusted frames/pages. */
    fun shouldOverride(view: WebView, request: WebResourceRequest): Boolean {
        val uri = request.url
        if (uri.scheme != SCHEME) return false
        // isForMainFrame describes the navigation target, not its initiator.
        // A foreign iframe could navigate top; it cannot read this random
        // capability injected only into the trusted main document.
        val token = legacyTokens[view]
        if (token != null && request.isForMainFrame && uri.userInfo == null && uri.port == -1 &&
            uri.path.isNullOrEmpty() && uri.encodedQuery == "token=$token" && uri.fragment == null) {
            command(view, uri.host)
        }
        return true
    }

    private fun command(view: WebView, command: String?) {
        if (!trustedView(view)) return
        if (command == "exit") {
            if (!exit()) publish(view)
            return
        }
        if (command != "enter") return
        val token = ++requestGeneration
        pending = view
        // The tools are a single-page app. The URL alone cannot distinguish
        // its model viewer from the unrelated tools and gallery sections.
        view.evaluateJavascript("""
            (function(){var viewer=document.getElementById('tab-viewer');
              return location.origin==='$ORIGIN'&&location.pathname==='/'&&
                !!viewer&&viewer.classList.contains('active')&&!document.hidden;
            })()
        """.trimIndent()) { result ->
            if (disposed || token != requestGeneration) return@evaluateJavascript
            pending = null
            if (result == "true" && started && trustedView(view) && isActiveViewer(view)) enter(view)
            else publish(view)
        }
    }

    private fun enter(view: WebView) {
        if (previous == null) {
            val window = activity.window
            val decor = window.decorView
            val insets = ViewCompat.getRootWindowInsets(decor)
            previous = PreviousUi(
                window.attributes.flags and WindowManager.LayoutParams.FLAG_FULLSCREEN,
                decor.systemUiVisibility,
                WindowInsetsControllerCompat(window, decor).systemBarsBehavior,
                insets?.isVisible(WindowInsetsCompat.Type.statusBars()),
                insets?.isVisible(WindowInsetsCompat.Type.navigationBars()),
                chrome.map { it.visibility }, activity.currentFocus,
            )
            owner = view
        }
        reapply()
        view.requestFocus()
        publish(view)
    }

    /** Back, tab changes and lifecycle exits synchronously restore the exact prior native presentation. */
    fun exit(): Boolean {
        requestGeneration += 1
        val pendingView = pending
        pending = null
        val saved = previous
        if (saved == null) {
            if (pendingView != null) publish(pendingView)
            return pendingView != null
        }
        val view = owner
        previous = null
        owner = null
        val window = activity.window
        val decor = window.decorView
        val controller = WindowInsetsControllerCompat(window, decor)
        controller.systemBarsBehavior = saved.barBehavior
        saved.statusVisible?.let { if (it) controller.show(WindowInsetsCompat.Type.statusBars()) else controller.hide(WindowInsetsCompat.Type.statusBars()) }
        saved.navigationVisible?.let { if (it) controller.show(WindowInsetsCompat.Type.navigationBars()) else controller.hide(WindowInsetsCompat.Type.navigationBars()) }
        window.setFlags(saved.fullscreenFlag, WindowManager.LayoutParams.FLAG_FULLSCREEN)
        decor.systemUiVisibility = saved.systemUi
        chrome.forEachIndexed { index, item -> item.visibility = saved.visibility[index] }
        ViewCompat.requestApplyInsets(decor)
        saved.focus?.takeIf { it.isAttachedToWindow && it.isShown }?.requestFocus()
        if (view != null) publish(view)
        return true
    }

    /** Configuration changes are handled in place by MainActivity; keep the same model and camera. */
    fun reapply() {
        if (disposed || previous == null) return
        val window = activity.window
        val decor = window.decorView
        chrome.forEach { it.visibility = View.GONE }
        window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        decor.systemUiVisibility = decor.systemUiVisibility or
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        WindowInsetsControllerCompat(window, decor).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(bars)
        }
        ViewCompat.requestApplyInsets(decor)
    }

    private fun publish(view: WebView, settled: Boolean = true) {
        // Let native layout and WebView viewport resize settle before the page
        // updates its CSS fullscreen mode. Always report the latest state, so
        // an already queued entry acknowledgement cannot outlive Back/Stop.
        // The unsolicited page-ready state does not settle a command sent
        // just before its delayed acknowledgement reaches JavaScript.
        view.postOnAnimation {
            view.postOnAnimation {
                if (pending !== view && trustedView(view)) {
                    val active = previous != null && owner === view
                    view.evaluateJavascript(
                        "window.dispatchEvent(new CustomEvent('elichika-native-fullscreen',{detail:{active:$active,settled:$settled}}));",
                        null,
                    )
                }
            }
        }
    }

    private fun trustedView(view: WebView): Boolean = !disposed && attached.contains(view) &&
        !activity.isFinishing && !activity.isDestroyed && runCatching {
            val uri = Uri.parse(view.url ?: "")
            AssetNavigationBridge.isToolDocument(uri)
        }.getOrDefault(false)

    private fun trustedOrigin(uri: Uri): Boolean = uri.scheme == "http" &&
        uri.host == "127.0.0.1" && uri.port == 8770 && uri.userInfo == null

    fun dispose() {
        exit()
        disposed = true
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            attached.forEach { WebViewCompat.removeWebMessageListener(it, BRIDGE) }
        }
        attached.clear()
        legacyTokens.clear()
    }

    companion object {
        const val ORIGIN = AssetNavigationBridge.ORIGIN
        private const val BRIDGE = "ElichikaViewerFullscreen"
        private const val SCHEME = "elichika-viewer-fullscreen"
    }
}
