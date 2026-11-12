import Foundation
import Darwin

struct RuntimeReady: Decodable {
    let controlURL: URL
    let adminURL: URL
    let toolsURL: URL
    let token: String
    let uiToken: String
    let dataDirectory: String
    let sukustaDirectory: String

    enum CodingKeys: String, CodingKey {
        case controlURL = "control_url", adminURL = "admin_url", toolsURL = "tools_url"
        case token, uiToken = "ui_token", dataDirectory = "data_dir", sukustaDirectory = "sukusta_dir"
    }

    func validate() throws {
        for url in [controlURL, adminURL, toolsURL] {
            guard TrustedOrigin(url) != nil else { throw NativeError.invalidReadiness }
        }
        guard Set([controlURL.port, adminURL.port, toolsURL.port]).count == 3,
              token.utf8.count >= 24, uiToken.utf8.count >= 24, token != uiToken,
              dataDirectory.hasPrefix("/"), sukustaDirectory.hasPrefix("/") else {
            throw NativeError.invalidReadiness
        }
    }
}

struct TrustedOrigin: Equatable, Hashable {
    let port: Int

    init?(_ url: URL) {
        guard url.scheme == "http", url.host == "127.0.0.1", url.user == nil, url.password == nil,
              let port = url.port, (1...65535).contains(port) else { return nil }
        self.port = port
    }

    func contains(_ url: URL) -> Bool { TrustedOrigin(url) == self }
}

struct RuntimeState: Decodable {
    var phase = "preparing"
    var serverRunning = false
    var busy = false
    var prepared = false
    var error: String?
    var progress: ProgressState?
    var server: ServerState?
    var management: ServerState?
    var console: ConsoleState?

    struct ProgressState: Decodable {
        let stage: String?
        let completed: Int?
        let total: Int?
        let current: String?

        let percent: Int?

        var displayPercent: Int? {
            guard let stage, let completed, let total, let percent,
                  total > 0, completed >= 0, completed <= total, (0...100).contains(percent) else { return nil }
            if stage == "complete" { return completed == 1 && total == 1 && percent == 100 ? 100 : nil }
            guard ["copying_data", "validating", "snapshot", "merging", "verifying", "publishing", "recovering"].contains(stage), percent < 100 else { return nil }
            return percent
        }
    }

    var serverLoading: Bool { serverRunning && server?.httpReady != true }

    func webUIURL(path: String) -> URL? {
        let source: ServerState?
        if serverRunning {
            source = server?.httpReady == true ? server : nil
        } else {
            source = management?.running == true && management?.httpReady == true ? management : nil
        }
        guard path == "/webui/admin/" || path == "/webui/user/",
              let raw = source?.url, let base = URL(string: raw),
              let components = URLComponents(url: base, resolvingAgainstBaseURL: false),
              let port = components.port, (1...65535).contains(port), base.scheme == "http",
              base.user == nil, base.password == nil, components.query == nil, components.fragment == nil,
              ["", "/"].contains(components.path) else { return nil }
        let rawHost = (base.host ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        guard serverRunning || rawHost == "127.0.0.1" else { return nil }
        let literal = rawHost == "localhost" ? "127.0.0.1" : rawHost
        guard IPAddress.isLiteral(literal) else { return nil }
        let normalized = ["0.0.0.0", "localhost"].contains(rawHost) ? "127.0.0.1" : rawHost == "::" ? "::1" : literal
        let host = normalized.contains(":") ? "[\(normalized)]" : normalized
        return URL(string: "http://\(host):\(port)" + path)
    }

    var preparationPercent: Int? {
        guard phase == "preparing", !prepared else { return nil }
        return progress?.displayPercent
    }
    struct ServerState: Decodable {
        let running: Bool?
        let pid: Int?
        let url: String?
        let status: String?
        let error: String?
        let httpReady: Bool?
        enum CodingKeys: String, CodingKey { case running, pid, url, status, error; case httpReady = "http_ready" }
    }

    enum CodingKeys: String, CodingKey { case phase, busy, prepared, error, progress, server, management, console; case serverRunning = "server_running" }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        phase = try c.decodeIfPresent(String.self, forKey: .phase) ?? "preparing"
        serverRunning = try c.decodeIfPresent(Bool.self, forKey: .serverRunning) ?? false
        busy = try c.decodeIfPresent(Bool.self, forKey: .busy) ?? false
        prepared = try c.decodeIfPresent(Bool.self, forKey: .prepared) ?? false
        error = try c.decodeIfPresent(String.self, forKey: .error)
        progress = try c.decodeIfPresent(ProgressState.self, forKey: .progress)
        server = try c.decodeIfPresent(ServerState.self, forKey: .server)
        management = try c.decodeIfPresent(ServerState.self, forKey: .management)
        console = try c.decodeIfPresent(ConsoleState.self, forKey: .console)
    }
}

struct ConsoleState: Decodable {
    var cacheEnabled: Bool?
    var job: Job?

    enum CodingKeys: String, CodingKey { case cacheEnabled = "cache_enabled", job }

    struct Job: Decodable {
        let id: String
        let action: ConsoleAction
        let region: ConsoleRegion?
        let status: String
        let running: Bool
        let cancellable: Bool
        let message: String
        let error: String?
        let progress: Progress?

        struct Progress: Decodable {
            let stage: String?
            let completed: Int?
            let total: Int?
            let current: String?
            let percent: Int?

            var fraction: Double? {
                if let completed, let total, total > 0, completed >= 0, completed <= total {
                    return Double(completed) / Double(total)
                }
                if let percent, (0...100).contains(percent) { return Double(percent) / 100 }
                return nil
            }
        }
    }
}

enum ConsoleRegion: String, CaseIterable, Identifiable, Decodable {
    case gl, jp, both
    var id: String { rawValue }
    static func defaultRegion(language: String) -> Self { language == "ja" ? .jp : .gl }
    func title(_ language: String) -> String {
        switch self {
        case .gl: return NativeText.value("GL (Global — EN / KO / ZH)", "GL (글로벌 — EN / KO / ZH)", "GL（グローバル — EN / KO / ZH）", language: language)
        case .jp: return NativeText.value("JP (Japan)", "JP (일본)", "JP（日本）", language: language)
        case .both: return NativeText.value("Both (GL + JP)", "둘 다 (GL + JP)", "両方（GL + JP）", language: language)
        }
    }
}

enum ConsoleAction: String, Decodable, Identifiable {
    case downloadArchive = "download_archive"
    case downloadPacks = "download_packs"
    case cdnCacheToggle = "cdn_cache_toggle"
    case rebuildAssets = "rebuild_assets"
    case fixTrainingTrees = "fix_training_trees"
    case resetServer = "reset_server"
    var id: String { rawValue }
    func title(_ language: String) -> String {
        let values: (String, String, String)
        switch self {
        case .downloadArchive: values = ("Download all (archive.org)…", "전체 받기 (archive.org)…", "全ファイル取得 (archive.org)…")
        case .downloadPacks: values = ("Download missing (CDN)…", "누락분 받기 (CDN)…", "不足分を取得 (CDN)…")
        case .cdnCacheToggle: values = ("CDN cache", "CDN 캐시", "CDNキャッシュ")
        case .rebuildAssets: values = ("Rebuild master data…", "마스터 데이터 재빌드…", "マスターデータ再構築…")
        case .fixTrainingTrees: values = ("Fix training trees…", "트레이닝 트리 복구…", "トレーニングツリー修復…")
        case .resetServer: values = ("Reset server (remove mods)…", "서버 초기화 (모드 제거)…", "サーバー初期化（MOD削除）…")
        }
        return NativeText.value(values.0, values.1, values.2, language: language)
    }

    func requestBody(region: ConsoleRegion? = nil) -> [String: String] {
        var body = ["action": rawValue, "confirmation": "STOP_SERVER"]
        if self == .downloadArchive, let region { body["region"] = region.rawValue }
        if self == .resetServer { body["reset_confirmation"] = "RESET_SERVER_AND_ACCOUNTS" }
        return body
    }
}

enum ConsolePresentation: Identifiable, Equatable {
    case action(ConsoleAction), guide, about
    var id: String {
        switch self {
        case .action(let action): return action.rawValue
        case .guide: return "guide"
        case .about: return "about"
        }
    }
    var action: ConsoleAction? { if case .action(let value) = self { return value }; return nil }
}

struct RuntimeLog: Decodable, Identifiable { let id: Int; let line: String }
struct RuntimeLogs: Decodable { let entries: [RuntimeLog]; let next: Int }
struct AuthorizedFiles: Decodable { let paths: [String] }

enum RuntimePreparationGate: Equatable {
    case ready, waiting, unavailable

    static func evaluate(ready: Bool, launching: Bool, running: Bool, failed: Bool, stopping: Bool) -> Self {
        guard !failed, !stopping else { return .unavailable }
        if ready { return .ready }
        // Launch queues the Process creation on the main actor; no PID exists yet.
        return launching || running ? .waiting : .unavailable
    }
}

struct AppTerminationGate {
    enum Phase { case idle, cleaning, ready }
    enum Decision: Equatable { case cleanUp, cancel, terminate }
    private(set) var phase: Phase = .idle

    mutating func request() -> Decision {
        switch phase {
        case .idle: phase = .cleaning; return .cleanUp
        case .cleaning: return .cancel
        case .ready: return .terminate
        }
    }

    mutating func cleanupFinished() {
        if case .cleaning = phase { phase = .ready }
    }
}

struct ServerNetworkConfig: Decodable, Equatable {
    let serverAddress: String
    let cdnServer: String
    let defaultCdnServer: String?
    enum CodingKeys: String, CodingKey { case serverAddress = "server_address", cdnServer = "cdn_server", defaultCdnServer = "default_cdn_server" }
    init(serverAddress: String, cdnServer: String, defaultCdnServer: String? = nil) {
        self.serverAddress = serverAddress; self.cdnServer = cdnServer; self.defaultCdnServer = defaultCdnServer
    }
    var localServerURL: URL? {
        let normalized = serverAddress.hasPrefix(":") ? "0.0.0.0" + serverAddress : serverAddress
        guard let value = URLComponents(string: "http://" + normalized),
              let host = value.host, value.user == nil, value.password == nil,
              value.path.isEmpty, value.query == nil, value.fragment == nil,
              let port = value.port, (1...65535).contains(port) else { return nil }
        let rawHost = host.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        let local = ["0.0.0.0", "localhost"].contains(rawHost) ? "127.0.0.1" : rawHost == "::" ? "::1" : rawHost
        guard IPAddress.isLiteral(local) else { return nil }
        let formatted = local.contains(":") ? "[\(local)]" : local
        return URL(string: "http://\(formatted):\(port)")
    }
}

enum IPAddress {
    static func isLiteral(_ value: String) -> Bool {
        var v4 = in_addr(), v6 = in6_addr()
        return value.withCString { inet_pton(AF_INET, $0, &v4) == 1 || inet_pton(AF_INET6, $0, &v6) == 1 }
    }
}

struct NativeRequest: Decodable {
    // The viewer clamps the actual pane to the available window width. This
    // bound validates persisted preferences without imposing a desktop UI cap.
    static let viewerPanelWidthRange = 240...16_384
    enum Action: String, Decodable { case openFiles, chooseDirectory, reveal, setFullscreen, setLanguage, setViewerPanelWidth, setViewerFilesWidth, setPanelSettings, setEditorSurface, setSection }
    let id: String
    let action: Action
    let multiple: Bool?
    let extensions: [String]?
    let title: String?
    let path: String?
    let enabled: Bool?
    let language: String?
    let width: Int?
    let panelScope: String?
    let panelSettings: PanelPreferences?
    let editorSurface: EditorSurface?
    let section: String?
    let event: String?

    struct PanelPreferences: Codable {
        let hidden: [String]
        let order: [String]
        var isValid: Bool {
            [hidden, order].allSatisfy { values in
                values.count <= 256 && Set(values).count == values.count && values.allSatisfy { value in
                    (1...128).contains(value.utf8.count) &&
                    value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil
                }
            }
        }
    }

    static func parse(_ body: Any) throws -> NativeRequest {
        guard JSONSerialization.isValidJSONObject(body) else { throw NativeError.invalidMessage }
        let data = try JSONSerialization.data(withJSONObject: body)
        guard data.count <= 32_768 else { throw NativeError.invalidMessage }
        let request = try JSONDecoder().decode(NativeRequest.self, from: data)
        guard (1...96).contains(request.id.utf8.count),
              request.id.unicodeScalars.allSatisfy({ CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_:.")).contains($0) }),
              (request.extensions?.count ?? 0) <= 32, (request.title?.utf8.count ?? 0) <= 1024,
              (request.path?.utf8.count ?? 0) <= 16_384 else { throw NativeError.invalidMessage }
        if request.action == .setViewerPanelWidth {
            guard let width = request.width, width == 0 || viewerPanelWidthRange.contains(width) else { throw NativeError.invalidMessage }
        } else if request.action == .setViewerFilesWidth {
            guard let width = request.width, width == 0 || (160...360).contains(width) else { throw NativeError.invalidMessage }
        } else if request.action == .setEditorSurface {
            guard request.editorSurface != nil else { throw NativeError.invalidMessage }
        } else if request.action == .setSection {
            guard let section = request.section, AssetEditorSection(rawValue: section) != nil else { throw NativeError.invalidMessage }
            if let event = request.event, AssetSectionEvent(rawValue: event) == nil { throw NativeError.invalidMessage }
        } else if request.action == .setPanelSettings {
            guard let scope = request.panelScope, ["viewer", "tools", "content"].contains(scope),
                  let settings = request.panelSettings, settings.isValid else { throw NativeError.invalidMessage }
        }
        return request
    }
}

enum NativeError: LocalizedError {
    case invalidReadiness, invalidMessage, runtimeUnavailable, invalidResponse, deniedPath, runtimeExited, timeout(String)
    case service(String)
    var errorDescription: String? {
        switch self {
        case .invalidReadiness: return "The bundled runtime returned an invalid local endpoint."
        case .invalidMessage: return "The requested native action is invalid."
        case .runtimeUnavailable: return "The local tools are not ready."
        case .invalidResponse: return "The local runtime returned an invalid response."
        case .deniedPath: return "Choose this file or folder before opening it from the app."
        case .runtimeExited: return "The bundled runtime stopped unexpectedly. See the console for details."
        case .timeout(let stage): return "Timed out while waiting for \(stage)."
        case .service(let value): return value
        }
    }
}

enum EditorSurface: String, Codable, CaseIterable, Sendable {
    case tools, viewer
    var section: AppSection { self == .viewer ? .viewer : .assets }
    var command: String { self == .viewer ? "showViewer" : "showTools" }
    var appSection: AppSection { section }

    static func embeddedURL(_ base: URL, section: Self) -> URL? {
        guard TrustedOrigin(base) != nil,
              var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "embedded" }
        items.append(URLQueryItem(name: "embedded", value: "1"))
        components.queryItems = items
        components.fragment = section.rawValue
        return components.url
    }
}

typealias AssetEditorSection = EditorSurface

enum AppSection: String, CaseIterable, Identifiable {
    case server, accounts, content, assets, viewer, settings
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .server: return "server.rack"
        case .accounts: return "person.crop.circle"
        case .content: return "externaldrive"
        case .assets: return "wrench.and.screwdriver"
        case .viewer: return "cube.transparent"
        case .settings: return "gearshape"
        }
    }
    func title(_ language: String) -> String {
        let strings: [String: [String]] = [
            "server": ["Server", "서버", "サーバー"],
            "accounts": ["Accounts", "계정", "アカウント"],
            "content": ["Server content", "서버 콘텐츠", "サーバーコンテンツ"],
            "assets": ["Asset editing tools", "에셋 편집 도구", "アセット編集ツール"],
            "viewer": ["3D model", "3D 모델", "3Dモデル"],
            "settings": ["Settings", "설정", "設定"],
        ]
        return strings[rawValue]![language == "ko" ? 1 : language == "ja" ? 2 : 0]
    }

    var assetEditorSection: AssetEditorSection? {
        switch self {
        case .assets: return .tools
        case .viewer: return .viewer
        default: return nil
        }
    }
}

enum AssetSectionEvent: String { case ready, change }

/// Keep the latest native destination while the shared page is loading.
struct AssetNavigationState {
    private(set) var desired: AssetEditorSection
    private(set) var sent: AssetEditorSection?

    init(desired: AssetEditorSection = .tools) { self.desired = desired }
    var needsUpdate: Bool { sent != desired }
    mutating func select(_ section: AssetEditorSection) { desired = section }
    mutating func selectFromRender(_ section: AssetEditorSection,
                                   currentSelection: AssetEditorSection?) -> Bool {
        guard currentSelection == section else { return false }
        select(section)
        return true
    }
    mutating func pageReady() { sent = nil }
    mutating func markSent(_ section: AssetEditorSection) {
        if section == desired { sent = section }
    }
    mutating func retry(_ section: AssetEditorSection) {
        if section == desired && sent == section { sent = nil }
    }
    mutating func pageChanged(_ section: AssetEditorSection) {
        desired = section; sent = section
    }
}

enum NativeText {
    static func value(_ english: String, _ korean: String, _ japanese: String, language: String) -> String {
        language == "ko" ? korean : language == "ja" ? japanese : english
    }
}
