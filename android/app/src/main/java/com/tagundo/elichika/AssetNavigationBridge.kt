package com.tagundo.elichika

import android.app.Activity
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import java.util.UUID

/** Two native destinations share one live tool document, model and authoring session. */
internal class AssetNavigationBridge(
    private val activity: Activity,
    private val onSection: (WebView, String, Boolean) -> Unit,
) {
    private val attached = HashSet<WebView>()
    private val legacyTokens = HashMap<WebView, String>()
    private var disposed = false

    fun attach(view: WebView) {
        if (disposed || !attached.add(view)) return
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(view, BRIDGE, setOf(ORIGIN)) { source, message, origin, mainFrame, _ ->
                if (mainFrame && trustedOrigin(origin) && message.type == WebMessageCompat.TYPE_STRING) {
                    receive(source, message.data)
                }
            }
        }
    }

    fun onPageStarted(view: WebView) { legacyTokens.remove(view) }

    fun onPageFinished(view: WebView) {
        if (!trustedView(view)) return
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            // Older providers get two fixed navigation commands, never a Java
            // object exposed to arbitrary frames or loaded model content.
            val token = UUID.randomUUID().toString()
            legacyTokens[view] = token
            view.evaluateJavascript("""
                (function(){
                  if(location.origin!=="$ORIGIN"||location.pathname!=="/")return;
                  var capability='$token';
                  window.$BRIDGE={postMessage:function(raw){
                    var value;try{value=JSON.parse(raw);}catch(e){return;}
                    if(!value||(value.section!=='tools'&&value.section!=='viewer'))return;
                    if(value.event!=='ready'&&value.event!=='change')return;
                    location.href='$SCHEME://'+value.event+'/'+value.section+'?token='+capability;
                  }};
                })();
            """.trimIndent(), null)
        }
    }

    fun showSection(view: WebView, section: String) {
        if (section !in SECTIONS || !trustedView(view)) return
        // Native already owns the selected tab. Suppressing its echo also
        // prevents a late acknowledgement of an earlier tap changing it back.
        view.evaluateJavascript(
            "if(window.ElichikaNavigation)window.ElichikaNavigation.showSection(${JSONObject.quote(section)},{notify:false});",
            null,
        )
    }

    fun shouldOverride(view: WebView, request: WebResourceRequest): Boolean {
        val uri = request.url
        if (uri.scheme != SCHEME) return false
        val token = legacyTokens[view]
        val section = uri.path?.removePrefix("/")
        if (token != null && request.isForMainFrame && uri.userInfo == null && uri.port == -1 &&
            uri.encodedQuery == "token=$token" && uri.fragment == null && section in SECTIONS &&
            uri.host in setOf("ready", "change")) {
            receive(view, JSONObject().put("event", uri.host).put("section", section).toString())
        }
        return true
    }

    private fun receive(view: WebView, raw: String?) {
        if (!trustedView(view) || raw == null || raw.length > 160) return
        val value = runCatching { JSONObject(raw) }.getOrNull() ?: return
        val event = value.optString("event")
        val section = value.optString("section")
        if (event !in setOf("ready", "change") || section !in SECTIONS) return
        onSection(view, section, event == "ready")
    }

    private fun trustedView(view: WebView): Boolean = !disposed && attached.contains(view) &&
        !activity.isFinishing && !activity.isDestroyed && runCatching {
            isEmbeddedDocument(Uri.parse(view.url ?: ""))
        }.getOrDefault(false)

    fun dispose() {
        disposed = true
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            attached.forEach { WebViewCompat.removeWebMessageListener(it, BRIDGE) }
        }
        attached.clear()
        legacyTokens.clear()
    }

    companion object {
        const val ORIGIN = "http://127.0.0.1:8770"
        private const val BRIDGE = "ElichikaNavigationNative"
        private const val SCHEME = "elichika-asset-navigation"
        private val SECTIONS = setOf("tools", "viewer")
        private val queries = Lang.SUPPORTED.map { "embedded=1&lang=$it" }.toSet()

        fun pageUrl(language: String): String {
            val safeLanguage = language.takeIf { it in Lang.SUPPORTED } ?: "en"
            return "$ORIGIN/?embedded=1&lang=$safeLanguage"
        }

        fun trustedOrigin(uri: Uri): Boolean = uri.scheme == "http" && uri.host == "127.0.0.1" &&
            uri.port == 8770 && uri.userInfo == null

        fun isEmbeddedDocument(uri: Uri): Boolean = trustedOrigin(uri) &&
            (uri.path == "/" || uri.path.isNullOrEmpty()) && uri.encodedQuery in queries

        /** Standalone pages remain compatible with the existing fullscreen bridge. */
        fun isToolDocument(uri: Uri): Boolean = trustedOrigin(uri) &&
            (uri.path == "/" || uri.path.isNullOrEmpty()) && (uri.query == null || uri.encodedQuery in queries)
    }
}
