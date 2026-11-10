// QA-only visible AppKit/WKWebView host. This is not the shipped Elichika app.
// Uses public default WK configuration corresponding to WebPanel.swift.
import AppKit
import Foundation
import WebKit

enum DiagnosticError: Error { case usage, invalidURL, invalidReply, snapshotFailed }

@MainActor
final class DiagnosticHost: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandlerWithReply {
    private let targetURL: URL
    private let preload: String
    private let script: String
    private let config: Any
    private let output: URL
    private let width: Int
    private let height: Int
    private let timeout: Double
    private var window: NSWindow!
    private var webView: WKWebView!
    private var deadline: Timer?
    private var started = false
    private var finished = false
    private let startedAt = Date()
    private var snapshots: [[String: Any]] = []
    private var startVisibility: [String: Any] = [:]

    init(arguments: [String]) throws {
        guard arguments.count >= 6 else { throw DiagnosticError.usage }
        guard let url = URL(string: arguments[1]), url.scheme == "http", url.host == "127.0.0.1",
              url.user == nil, url.password == nil else { throw DiagnosticError.invalidURL }
        targetURL = url
        preload = try String(contentsOfFile: arguments[2], encoding: .utf8)
        script = try String(contentsOfFile: arguments[3], encoding: .utf8)
        config = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: arguments[4])))
        output = URL(fileURLWithPath: arguments[5], isDirectory: true)
        width = arguments.count > 6 ? Int(arguments[6]) ?? 1280 : 1280
        height = arguments.count > 7 ? Int(arguments[7]) ?? 1000 : 1000
        timeout = arguments.count > 8 ? Double(arguments[8]) ?? 480 : 480
        super.init()
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.userContentController.addUserScript(WKUserScript(source: preload, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        configuration.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "qaDiagnostic")
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)), configuration: configuration)
        webView.navigationDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        window = NSWindow(contentRect: NSRect(x: 60, y: 60, width: CGFloat(width), height: CGFloat(height)), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "QA-only native WKWebView diagnostic"
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        deadline = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.finish(result: nil, error: "Native diagnostic timeout") }
        }
        var request = URLRequest(url: targetURL)
        // Optional normal-runtime first-request headers. Values never enter JS or reports.
        if let path = ProcessInfo.processInfo.environment["QA_REQUEST_HEADERS_FILE"] {
            do {
                let data = try Data(contentsOf: URL(fileURLWithPath: path))
                guard let headers = try JSONSerialization.jsonObject(with: data) as? [String: String] else { throw DiagnosticError.invalidReply }
                for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
            } catch { finish(result: nil, error: "Could not read the private request headers file"); return }
        }
        webView.load(request)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard !started, !finished else { return }
        started = true
        Task { @MainActor in
            let until = Date().addingTimeInterval(20)
            while !(NSApp.isActive && self.window.isKeyWindow && self.window.occlusionState.contains(.visible)) {
                if Date() >= until { self.finish(result: nil, error: "The QA window did not become active, key and visible"); return }
                self.window.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            self.startVisibility = ["applicationActive": NSApp.isActive, "windowKey": self.window.isKeyWindow,
                                    "windowOcclusionVisible": self.window.occlusionState.contains(.visible)]
            webView.callAsyncJavaScript(self.script, arguments: ["config": self.config], in: nil, in: .page) { [weak self] result in
                Task { @MainActor in
                    switch result {
                    case .success(let value): self?.finish(result: value, error: nil)
                    case .failure(let error): self?.finish(result: nil, error: String(describing: error))
                    }
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        finish(result: nil, error: "Navigation: \(error)")
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        finish(result: nil, error: "Native WebKit content process terminated")
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.protocol == "http",
              message.frameInfo.securityOrigin.host == "127.0.0.1",
              message.frameInfo.securityOrigin.port == (targetURL.port ?? 80),
              let request = message.body as? [String: Any], request["kind"] as? String == "snapshot",
              let name = request["name"] as? String,
              name.range(of: "^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$", options: .regularExpression) != nil else {
            replyHandler(nil, "Invalid diagnostic request"); return
        }
        let destination = output.appendingPathComponent(name + ".png")
        let settings = WKSnapshotConfiguration()
        settings.afterScreenUpdates = true
        let before = Date()
        webView.takeSnapshot(with: settings) { [weak self] image, error in
            Task { @MainActor in
                do {
                    if let error { throw error }
                    guard let image, let tiff = image.tiffRepresentation,
                          let bitmap = NSBitmapImageRep(data: tiff),
                          let data = bitmap.representation(using: .png, properties: [:]) else { throw DiagnosticError.snapshotFailed }
                    try data.write(to: destination, options: .atomic)
                    let value: [String: Any] = ["name": name, "file": destination.lastPathComponent,
                                               "width": bitmap.pixelsWide, "height": bitmap.pixelsHigh,
                                               "elapsedMs": Date().timeIntervalSince(before) * 1000]
                    self?.snapshots.append(value)
                    replyHandler(value, nil)
                } catch { replyHandler(nil, "Snapshot: \(error)") }
            }
        }
    }

    private func finish(result: Any?, error: String?) {
        guard !finished else { return }
        finished = true
        deadline?.invalidate()
        var native: [String: Any] = ["host": "QA-only standalone AppKit WKWebView; not shipped Elichika.app",
                                    "os": ProcessInfo.processInfo.operatingSystemVersionString,
                                    "architecture": "\(MemoryLayout<Int>.size * 8)-bit",
                                    "webViewUserAgent": "default public WKWebView configuration",
                                    "elapsedSeconds": Date().timeIntervalSince(startedAt),
                                    "startVisibility": startVisibility,
                                    "snapshots": snapshots]
        #if arch(arm64)
        native["cpuArchitecture"] = "arm64"
        #else
        native["cpuArchitecture"] = "x86_64"
        #endif
        if let window {
            native["windowBackingScaleFactor"] = window.backingScaleFactor
            native["windowVisible"] = window.isVisible
            native["windowOcclusionVisible"] = window.occlusionState.contains(.visible)
            native["windowKey"] = window.isKeyWindow
            native["applicationActive"] = NSApp.isActive
            native["viewWidth"] = webView.bounds.width
            native["viewHeight"] = webView.bounds.height
            if let screen = window.screen {
                native["screenMaximumFramesPerSecond"] = screen.maximumFramesPerSecond
                native["screenWidth"] = screen.frame.width
                native["screenHeight"] = screen.frame.height
            }
        }
        var report: [String: Any] = ["status": error == nil ? "PASS" : "FAIL", "native": native]
        if let result { report["javascript"] = result }
        if let error { report["error"] = error }
        do {
            let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: output.appendingPathComponent("native-report.json"), options: .atomic)
            print("Native WK diagnostic \(error == nil ? "PASS" : "FAIL"); report native-report.json")
        } catch { fputs("Could not write diagnostic report: \(error)\n", stderr) }
        webView?.stopLoading()
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "qaDiagnostic", contentWorld: .page)
        window?.orderOut(nil)
        exit(error == nil ? 0 : 1)
    }
}

@main
struct Main {
    @MainActor
    static func main() {
        do {
            let host = try DiagnosticHost(arguments: CommandLine.arguments)
            let app = NSApplication.shared
            app.setActivationPolicy(.regular)
            app.delegate = host
            withExtendedLifetime(host) { app.run() }
        } catch {
            fputs("Usage: NativeWKDiagnostic http://127.0.0.1:PORT/ preload.js probe.js config.json OUT [WIDTH HEIGHT TIMEOUT]\n\(error)\n", stderr)
            exit(2)
        }
    }
}
