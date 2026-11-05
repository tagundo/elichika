import AppKit
import Foundation
import WebKit
import Darwin

@MainActor
final class AppModel: ObservableObject {
    @Published var selectedSection: AppSection? = .server
    @Published var snapshot = RuntimeState()
    @Published var connection: RuntimeReady?
    @Published var message: String?
    @Published var console: [String] = []
    @Published var launching = false
    @Published var quitting = false
    @Published private(set) var stoppingRuntime = false
    @Published var language: String
    @Published var libraryDirectory: String
    @Published var showServerSettings = false
    @Published var serverAddressDraft = "127.0.0.1:8080"
    @Published var cdnServerDraft = "http://127.0.0.1:8080/static"
    @Published private(set) var savingNetwork = false

    let websiteDataStore = WKWebsiteDataStore.nonPersistent()
    let goWebsiteDataStore = WKWebsiteDataStore.nonPersistent()
    let smokeDirectory: URL?
    let resourceDirectory: URL
    let dataDirectory: URL
    private(set) var process: Process?
    private var verifiedGroup: pid_t?
    private var outputPipe: Pipe?
    private var errorPipe: Pipe?
    private var readers: [PipeLines] = []
    private var polling: Task<Void, Never>?
    private var logCursor = 0
    private var browsers: [BrowserRoute: BrowserSession] = [:]
    private var approvedFiles: Set<String> = []
    private var approvedDirectories: Set<String> = []
    private var started = false
    private var smokeStarted = false
    private var networkApplied: ServerNetworkConfig?
    private var reportedRuntimeError: String?
    private let http: URLSession
    var smokeQuitObserver: (() async -> Void)?

    init(arguments: [String] = CommandLine.arguments, resources: URL? = Bundle.main.resourceURL) {
        let locale = Locale.preferredLanguages.first?.prefix(2).lowercased() ?? "en"
        let stored = UserDefaults.standard.string(forKey: "language") ?? locale
        language = ["en", "ko", "ja"].contains(stored) ? stored : "en"
        resourceDirectory = resources ?? URL(fileURLWithPath: "/missing-resources", isDirectory: true)
        if let index = arguments.firstIndex(of: "--smoke-test"), arguments.indices.contains(index + 1) {
            smokeDirectory = URL(fileURLWithPath: arguments[index + 1], isDirectory: true)
        } else { smokeDirectory = nil }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        dataDirectory = smokeDirectory?.appendingPathComponent("application-support", isDirectory: true)
            ?? support.appendingPathComponent("Elichika", isDirectory: true)
        libraryDirectory = smokeDirectory?.appendingPathComponent("sukusta", isDirectory: true).path
            ?? UserDefaults.standard.string(forKey: "libraryDirectory")
            ?? dataDirectory.appendingPathComponent("sukusta", isDirectory: true).path
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 30
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.connectionProxyDictionary = [:]
        http = URLSession(configuration: configuration, delegate: LocalControlSessionDelegate(), delegateQueue: nil)
        if smokeDirectory != nil { selectedSection = .assets }
    }

    func text(_ en: String, _ ko: String, _ ja: String) -> String {
        NativeText.value(en, ko, ja, language: language)
    }

    var toolsReady: Bool { connection != nil && process?.isRunning == true && snapshot.prepared && snapshot.phase != "error" && !stoppingRuntime }
    var canChangeStorage: Bool { !snapshot.busy && !snapshot.serverRunning && !quitting && !launching && !stoppingRuntime }
    var serverStatusTitle: String {
        if snapshot.serverRunning && snapshot.server?.httpReady != true { return text("Server starting…", "서버 시작 중…", "サーバー起動中…") }
        return snapshot.serverRunning ? text("Server running", "서버 실행 중", "サーバー実行中") : text("Server stopped", "서버 중지됨", "サーバー停止中")
    }
    var networkChanged: Bool { networkApplied != ServerNetworkConfig(serverAddress: serverAddressDraft, cdnServer: cdnServerDraft) }
    var connectionAddress: String? {
        guard let raw = networkApplied?.cdnServer, var value = URLComponents(string: raw) else { return nil }
        value.path = ""; value.query = nil; value.fragment = nil
        return value.url?.absoluteString
    }

    func launch() {
        guard !started, !quitting else { return }
        started = true
        launching = true
        message = nil
        Task {
            do {
                try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
                try FileManager.default.createDirectory(atPath: libraryDirectory, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
                #if arch(arm64)
                let architecture = "arm64"
                #else
                let architecture = "x86_64"
                #endif
                let python = resourceDirectory.appendingPathComponent("runtime/\(architecture)/python/bin/python3")
                let launcher = resourceDirectory.appendingPathComponent("python-app/elichika_macos.py")
                guard FileManager.default.isExecutableFile(atPath: python.path),
                      FileManager.default.fileExists(atPath: launcher.path) else {
                    throw NativeError.service("The app is missing its bundled Python runtime. Download the complete Elichika.app package.")
                }
                let child = Process()
                child.executableURL = python
                child.arguments = ["-I", "-B", launcher.path, "--resources", resourceDirectory.path,
                                   "--data-dir", dataDirectory.path, "--sukusta-dir", libraryDirectory,
                                   "--lang", language, "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
                child.currentDirectoryURL = dataDirectory
                var environment = ProcessInfo.processInfo.environment
                for key in Array(environment.keys) where key.hasPrefix("DYLD_") || key == "PYTHONPATH" || key == "PYTHONHOME" {
                    environment.removeValue(forKey: key)
                }
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                environment["PYTHONNOUSERSITE"] = "1"
                environment["PYTHONUNBUFFERED"] = "1"
                child.environment = environment
                let output = Pipe(), errors = Pipe()
                outputPipe = output; errorPipe = errors
                child.standardOutput = output; child.standardError = errors
                readers = [PipeLines(handle: output.fileHandleForReading) { [weak self] line in
                    Task { @MainActor in self?.consume(line, readinessAllowed: true) }
                }, PipeLines(handle: errors.fileHandleForReading) { [weak self] line in
                    Task { @MainActor in self?.consume(line, readinessAllowed: false) }
                }]
                child.terminationHandler = { [weak self] ended in
                    Task { @MainActor in self?.runtimeExited(pid: ended.processIdentifier, status: ended.terminationStatus) }
                }
                process = child
                try child.run()
                appendLog(text("Preparing bundled tools…", "내장 도구를 준비하고 있습니다…", "内蔵ツールを準備しています…"))
                Task { [weak self] in
                    try? await Task.sleep(nanoseconds: 120_000_000_000)
                    guard let self, self.connection == nil, !self.quitting, self.process?.isRunning == true else { return }
                    self.message = NativeError.timeout("the bundled tools").localizedDescription
                }
            } catch {
                launching = false
                message = error.localizedDescription
                appendLog(error.localizedDescription)
            }
        }
    }

    private func consume(_ line: String, readinessAllowed: Bool) {
        if line.hasPrefix("ELICHIKA_READY ") {
            // Readiness carries capabilities. Never put it in the visible/file console.
            guard readinessAllowed, connection == nil else { return }
            do {
                let ready = try JSONDecoder().decode(RuntimeReady.self, from: Data(line.dropFirst("ELICHIKA_READY ".count).utf8))
                try ready.validate()
                guard let child = process, child.isRunning, getpgid(child.processIdentifier) == child.processIdentifier else {
                    throw NativeError.invalidReadiness
                }
                verifiedGroup = child.processIdentifier
                connection = ready
                launching = false
                appendLog(text("Local tools are ready.", "로컬 도구가 준비됐습니다.", "ローカルツールの準備ができました。"))
                polling = Task { [weak self] in
                    while !Task.isCancelled {
                        guard let self, !self.quitting else { return }
                        await self.refresh()
                        try? await Task.sleep(nanoseconds: 700_000_000)
                    }
                }
                if smokeDirectory != nil, !smokeStarted {
                    smokeStarted = true
                    Task { await NativeSmokeTest(model: self).run() }
                }
            } catch {
                message = error.localizedDescription
                appendLog(error.localizedDescription)
                terminateOwnedRuntime()
            }
            return
        }
        appendLog(line)
    }

    func appendLog(_ line: String) {
        let bounded = String(line.prefix(4096))
        console.append(bounded)
        if console.count > 1500 { console.removeFirst(console.count - 1500) }
    }

    private func runtimeExited(pid: Int32, status: Int32) {
        guard process?.processIdentifier == pid else { return }
        polling?.cancel()
        launching = false
        if !quitting && !stoppingRuntime {
            message = NativeError.runtimeExited.localizedDescription
            appendLog("Runtime exited (\(status)).")
            Task { await stopRuntime() }
        }
    }

    func request(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> Data {
        guard let ready = connection, let origin = TrustedOrigin(ready.controlURL),
              let url = URL(string: path, relativeTo: ready.controlURL)?.absoluteURL, origin.contains(url) else {
            throw NativeError.runtimeUnavailable
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = path == "/v1/shutdown" ? 2 : 15
        request.httpMethod = method
        request.setValue("Bearer " + ready.token, forHTTPHeaderField: "Authorization")
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body ?? [:])
        }
        let (data, response) = try await http.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw NativeError.invalidResponse }
        guard (200...299).contains(response.statusCode) else {
            let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw NativeError.service(value?["error"] as? String ?? "The local operation failed (\(response.statusCode)).")
        }
        guard data.count <= 2_097_152 else { throw NativeError.invalidResponse }
        return data
    }

    func refresh() async {
        guard connection != nil, !quitting else { return }
        do {
            let previousGoURL = snapshot.server?.url
            let previousRunning = snapshot.serverRunning
            snapshot = try JSONDecoder().decode(RuntimeState.self, from: await request("/v1/state"))
            if previousGoURL != snapshot.server?.url || previousRunning != snapshot.serverRunning { clearGoBrowsers() }
            if snapshot.prepared && networkApplied == nil { await loadNetworkConfig() }
            let logs = try JSONDecoder().decode(RuntimeLogs.self, from: await request("/v1/logs?after=\(logCursor)"))
            logs.entries.forEach { appendLog($0.line) }
            logCursor = logs.next
            let currentError = snapshot.error ?? snapshot.server?.error
            if let error = currentError, !error.isEmpty, error != reportedRuntimeError { message = error }
            reportedRuntimeError = currentError
        } catch {
            if process?.isRunning != true { message = error.localizedDescription }
        }
    }

    func toggleServer() {
        guard toolsReady, !snapshot.busy, !stoppingRuntime else { return }
        Task {
            do {
                _ = try await request(snapshot.serverRunning ? "/v1/server/stop" : "/v1/server/start", method: "POST")
                await refresh()
            } catch { message = error.localizedDescription }
        }
    }

    func authorize(_ urls: [URL]) async throws -> [String] {
        guard !urls.isEmpty, urls.count <= 128, urls.allSatisfy(\.isFileURL) else { throw NativeError.deniedPath }
        let canonical = urls.map { $0.resolvingSymlinksInPath().standardizedFileURL }
        let data = try await request("/v1/files/authorize", method: "POST", body: ["paths": canonical.map(\.path)])
        let response = try JSONDecoder().decode(AuthorizedFiles.self, from: data)
        guard response.paths == canonical.map(\.path) else { throw NativeError.invalidResponse }
        for path in response.paths {
            var directory: ObjCBool = false
            guard path.hasPrefix("/"), FileManager.default.fileExists(atPath: path, isDirectory: &directory) else { throw NativeError.deniedPath }
            if directory.boolValue { approvedDirectories.insert(path) } else { approvedFiles.insert(path) }
        }
        return response.paths
    }

    func reveal(_ path: String) throws {
        let url = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        let roots = [dataDirectory.path, libraryDirectory] + Array(approvedDirectories)
        guard approvedFiles.contains(url.path) || roots.contains(where: { url.path == $0 || url.path.hasPrefix($0 + "/") }),
              FileManager.default.fileExists(atPath: url.path) else { throw NativeError.deniedPath }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func browser(_ route: BrowserRoute) -> BrowserSession {
        if let existing = browsers[route] { return existing }
        let session = BrowserSession(model: self, route: route)
        browsers[route] = session
        return session
    }

    var assetWebView: WKWebView? { browsers[.assets]?.webView }

    func goURL(path: String) -> URL? {
        guard snapshot.serverRunning, snapshot.server?.httpReady == true,
              let raw = snapshot.server?.url, let base = URL(string: raw),
              let components = URLComponents(url: base, resolvingAgainstBaseURL: false),
              let port = components.port, (1...65535).contains(port), base.scheme == "http",
              base.user == nil, base.password == nil else { return nil }
        let rawHost = (base.host ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        let literal = rawHost == "localhost" ? "127.0.0.1" : rawHost
        guard IPAddress.isLiteral(literal) else { return nil }
        let normalized = ["0.0.0.0", "localhost"].contains(rawHost) ? "127.0.0.1" : rawHost == "::" ? "::1" : literal
        let host = normalized.contains(":") ? "[\(normalized)]" : normalized
        return URL(string: "http://\(host):\(port)" + path)
    }

    func loadNetworkConfig() async {
        do {
            let value = try JSONDecoder().decode(ServerNetworkConfig.self, from: await request("/v1/server/config"))
            networkApplied = value; serverAddressDraft = value.serverAddress; cdnServerDraft = value.cdnServer
        } catch { appendLog(error.localizedDescription) }
    }

    func saveNetworkConfig() {
        guard canChangeStorage, !savingNetwork else { return }
        savingNetwork = true
        let body = ["server_address": serverAddressDraft, "cdn_server": cdnServerDraft]
        Task {
            defer { savingNetwork = false }
            do {
                let value = try JSONDecoder().decode(ServerNetworkConfig.self, from: await request("/v1/server/config", method: "POST", body: body))
                networkApplied = value; serverAddressDraft = value.serverAddress; cdnServerDraft = value.cdnServer
                clearGoBrowsers()
            } catch { message = error.localizedDescription }
        }
    }

    private func clearGoBrowsers() {
        for route in [BrowserRoute.accounts, .serverSettings] { browsers.removeValue(forKey: route)?.dispose() }
    }

    func perform(_ action: String) {
        guard ["openModel", "saveModel", "showViewer"].contains(action), toolsReady else { return }
        selectedSection = .assets
        let session = browser(.assets)
        session.perform(action)
    }

    func openDocuments(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        selectedSection = .assets
        launch()
        Task {
            do {
                try await waitForTools()
                let paths = try await authorize(urls)
                browser(.assets).perform("openModel", paths: paths)
            } catch { message = error.localizedDescription }
        }
    }

    private func waitForTools() async throws {
        let deadline = Date().addingTimeInterval(420)
        while true {
            switch RuntimePreparationGate.evaluate(ready: toolsReady, launching: launching,
                    running: process?.isRunning == true, failed: snapshot.phase == "error",
                    stopping: stoppingRuntime || quitting) {
            case .ready: return
            case .unavailable: throw NativeError.runtimeUnavailable
            case .waiting:
                guard Date() < deadline else { throw NativeError.timeout("the bundled tools") }
                try await Task.sleep(nanoseconds: 100_000_000)
            }
        }
    }

    func chooseLibraryDirectory() {
        guard canChangeStorage else { return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true
        panel.directoryURL = URL(fileURLWithPath: libraryDirectory, isDirectory: true)
        panel.title = text("Choose asset library", "에셋 보관 폴더 선택", "アセット保存先を選択")
        panel.begin { [weak self] response in
            Task { @MainActor in
                guard let self, response == .OK, let url = panel.url else { return }
                guard self.canChangeStorage else { return }
                let path = url.resolvingSymlinksInPath().path
                guard path != self.libraryDirectory else { return }
                let alert = NSAlert()
                alert.messageText = self.text("Change asset folder?", "에셋 보관 폴더를 바꿀까요?", "アセット保存先を変更しますか？")
                alert.informativeText = self.text("The asset tools restart and the current editor closes. Save edited models before continuing. Existing files stay in the previous folder; copy them to the new folder if needed.", "도구가 다시 시작되고 현재 편집기가 닫힙니다. 계속하기 전에 편집한 모델을 저장하세요. 기존 파일은 이전 폴더에 남으므로 필요하면 새 폴더로 복사하세요.", "ツールを再起動し、現在のエディターを閉じます。続ける前に編集したモデルを保存してください。既存ファイルは以前のフォルダーに残るため、必要なら新しいフォルダーへコピーしてください。")
                alert.addButton(withTitle: self.text("Change folder", "폴더 변경", "フォルダーを変更"))
                alert.addButton(withTitle: self.text("Cancel", "취소", "キャンセル"))
                guard alert.runModal() == .alertFirstButtonReturn, self.canChangeStorage else { return }
                self.libraryDirectory = path
                UserDefaults.standard.set(self.libraryDirectory, forKey: "libraryDirectory")
                await self.restartTools()
            }
        }
    }

    func setLanguage(_ value: String) {
        guard ["en", "ko", "ja"].contains(value), value != language else { return }
        language = value
        UserDefaults.standard.set(value, forKey: "language")
        browsers.values.forEach { $0.setLanguage(value) }
    }

    private func restartTools() async {
        guard canChangeStorage else { return }
        await stopRuntime()
        guard !quitting else { return }
        browsers.values.forEach { $0.dispose() }; browsers.removeAll()
        connection = nil; snapshot = RuntimeState(); logCursor = 0; networkApplied = nil
        started = false
        launch()
    }

    func retryTools() {
        guard canChangeStorage else { return }
        message = nil
        Task { await restartTools() }
    }

    func stopRuntime() async {
        if stoppingRuntime {
            while stoppingRuntime { try? await Task.sleep(nanoseconds: 50_000_000) }
            return
        }
        stoppingRuntime = true
        defer { stoppingRuntime = false }
        polling?.cancel()
        if connection != nil && process?.isRunning == true { _ = try? await request("/v1/shutdown", method: "POST") }
        let deadline = Date().addingTimeInterval(8)
        while process?.isRunning == true && Date() < deadline { try? await Task.sleep(nanoseconds: 50_000_000) }
        terminateOwnedRuntime()
        let killDeadline = Date().addingTimeInterval(2)
        while let group = verifiedGroup, Darwin.kill(-group, 0) == 0, Date() < killDeadline {
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        if let group = verifiedGroup, Darwin.kill(-group, 0) == 0 { _ = Darwin.kill(-group, SIGKILL) }
        if process?.isRunning == true { process?.terminate() }
        readers.forEach { $0.stop() }; readers.removeAll()
        verifiedGroup = nil
        process = nil
    }

    private func terminateOwnedRuntime() {
        if let group = verifiedGroup { _ = Darwin.kill(-group, SIGTERM) }
        else if process?.isRunning == true { process?.terminate() }
    }

    func quit(completion: @escaping () -> Void) {
        guard !quitting else { return }
        quitting = true
        Task {
            await stopRuntime()
            let observer = smokeQuitObserver; smokeQuitObserver = nil
            await observer?()
            completion()
        }
    }
}

private final class LocalControlSessionDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // Authenticated local control endpoints never redirect, especially to another origin.
        completionHandler(nil)
    }
}

/// Pipe callbacks never mutate UI state and keep complete UTF-8 lines together.
private final class PipeLines {
    private let handle: FileHandle
    private var buffered = Data()
    private let lock = NSLock()
    init(handle: FileHandle, consume: @escaping (String) -> Void) {
        self.handle = handle
        handle.readabilityHandler = { [weak self] source in
            guard let self else { return }
            let bytes = source.availableData
            self.lock.lock()
            self.buffered.append(bytes)
            var lines: [String] = []
            while let newline = self.buffered.firstIndex(of: 10) {
                let line = self.buffered[..<newline]
                if line.count <= 65_536 { lines.append(String(decoding: line, as: UTF8.self)) }
                self.buffered.removeSubrange(...newline)
            }
            if self.buffered.count > 65_536 { self.buffered.removeAll() }
            self.lock.unlock()
            lines.forEach(consume)
            if bytes.isEmpty { source.readabilityHandler = nil }
        }
    }
    func stop() { handle.readabilityHandler = nil; try? handle.close() }
}
