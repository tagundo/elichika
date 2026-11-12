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
    @Published var cdnServerDraft = ""
    @Published private(set) var savingNetwork = false
    @Published private(set) var consoleState: ConsoleState?
    @Published private(set) var submittingConsoleAction = false
    @Published private(set) var cancellingConsoleAction = false
    @Published var consolePresentation: ConsolePresentation?
    @Published var consoleRegion: ConsoleRegion = .gl
    @Published private(set) var consoleResetFinal = false
    @Published private(set) var consoleActionError: String?
    @Published private(set) var resetSubmissionUncertain = false
    @Published private(set) var goBrowserRevision: UInt64 = 0

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
    private var managementDemandWanted = false
    private var managementDemandRevision = 0
    private var managementDemandTask: Task<Void, Never>?
    private var managementAdmissionUncertain = false
    private var stateRequestSequence: UInt64 = 0
    private var appliedStateSequence: UInt64 = 0
    private var stateEpoch: UInt64 = 0
    private var uncertainResetPreviousJobID: String?
    private let http: URLSession
    var smokeQuitObserver: (() async -> Void)?
    var smokeEvent: ((String) -> Void)?

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
        if smokeDirectory != nil { selectedSection = .viewer }
    }

    func text(_ en: String, _ ko: String, _ ja: String) -> String {
        NativeText.value(en, ko, ja, language: language)
    }

    var toolsReady: Bool { connection != nil && process?.isRunning == true && snapshot.prepared && snapshot.phase != "error" && !stoppingRuntime }
    var canChangeStorage: Bool { !snapshot.busy && !snapshot.serverRunning && !quitting && !launching && !stoppingRuntime && !submittingConsoleAction && !resetSubmissionUncertain && consoleState?.job?.running != true }
    var canControlServer: Bool { toolsReady && !snapshot.busy && !submittingConsoleAction && !resetSubmissionUncertain && !quitting && consoleState?.job?.running != true }
    var canRunConsoleAction: Bool { canControlServer }
    var preparationStatusTitle: String {
        if snapshot.phase == "error" { return text("Preparation failed", "준비하지 못했습니다", "準備できませんでした") }
        switch snapshot.progress?.stage {
        case "recovering": return text("Checking interrupted updates…", "중단된 갱신 확인 중…", "中断された更新を確認中…")
        case "copying_data": return text("Preparing game data…", "게임 데이터 준비 중…", "ゲームデータを準備中…")
        case "validating": return text("Checking game data…", "게임 데이터 확인 중…", "ゲームデータを確認中…")
        case "snapshot": return text("Backing up game data…", "게임 데이터 백업 중…", "ゲームデータをバックアップ中…")
        case "merging": return text("Merging data and preserving mods…", "모드를 보존하며 DB 병합 중…", "Modを維持してデータを統合中…")
        case "verifying": return text("Verifying updated data…", "병합 결과 검증 중…", "更新データを検証中…")
        case "publishing": return text("Applying verified data…", "검증된 데이터 적용 중…", "検証済みデータを適用中…")
        case "complete": return text("Game-data update complete", "게임 데이터 갱신 완료", "ゲームデータ更新完了")
        case "same_data": return text("Game data is already current", "게임 데이터가 최신입니다", "ゲームデータは最新です")
        default: return text("Preparing bundled tools…", "내장 도구 준비 중…", "内蔵ツールを準備中…")
        }
    }
    var serverStatusTitle: String {
        if snapshot.phase == "preparing" {
            return preparationStatusTitle + (snapshot.preparationPercent.map { " \($0)%" } ?? "")
        }
        if snapshot.serverLoading { return text("Server loading…", "서버 로딩 중…", "サーバー読み込み中…") }
        return snapshot.serverRunning ? text("Server running", "서버 실행 중", "サーバー実行中") : text("Server stopped", "서버 중지됨", "サーバー停止中")
    }
    var networkReady: Bool { networkApplied != nil }
    var networkChanged: Bool {
        guard let networkApplied else { return false }
        return networkApplied.serverAddress != serverAddressDraft || networkApplied.cdnServer != cdnServerDraft
    }
    var defaultCdnServer: String? { networkApplied?.defaultCdnServer }
    var connectionAddress: String? { networkApplied?.localServerURL?.absoluteString }

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
        clearGoBrowsers()
        snapshot.progress = nil
        snapshot.busy = false
        snapshot.serverRunning = false
        consoleState = nil
        resetSubmissionUncertain = false
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
        guard connection != nil, !quitting, !stoppingRuntime else { return }
        let runtimePID = process?.processIdentifier
        let stateRequest = beginRuntimeStateRequest()
        do {
            let updated = try JSONDecoder().decode(RuntimeState.self, from: await request("/v1/state"))
            guard !quitting, !stoppingRuntime, process?.processIdentifier == runtimePID else { return }
            guard applyRuntimeState(updated, for: stateRequest) else { return }
            if let value = updated.console { consoleState = value }
            else if snapshot.prepared {
                let value = try JSONDecoder().decode(ConsoleState.self, from: await request("/v1/console"))
                guard stateRequestIsCurrent(stateRequest) else { return }
                consoleState = value
            }
            if resetSubmissionUncertain, !submittingConsoleAction, let job = consoleState?.job,
               job.action == .resetServer, job.id != uncertainResetPreviousJobID {
                // A new reset job proves that the lost submission was accepted.
                resetSubmissionUncertain = false
                if consolePresentation?.action == .resetServer { dismissConsolePresentation() }
            }
            if !managementPageVisible && snapshot.management?.running == true && snapshot.management?.status != "stopping" && managementDemandTask == nil {
                queueManagementDemand(false)
            }
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
        guard canControlServer else { return }
        Task {
            do {
                _ = try await request(snapshot.serverRunning ? "/v1/server/stop" : "/v1/server/start", method: "POST")
                await refresh()
            } catch { message = error.localizedDescription }
        }
    }

    func runConsoleAction(_ action: ConsoleAction, region: ConsoleRegion? = nil) async throws {
        guard canRunConsoleAction else {
            throw NativeError.service(text("Wait for the current operation to finish.", "현재 작업이 끝날 때까지 기다리세요.", "現在の処理が終わるまでお待ちください。"))
        }
        submittingConsoleAction = true
        defer { submittingConsoleAction = false }
        let body = action.requestBody(region: region)
        // A lost POST response may still mean the irreversible reset started.
        // Retain that uncertainty until a successful shutdown gates admission.
        if action == .resetServer {
            uncertainResetPreviousJobID = consoleState?.job?.id
            resetSubmissionUncertain = true
        }
        do {
            consoleState = try JSONDecoder().decode(ConsoleState.self,
                from: await request("/v1/console/run", method: "POST", body: body))
        } catch {
            if let nativeError = error as? NativeError {
                switch nativeError {
                case .service, .runtimeUnavailable: resetSubmissionUncertain = false
                default: break
                }
            }
            throw error
        }
        if action == .resetServer { resetSubmissionUncertain = false }
        await refresh()
    }

    func presentConsole(_ presentation: ConsolePresentation) {
        guard presentation.action == nil || canRunConsoleAction else { return }
        consoleRegion = ConsoleRegion.defaultRegion(language: language)
        consoleResetFinal = false
        consoleActionError = nil
        consolePresentation = presentation
    }

    func dismissConsolePresentation() {
        guard !submittingConsoleAction else { return }
        consolePresentation = nil
        consoleResetFinal = false
        consoleActionError = nil
    }

    @discardableResult
    func confirmConsoleAction() async -> Bool {
        guard let action = consolePresentation?.action, canRunConsoleAction else { return false }
        if action == .resetServer && !consoleResetFinal { consoleResetFinal = true; return false }
        do {
            try await runConsoleAction(action, region: action == .downloadArchive ? consoleRegion : nil)
            dismissConsolePresentation()
            return true
        } catch {
            consoleActionError = error.localizedDescription + (resetSubmissionUncertain
                ? "\n" + text("Checking whether the reset started before allowing another action…", "다른 작업을 허용하기 전에 초기화 시작 여부를 확인합니다…", "次の操作を許可する前に、初期化が開始されたか確認しています…") : "")
            return false
        }
    }

    func cancelConsoleAction() {
        guard consoleState?.job?.running == true, consoleState?.job?.cancellable == true,
              consoleState?.job?.status != "cancelling", !cancellingConsoleAction else { return }
        cancellingConsoleAction = true
        Task {
            defer { cancellingConsoleAction = false }
            do {
                consoleState = try JSONDecoder().decode(ConsoleState.self,
                    from: await request("/v1/console/cancel", method: "POST"))
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

    func assetSectionChanged(_ section: AssetEditorSection) {
        // Keep a hidden editor's delayed event from stealing focus from the
        // server, account or settings destination.
        guard selectedSection?.assetEditorSection != nil,
              selectedSection != section.appSection else { return }
        selectedSection = section.appSection
    }

    func goURL(path: String) -> URL? {
        snapshot.webUIURL(path: path)
    }

    struct RuntimeStateRequest {
        fileprivate let sequence: UInt64
        fileprivate let epoch: UInt64
        fileprivate let runtimePID: Int32?
    }

    func beginRuntimeStateRequest() -> RuntimeStateRequest {
        stateRequestSequence &+= 1
        return RuntimeStateRequest(sequence: stateRequestSequence, epoch: stateEpoch,
                                   runtimePID: process?.processIdentifier)
    }

    @discardableResult
    func applyRuntimeState(_ value: RuntimeState, for request: RuntimeStateRequest) -> Bool {
        guard request.epoch == stateEpoch, request.sequence > appliedStateSequence,
              request.runtimePID == process?.processIdentifier else { return false }
        // Awaiting a response can let another request publish a ready browser.
        // Compare the live state, and invalidate before SwiftUI sees a new URL.
        if goURL(path: "/webui/admin/") != value.webUIURL(path: "/webui/admin/") {
            disposeGoBrowsers()
        }
        appliedStateSequence = request.sequence
        snapshot = value
        return true
    }

    private func stateRequestIsCurrent(_ request: RuntimeStateRequest) -> Bool {
        request.epoch == stateEpoch && request.sequence == appliedStateSequence
            && request.runtimePID == process?.processIdentifier
    }

    func retryManagement() {
        guard managementPageVisible, toolsReady, !snapshot.busy, !snapshot.serverRunning else { return }
        queueManagementDemand(true)
    }

    func releaseManagementIfNotVisible() {
        guard !managementPageVisible, toolsReady else { return }
        queueManagementDemand(false)
    }

    private var managementPageVisible: Bool {
        selectedSection == .accounts || (selectedSection == .settings && showServerSettings)
    }

    var managementDemandIdle: Bool { managementDemandTask == nil }

    private func queueManagementDemand(_ wanted: Bool) {
        managementDemandWanted = wanted
        managementDemandRevision &+= 1
        guard managementDemandTask == nil else { return }
        managementDemandTask = Task { [weak self] in
            guard let self else { return }
            defer { self.managementDemandTask = nil }
            while self.connection != nil && self.process?.isRunning == true {
                let revision = self.managementDemandRevision
                let wantedNow = self.managementDemandWanted && self.managementPageVisible && !self.stoppingRuntime && !self.quitting
                if wantedNow && (!self.toolsReady || self.snapshot.busy || self.snapshot.serverRunning) { return }
                if wantedNow { self.managementAdmissionUncertain = true }
                let stateRequest = self.beginRuntimeStateRequest()
                do {
                    self.smokeEvent?(wantedNow ? "management-demand-start-requested" : "management-demand-stop-requested")
                    let value = try JSONDecoder().decode(RuntimeState.self,
                        from: await self.request(wantedNow ? "/v1/management/start" : "/v1/management/stop", method: "POST"))
                    self.smokeEvent?(wantedNow ? "management-demand-start-acknowledged" : "management-demand-stop-acknowledged")
                    let applied = self.applyRuntimeState(value, for: stateRequest)
                    // The command was acknowledged even when a newer state
                    // body won the race. Always reconcile its real demand.
                    if !wantedNow && value.management?.running != true &&
                        (applied || self.snapshot.management?.running != true) {
                        self.managementAdmissionUncertain = false
                    }
                } catch {
                    if wantedNow && revision == self.managementDemandRevision && self.managementPageVisible {
                        self.message = error.localizedDescription
                    }
                }
                let latest = self.managementDemandWanted && self.managementPageVisible && !self.stoppingRuntime && !self.quitting
                if latest != wantedNow {
                    self.managementDemandWanted = latest
                    self.managementDemandRevision &+= 1
                    continue
                }
                if revision == self.managementDemandRevision { return }
            }
        }
    }

    func loadNetworkConfig() async {
        do {
            let value = try JSONDecoder().decode(ServerNetworkConfig.self, from: await request("/v1/server/config"))
            networkApplied = value; serverAddressDraft = value.serverAddress; cdnServerDraft = value.cdnServer
        } catch { appendLog(error.localizedDescription) }
    }

    func saveNetworkConfig() {
        guard canChangeStorage, networkReady, !savingNetwork else { return }
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

    func clearGoBrowsers() {
        // An explicit same-origin reload must fence responses begun before it
        // and tell the visible panel to use the newly cached session identity.
        stateEpoch &+= 1
        disposeGoBrowsers()
        goBrowserRevision &+= 1
    }

    private func disposeGoBrowsers() {
        for route in [BrowserRoute.accounts, .serverSettings] { browsers.removeValue(forKey: route)?.dispose() }
    }

    func perform(_ action: String) {
        guard ["openModel", "saveModel", "showViewer"].contains(action), toolsReady else { return }
        selectedSection = .viewer
        let session = browser(.assets)
        session.setEditorSurface(.viewer)
        session.perform(action)
    }

    func openDocuments(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        selectedSection = .viewer
        launch()
        Task {
            do {
                try await waitForTools()
                let paths = try await authorize(urls)
                let session = browser(.assets)
                session.setEditorSurface(.viewer)
                session.perform("openModel", paths: paths)
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
        smokeEvent?("runtime-stop-entered")
        if stoppingRuntime {
            smokeEvent?("runtime-stop-awaiting-existing-stop")
            while stoppingRuntime { try? await Task.sleep(nanoseconds: 50_000_000) }
            return
        }
        stoppingRuntime = true
        snapshot.progress = nil
        defer { stoppingRuntime = false }
        polling?.cancel()
        queueManagementDemand(false)
        if let demand = managementDemandTask { await demand.value }
        // A reset restores vanilla data and then resets accounts. Gate new
        // admission with shutdown, then await both phases before any group kill.
        while submittingConsoleAction { try? await Task.sleep(nanoseconds: 100_000_000) }
        var resetRunning = resetSubmissionUncertain || (consoleState?.job?.action == .resetServer && consoleState?.job?.running == true)
        var managementRunning = managementAdmissionUncertain || snapshot.management?.running == true
        var shutdownAcknowledged = false
        if connection != nil && process?.isRunning == true {
            smokeEvent?("runtime-shutdown-request")
            repeat {
                do {
                    _ = try await request("/v1/shutdown", method: "POST")
                    shutdownAcknowledged = true
                } catch {
                    if (resetRunning || managementRunning) && process?.isRunning == true { try? await Task.sleep(nanoseconds: 500_000_000) }
                }
            } while (resetRunning || managementRunning) && !shutdownAcknowledged && process?.isRunning == true
            smokeEvent?("runtime-shutdown-response")
        }
        while resetRunning && process?.isRunning == true {
            message = text("Finishing the server reset safely before quitting…", "서버 초기화를 안전하게 완료한 뒤 종료합니다…", "サーバー初期化を安全に完了してから終了します…")
            do {
                let value = try JSONDecoder().decode(ConsoleState.self, from: await request("/v1/console"))
                consoleState = value
                resetRunning = value.job?.action == .resetServer && value.job?.running == true
                resetSubmissionUncertain = false
            } catch { /* Never escalate an uncertain or active reset. */ }
            if resetRunning { try? await Task.sleep(nanoseconds: 500_000_000) }
        }
        while managementRunning && process?.isRunning == true {
            message = text("Finishing management changes safely before quitting…", "관리 작업을 안전하게 완료한 뒤 종료합니다…", "管理処理を安全に完了してから終了します…")
            do {
                let stateRequest = beginRuntimeStateRequest()
                let value = try JSONDecoder().decode(RuntimeState.self, from: await request("/v1/state"))
                _ = applyRuntimeState(value, for: stateRequest)
                managementRunning = value.management?.running == true
                managementAdmissionUncertain = managementRunning
            } catch { /* An owned management write must not be force-killed while its state is uncertain. */ }
            if managementRunning { try? await Task.sleep(nanoseconds: 500_000_000) }
        }
        let deadline = Date().addingTimeInterval(8)
        while process?.isRunning == true && Date() < deadline { try? await Task.sleep(nanoseconds: 50_000_000) }
        smokeEvent?("runtime-stop-grace-period-finished")
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
        consoleState = nil
        resetSubmissionUncertain = false
        managementAdmissionUncertain = false
        smokeEvent?("runtime-stop-finished")
    }

    private func terminateOwnedRuntime() {
        if let group = verifiedGroup { _ = Darwin.kill(-group, SIGTERM) }
        else if process?.isRunning == true { process?.terminate() }
    }

    func quit(completion: @escaping () -> Void) {
        smokeEvent?("native-quit-received")
        guard !quitting else { return }
        quitting = true
        Task {
            smokeEvent?("native-quit-task-started")
            await stopRuntime()
            let observer = smokeQuitObserver; smokeQuitObserver = nil
            await observer?()
            smokeEvent?("native-quit-cleanup-complete")
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
