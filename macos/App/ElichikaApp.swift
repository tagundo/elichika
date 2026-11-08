import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
struct ElichikaMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        Window("Elichika", id: "main") {
            RootView(model: model)
                .frame(minWidth: 920, minHeight: 640)
                .onAppear { model.launch(); delegate.attach(model) }
        }
        .defaultSize(width: 1280, height: 860)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(model.text("Open model…", "모델 열기…", "モデルを開く…")) { model.perform("openModel") }
                    .keyboardShortcut("o").disabled(!model.toolsReady)
            }
            CommandGroup(after: .saveItem) {
                Button(model.text("Save edited model", "편집 모델 저장", "編集モデルを保存")) { model.perform("saveModel") }
                    .keyboardShortcut("s").disabled(!model.toolsReady)
            }
            CommandGroup(replacing: .appSettings) {
                Button(model.text("Settings…", "설정…", "設定…")) { model.selectedSection = .settings }
                    .keyboardShortcut(",")
            }
            CommandMenu(model.text("Server", "서버", "サーバー")) {
                Button(model.snapshot.serverRunning ? model.text("Stop server", "서버 중지", "サーバー停止") : model.text("Start server", "서버 시작", "サーバー起動")) { model.toggleServer() }
                    .disabled(!model.toolsReady || model.snapshot.busy)
                Button(model.text("Show model viewer", "모델 뷰어 표시", "モデルビューアを表示")) { model.perform("showViewer") }
                    .keyboardShortcut("3", modifiers: [.command, .shift]).disabled(!model.toolsReady)
            }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private weak var model: AppModel?
    private var pendingURLs: [URL] = []
    private var termination = AppTerminationGate()
    func attach(_ model: AppModel) {
        self.model = model
        if !pendingURLs.isEmpty { model.openDocuments(pendingURLs); pendingURLs.removeAll() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model else { return .terminateNow }
        model.smokeEvent?("appkit-termination-delegate")
        switch termination.request() {
        case .terminate:
            model.smokeEvent?("appkit-termination-ready")
            return .terminateNow
        case .cancel:
            model.smokeEvent?("appkit-termination-cancelled-during-cleanup")
            return .terminateCancel
        case .cleanUp:
            // Keep the ordinary main run loop active while async child cleanup
            // runs. terminateLater enters AppKit's termination loop, which can
            // prevent MainActor tasks and their continuations from progressing.
            model.quit { [weak self] in
                self?.termination.cleanupFinished()
                model.smokeEvent?("appkit-termination-retry")
                sender.terminate(nil)
            }
            return .terminateCancel
        }
    }
    func application(_ application: NSApplication, open urls: [URL]) {
        let files = urls.filter(\.isFileURL)
        if let model { model.openDocuments(files) } else { pendingURLs.append(contentsOf: files) }
    }
}

struct RootView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $model.selectedSection) { section in
                Label(section.title(model.language), systemImage: section.symbol).tag(section)
            }
            .navigationTitle("Elichika")
            .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 280)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        if model.snapshot.serverLoading { ProgressView().controlSize(.small) }
                        else { Circle().fill(model.snapshot.serverRunning ? Color.green : Color.secondary).frame(width: 8, height: 8) }
                        Text(model.serverStatusTitle)
                            .font(.caption)
                    }
                    if let percent = model.snapshot.preparationPercent {
                        ProgressView(value: Double(percent), total: 100).controlSize(.small)
                    }
                    Button(model.snapshot.serverRunning ? model.text("Stop server", "서버 중지", "サーバー停止") : model.text("Start server", "서버 시작", "サーバー起動")) { model.toggleServer() }
                        .disabled(!model.toolsReady || model.snapshot.busy)
                }.padding().frame(maxWidth: .infinity, alignment: .leading)
            }
        } detail: {
            VStack(spacing: 0) {
                if let message = model.message {
                    HStack(alignment: .top) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                        Text(message).textSelection(.enabled)
                        Spacer()
                        Button { model.message = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }.padding(12).background(Color.orange.opacity(0.12))
                }
                destination
            }
            .navigationTitle((model.selectedSection ?? .server).title(model.language))
        }
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: nil) { providers in
            for provider in providers.prefix(128) {
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                    let url: URL?
                    if let data = item as? Data { url = URL(dataRepresentation: data, relativeTo: nil) }
                    else { url = item as? URL }
                    if let url, url.isFileURL { Task { @MainActor in model.openDocuments([url]) } }
                }
            }
            return !providers.isEmpty
        }
    }

    @ViewBuilder private var destination: some View {
        switch model.selectedSection ?? .server {
        case .server: ServerView(model: model)
        case .settings: SettingsView(model: model)
        case .assets, .viewer:
            if model.toolsReady { WebPanel(model: model, route: .assets) }
            else { PreparationView(model: model) }
        case .content:
            if model.toolsReady { WebPanel(model: model, route: .content) }
            else { PreparationView(model: model) }
        case .accounts:
            if model.goURL(path: "/webui/user/") != nil { WebPanel(model: model, route: .accounts).id(model.snapshot.server?.url) }
            else { StartServerView(model: model) }
        }
    }
}

private struct PreparationView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 18) {
            if model.snapshot.phase != "error" && model.snapshot.preparationPercent == nil { ProgressView() }
            Text(model.preparationStatusTitle).font(.title3)
            PreparationProgressView(model: model).frame(width: 300)
            Text(model.text("The game server can remain stopped while editing assets.", "에셋을 편집할 때 게임 서버를 실행할 필요는 없습니다.", "アセット編集中はゲームサーバーを停止したままにできます。"))
                .foregroundStyle(.secondary)
            if model.snapshot.phase == "error" || (!model.launching && model.message != nil) {
                Button(model.text("Retry preparation", "준비 다시 시도", "準備を再試行")) { model.retryTools() }
                    .disabled(!model.canChangeStorage)
            }
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct PreparationProgressView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        if let percent = model.snapshot.preparationPercent {
            VStack(spacing: 6) {
                ProgressView(value: Double(percent), total: 100)
                HStack {
                    Text(model.text("Game-data update progress", "게임 데이터 갱신 진행률", "ゲームデータ更新の進捗"))
                    Spacer()
                    Text("\(percent)%").monospacedDigit()
                }.font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

private struct StartServerView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 18) {
            if model.snapshot.serverRunning { ProgressView(); Text(model.serverStatusTitle) }
            else {
                Image(systemName: "server.rack").font(.system(size: 44)).foregroundStyle(.secondary)
                Text(model.text("Start the server to open this page.", "이 화면을 열려면 서버를 시작하세요.", "この画面を開くにはサーバーを起動してください。"))
            }
            Button(model.snapshot.serverRunning ? model.text("Stop server", "서버 중지", "サーバー停止") : model.text("Start server", "서버 시작", "サーバー起動")) { model.toggleServer() }
                .disabled(!model.toolsReady || model.snapshot.busy)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct ServerView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 18) {
                Image(systemName: "server.rack").font(.system(size: 40)).foregroundStyle(.pink)
                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(model.serverStatusTitle).font(.title2)
                        if model.snapshot.serverLoading { ProgressView().controlSize(.small) }
                    }
                    Text(model.toolsReady ? model.text("Tools are ready", "도구 준비 완료", "ツール準備完了") : model.text("Preparing tools…", "도구 준비 중…", "ツール準備中…")).foregroundStyle(.secondary)
                }
                Spacer()
                Button(model.snapshot.serverRunning ? model.text("Stop server", "서버 중지", "サーバー停止") : model.text("Start server", "서버 시작", "サーバー起動")) { model.toggleServer() }
                    .buttonStyle(.borderedProminent).disabled(!model.toolsReady || model.snapshot.busy)
            }
            if let url = model.connectionAddress ?? model.snapshot.server?.url, model.snapshot.serverRunning {
                HStack {
                    Text(url).font(.body.monospaced()).textSelection(.enabled)
                    Button(model.text("Copy", "복사", "コピー")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(url, forType: .string) }
                    Button(model.text("Server settings", "서버 설정", "サーバー設定")) { model.selectedSection = .settings; model.showServerSettings = true }
                }
            }
            PreparationProgressView(model: model).frame(maxWidth: 420, alignment: .leading)
            Text(model.text("Console", "콘솔", "コンソール")).font(.headline)
            if !model.launching && model.process?.isRunning != true {
                Button(model.text("Retry preparation", "준비 다시 시도", "準備を再試行")) { model.retryTools() }
                    .disabled(!model.canChangeStorage)
            }
            ScrollView {
                Text(model.console.joined(separator: "\n")).font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }.background(Color(nsColor: .textBackgroundColor)).cornerRadius(8)
        }.padding(24)
    }
}

private struct SettingsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            Picker(model.text("Settings", "설정", "設定"), selection: $model.showServerSettings) {
                Text(model.text("App", "앱", "アプリ")).tag(false)
                Text(model.text("Server", "서버", "サーバー")).tag(true)
            }.pickerStyle(.segmented).frame(width: 300).padding()
            if model.showServerSettings {
                if model.goURL(path: "/webui/admin/") != nil { WebPanel(model: model, route: .serverSettings).id(model.snapshot.server?.url) }
                else { StartServerView(model: model) }
            } else {
                Form {
                    Section {
                        Picker(model.text("Language", "언어", "言語"), selection: Binding(get: { model.language }, set: model.setLanguage)) {
                            Text("English").tag("en"); Text("한국어").tag("ko"); Text("日本語").tag("ja")
                        }
                    }
                    Section(model.text("Asset library", "에셋 보관 폴더", "アセット保存先")) {
                        Text(model.libraryDirectory).font(.callout.monospaced()).textSelection(.enabled)
                        HStack {
                            Button(model.text("Choose folder…", "폴더 선택…", "フォルダーを選択…")) { model.chooseLibraryDirectory() }.disabled(!model.canChangeStorage)
                            Button(model.text("Show in Finder", "Finder에서 보기", "Finderで表示")) { try? model.reveal(model.libraryDirectory) }
                        }
                        Text(model.text("Stop the server and finish running jobs before changing the asset folder.", "에셋 보관 폴더를 바꾸기 전에 서버와 실행 중인 작업을 중지하세요.", "保存先を変更する前にサーバーと実行中の処理を停止してください。"))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Section(model.text("Server data", "서버 데이터", "サーバーデータ")) {
                        Text(model.dataDirectory.path).font(.callout.monospaced()).textSelection(.enabled)
                        Button(model.text("Show in Finder", "Finder에서 보기", "Finderで表示")) { try? model.reveal(model.dataDirectory.path) }
                    }
                    Section(model.text("Network", "네트워크", "ネットワーク")) {
                        TextField(model.text("Listen address", "서버 수신 주소", "待ち受けアドレス"), text: $model.serverAddressDraft)
                            .disabled(!model.canChangeStorage || model.savingNetwork)
                        TextField(model.text("CDN URL", "CDN URL", "CDN URL"), text: $model.cdnServerDraft)
                            .disabled(!model.canChangeStorage || model.savingNetwork)
                        Text(model.text("For another device: listen on 0.0.0.0:8080 and use http://YOUR-MAC-LAN-IP:8080/static as the CDN URL. Firewall and game connection settings are managed separately.", "다른 기기에서 연결하려면 수신 주소를 0.0.0.0:8080, CDN URL을 http://맥의-LAN-IP:8080/static 으로 설정하세요. 방화벽과 게임 연결 설정은 별도로 관리합니다.", "別の端末から接続する場合は0.0.0.0:8080で待ち受け、CDN URLをhttp://MacのLAN-IP:8080/staticに設定してください。ファイアウォールとゲームの接続設定は別途管理します。"))
                            .font(.caption).foregroundStyle(.secondary)
                        HStack {
                            Button(model.text("Save network settings", "네트워크 설정 저장", "ネットワーク設定を保存")) { model.saveNetworkConfig() }
                                .disabled(!model.canChangeStorage || !model.networkChanged || model.savingNetwork)
                            Button(model.text("Reload", "다시 읽기", "再読み込み")) { Task { await model.loadNetworkConfig() } }
                                .disabled(!model.toolsReady || model.savingNetwork)
                            if let address = model.connectionAddress {
                                Button(model.text("Copy connection address", "연결 주소 복사", "接続アドレスをコピー")) {
                                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(address, forType: .string)
                                }
                            }
                        }
                    }
                    Section {
                        Text("Elichika " + (Bundle.main.object(forInfoDictionaryKey: "ElichikaVersion") as? String ?? Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""))
                        Text("Apple silicon · macOS 13+").font(.caption).foregroundStyle(.secondary)
                        Text(model.text("Quitting Elichika stops its server and bundled tools.", "Elichika를 종료하면 서버와 내장 도구도 함께 종료됩니다.", "Elichikaを終了するとサーバーと内蔵ツールも停止します。"))
                            .foregroundStyle(.secondary)
                    }
                }.formStyle(.grouped)
            }
        }
    }
}
