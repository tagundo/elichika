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

    enum CodingKeys: String, CodingKey { case phase, busy, prepared, error, progress, server; case serverRunning = "server_running" }
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
    }
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
    enum CodingKeys: String, CodingKey { case serverAddress = "server_address", cdnServer = "cdn_server" }
}

enum IPAddress {
    static func isLiteral(_ value: String) -> Bool {
        var v4 = in_addr(), v6 = in6_addr()
        return value.withCString { inet_pton(AF_INET, $0, &v4) == 1 || inet_pton(AF_INET6, $0, &v6) == 1 }
    }
}

struct NativeRequest: Decodable {
    enum Action: String, Decodable { case openFiles, chooseDirectory, reveal, setFullscreen, setLanguage, setViewerPanelWidth, setViewerFilesWidth, setPanelSettings }
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
            guard let width = request.width, width == 0 || (240...640).contains(width) else { throw NativeError.invalidMessage }
        } else if request.action == .setViewerFilesWidth {
            guard let width = request.width, width == 0 || (160...360).contains(width) else { throw NativeError.invalidMessage }
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

enum AppSection: String, CaseIterable, Identifiable {
    case server, accounts, content, assets, settings
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .server: return "server.rack"
        case .accounts: return "person.crop.circle"
        case .content: return "externaldrive"
        case .assets: return "cube.transparent"
        case .settings: return "gearshape"
        }
    }
    func title(_ language: String) -> String {
        let strings: [String: [String]] = [
            "server": ["Server", "서버", "サーバー"],
            "accounts": ["Accounts", "계정", "アカウント"],
            "content": ["Server content", "서버 콘텐츠", "サーバーコンテンツ"],
            "assets": ["Asset editing", "에셋 편집", "アセット編集"],
            "settings": ["Settings", "설정", "設定"],
        ]
        return strings[rawValue]![language == "ko" ? 1 : language == "ja" ? 2 : 0]
    }
}

enum NativeText {
    static func value(_ english: String, _ korean: String, _ japanese: String, language: String) -> String {
        language == "ko" ? korean : language == "ja" ? japanese : english
    }
}
