import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WebKit

enum BrowserRoute: String, Hashable { case accounts, content, assets, serverSettings }

@MainActor
final class BrowserSession: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    let webView: WKWebView
    private weak var model: AppModel?
    private let route: BrowserRoute
    private let origin: TrustedOrigin?
    private let targetURL: URL?
    private let bridgeEnabled: Bool
    private var loaded = false
    private var pendingPerform: (String, [String]?)?
    private var activeRequests = Set<String>()
    private var windowObservers: [NSObjectProtocol] = []
    private weak var observedWindow: NSWindow?
    private var fullscreenOwned = false
    private var viewerFullscreen = false
    private var currentLanguage: String
    private var fullscreenCompletion: ((Result<Bool, Error>) -> Void)?

    init(model: AppModel, route: BrowserRoute) {
        self.model = model; self.route = route
        currentLanguage = model.language
        bridgeEnabled = route == .content || route == .assets
        if let ready = model.connection {
            switch route {
            case .content: targetURL = ready.adminURL
            case .assets: targetURL = ready.toolsURL
            case .accounts: targetURL = model.goURL(path: "/webui/user/")
            case .serverSettings: targetURL = model.goURL(path: "/webui/admin/")
            }
        } else { targetURL = nil }
        origin = targetURL.flatMap(TrustedOrigin.init)
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = bridgeEnabled ? model.websiteDataStore : model.goWebsiteDataStore
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        if bridgeEnabled {
            configuration.userContentController.addUserScript(Self.platformScript(language: model.language))
        }
        webView = WKWebView(frame: .zero, configuration: configuration)
        super.init()
        webView.navigationDelegate = self; webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        if bridgeEnabled { configuration.userContentController.add(self, name: "elichika") }
        if let targetURL {
            var request = URLRequest(url: targetURL)
            if bridgeEnabled, let uiToken = model.connection?.uiToken {
                request.setValue(uiToken, forHTTPHeaderField: "X-Elichika-Session")
            }
            webView.load(request)
        }
    }

    func dispose() {
        webView.stopLoading()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "elichika")
        windowObservers.forEach(NotificationCenter.default.removeObserver)
        windowObservers.removeAll()
    }

    func perform(_ action: String, paths: [String]? = nil) {
        guard bridgeEnabled, route == .assets, ["openModel", "saveModel", "showViewer"].contains(action) else { return }
        guard loaded else { pendingPerform = (action, paths); return }
        let arguments: [String: Any] = ["action": action, "payload": paths.map { ["paths": $0] } ?? [:]]
        let data = try! JSONSerialization.data(withJSONObject: arguments)
        let json = String(decoding: data, as: UTF8.self)
        webView.evaluateJavaScript("(function(){const a=" + json + ";if(window.ElichikaPlatform)window.ElichikaPlatform.perform(a.action,a.payload);})();")
    }

    func setLanguage(_ language: String) {
        guard bridgeEnabled, ["en", "ko", "ja"].contains(language), language != currentLanguage else { return }
        currentLanguage = language
        webView.configuration.userContentController.removeAllUserScripts()
        webView.configuration.userContentController.addUserScript(Self.platformScript(language: language))
        let json = String(decoding: try! JSONSerialization.data(withJSONObject: [language]), as: UTF8.self)
        webView.evaluateJavaScript("(function(){const l=" + json + "[0];if(window.ElichikaDesktop)window.ElichikaDesktop.language=l;if(typeof changeLang==='function')changeLang(l);})();")
    }

    private static func platformScript(language: String) -> WKUserScript {
        let metadata: [String: Any] = ["platform": "macos", "version": 1,
            "capabilities": ["openFiles", "chooseDirectory", "reveal", "fullscreen", "setLanguage"], "language": language]
        let json = String(decoding: try! JSONSerialization.data(withJSONObject: metadata), as: UTF8.self)
        return WKUserScript(source: "window.ElichikaDesktop=" + json + ";", injectionTime: .atDocumentStart, forMainFrameOnly: true)
    }

    private func trusted(_ message: WKScriptMessage) -> Bool {
        guard bridgeEnabled, message.frameInfo.isMainFrame, let origin,
              let current = webView.url, origin.contains(current) else { return false }
        let sender = message.frameInfo.securityOrigin
        return sender.protocol == "http" && sender.host == "127.0.0.1" && sender.port == origin.port
    }

    private func allowsNavigation(_ url: URL) -> Bool {
        if bridgeEnabled { return origin?.contains(url) == true }
        guard let targetURL, url.scheme == "http", url.user == nil, url.password == nil,
              url.host == targetURL.host, url.port == targetURL.port else { return false }
        let host = (url.host ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        return IPAddress.isLiteral(host)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "elichika", trusted(message), let model else { return }
        let request: NativeRequest
        do { request = try NativeRequest.parse(message.body) } catch { return }
        guard activeRequests.count < 16, !activeRequests.contains(request.id) else { return }
        activeRequests.insert(request.id)
        Task {
            do {
                let result: [String: Any]
                switch request.action {
                case .openFiles:
                    let urls = try await chooseFiles(request)
                    result = urls.isEmpty ? ["cancelled": true] : ["paths": try await model.authorize(urls)]
                case .chooseDirectory:
                    let urls = try await chooseDirectory(request)
                    if !urls.isEmpty, let first = try await model.authorize(urls).first { result = ["path": first] }
                    else { result = ["cancelled": true] }
                case .reveal:
                    guard let path = request.path else { throw NativeError.invalidMessage }
                    try model.reveal(path); result = ["path": path]
                case .setFullscreen:
                    guard let enabled = request.enabled else { throw NativeError.invalidMessage }
                    result = ["active": try await setFullscreen(enabled), "settled": true]
                case .setLanguage:
                    guard let language = request.language, ["en", "ko", "ja"].contains(language) else { throw NativeError.invalidMessage }
                    model.setLanguage(language); result = ["language": language]
                }
                reply(id: request.id, result: result)
            } catch { reply(id: request.id, error: error.localizedDescription) }
            activeRequests.remove(request.id)
        }
    }

    private func reply(id: String, result: [String: Any]? = nil, error: String? = nil) {
        var message: [String: Any] = ["id": id]
        if let result { message["result"] = result }
        if let error { message["error"] = error }
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        let json = String(decoding: data, as: UTF8.self)
        webView.evaluateJavaScript("if(window.ElichikaPlatform)window.ElichikaPlatform.receive(" + json + ");")
    }

    private func chooseFiles(_ request: NativeRequest) async throws -> [URL] {
        guard let model else { throw NativeError.runtimeUnavailable }
        if model.smokeDirectory != nil {
            return [model.resourceDirectory.appendingPathComponent("qa/viewer_persistence.unity")]
        }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = false
        panel.allowsMultipleSelection = request.multiple ?? false
        panel.allowedContentTypes = (request.extensions ?? []).compactMap { UTType(filenameExtension: $0) }
        panel.allowsOtherFileTypes = true
        panel.title = request.title ?? model.text("Choose model files", "모델 파일 선택", "モデルファイルを選択")
        let response = await present(panel)
        return response == .OK ? Array(panel.urls.prefix(128)) : []
    }

    private func chooseDirectory(_ request: NativeRequest) async throws -> [URL] {
        guard let model else { throw NativeError.runtimeUnavailable }
        if model.smokeDirectory != nil { return [URL(fileURLWithPath: model.libraryDirectory, isDirectory: true)] }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true
        panel.title = request.title ?? model.text("Choose folder", "폴더 선택", "フォルダーを選択")
        return await present(panel) == .OK ? Array(panel.urls.prefix(1)) : []
    }

    private func present(_ panel: NSOpenPanel) async -> NSApplication.ModalResponse {
        await withCheckedContinuation { continuation in
            if let window = webView.window {
                panel.beginSheetModal(for: window) { continuation.resume(returning: $0) }
            } else { panel.begin { continuation.resume(returning: $0) } }
        }
    }

    private func observeWindow() {
        guard let window = webView.window, observedWindow !== window else { return }
        windowObservers.forEach(NotificationCenter.default.removeObserver)
        windowObservers.removeAll(); observedWindow = window
        for (name, active) in [(NSWindow.didEnterFullScreenNotification, true), (NSWindow.didExitFullScreenNotification, false)] {
            windowObservers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                Task { @MainActor in
                    guard let self else { return }
                    self.emitFullscreen(active, settled: true)
                    self.fullscreenCompletion?(.success(active)); self.fullscreenCompletion = nil
                    if !active { self.fullscreenOwned = false; self.viewerFullscreen = false }
                }
            })
        }
        emitFullscreen(false, settled: false)
    }

    private func emitFullscreen(_ active: Bool, settled: Bool) {
        guard bridgeEnabled else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('elichika-native-fullscreen-changed',{detail:{active:\(active),settled:\(settled)}}));")
    }

    private func setFullscreen(_ enabled: Bool) async throws -> Bool {
        observeWindow()
        guard let window = webView.window else { throw NativeError.service("The app window is not available.") }
        guard fullscreenCompletion == nil else { throw NativeError.service("The window is changing fullscreen mode.") }
        let actual = window.styleMask.contains(.fullScreen)
        if enabled && actual { viewerFullscreen = true; emitFullscreen(true, settled: true); return true }
        if !enabled && !fullscreenOwned {
            viewerFullscreen = false; emitFullscreen(false, settled: true); return false
        }
        if actual == enabled { return actual }
        if enabled { fullscreenOwned = true; viewerFullscreen = true }
        return try await withCheckedThrowingContinuation { continuation in
            fullscreenCompletion = { result in continuation.resume(with: result) }
            window.toggleFullScreen(nil)
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 6_000_000_000)
                guard let self, let pending = self.fullscreenCompletion else { return }
                self.fullscreenCompletion = nil
                pending(.failure(NativeError.timeout("fullscreen")))
            }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = true
        observeWindow()
        if let model { setLanguage(model.language) }
        if let (action, paths) = pendingPerform { pendingPerform = nil; perform(action, paths: paths) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if allowsNavigation(url) {
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
            return
        }
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard let url = navigationResponse.response.url, allowsNavigation(url) else { decisionHandler(.cancel); return }
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        guard let url = response.url, allowsNavigation(url) else { completionHandler(nil); return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.canCreateDirectories = true
        if let window = webView.window {
            panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
        } else { panel.begin { completionHandler($0 == .OK ? panel.url : nil) } }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) { model?.message = error.localizedDescription }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url else { return nil }
        if allowsNavigation(url) { webView.load(navigationAction.request) }
        else if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        guard frame.isMainFrame, let source = frame.request.url, allowsNavigation(source),
              frame.securityOrigin.protocol == "http", frame.securityOrigin.port == source.port,
              frame.securityOrigin.host.trimmingCharacters(in: CharacterSet(charactersIn: "[]")) == source.host?.trimmingCharacters(in: CharacterSet(charactersIn: "[]")) else { completionHandler(nil); return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.begin { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        loaded = false
        model?.message = "The web editor stopped. Reopen the app after preserving any exported files."
    }
}

struct WebPanel: NSViewRepresentable {
    @ObservedObject var model: AppModel
    let route: BrowserRoute
    func makeNSView(context: Context) -> WKWebView { model.browser(route).webView }
    func updateNSView(_ view: WKWebView, context: Context) {}
}
