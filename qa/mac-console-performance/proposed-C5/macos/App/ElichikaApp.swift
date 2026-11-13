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
                Button(model.text("App settings…", "앱 설정…", "アプリ設定…")) { model.selectedSection = .settings }
                    .keyboardShortcut(",")
            }
            CommandMenu(model.text("Server", "서버", "サーバー")) {
                Button(model.snapshot.serverRunning ? model.text("Stop server", "서버 중지", "サーバー停止") : model.text("Start server", "서버 시작", "サーバー起動")) { model.toggleServer() }
                    .disabled(!model.canControlServer)
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
                        .disabled(!model.canControlServer)
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
        case .serverSettings:
            if model.goURL(path: "/webui/admin/") != nil {
                WebPanel(model: model, route: .serverSettings)
                    .onAppear { model.retryManagement() }
            }
            else { ManagementPreparationView(model: model) }
        case .assets, .viewer:
            if model.toolsReady {
                WebPanel(model: model, route: .assets,
                         editorSurface: model.selectedSection == .viewer ? .viewer : .tools)
            }
            else { PreparationView(model: model) }
        case .content:
            if model.toolsReady { WebPanel(model: model, route: .content) }
            else { PreparationView(model: model) }
        case .accounts:
            if model.goURL(path: "/webui/user/") != nil {
                WebPanel(model: model, route: .accounts)
                    .onAppear { model.retryManagement() }
            }
            else { ManagementPreparationView(model: model) }
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
                .disabled(!model.canControlServer)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct ManagementPreparationView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        if !model.toolsReady {
            PreparationView(model: model)
        } else {
            VStack(spacing: 16) {
                if model.snapshot.management?.error == nil { ProgressView() }
                Text(model.text("Preparing management tools…", "관리 도구를 준비하고 있습니다…", "管理ツールを準備しています…"))
                    .font(.title3)
                Text(model.text("Server settings and accounts can be managed while the game server is stopped.", "게임 서버가 꺼져 있어도 서버 설정과 유저 관리를 사용할 수 있습니다.", "ゲームサーバーを停止したまま設定とユーザー管理を利用できます。"))
                    .foregroundStyle(.secondary)
                if model.snapshot.busy {
                    Text(model.text("Waiting for the current task to finish.", "현재 작업이 끝나기를 기다리고 있습니다.", "実行中の処理の完了を待っています。"))
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let error = model.snapshot.management?.error {
                    Text(error).textSelection(.enabled)
                    Button(model.text("Retry", "다시 시도", "再試行")) { model.retryManagement() }
                        .disabled(model.snapshot.busy || model.snapshot.serverRunning)
                }
            }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
                .onAppear {
                    if model.snapshot.management?.error == nil { model.retryManagement() }
                }
                .onChange(of: model.snapshot.busy) { busy in
                    if !busy && model.snapshot.management?.error == nil && model.goURL(path: "/webui/admin/") == nil {
                        model.retryManagement()
                    }
                }
        }
    }
}

private struct ServerView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
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
                    .buttonStyle(.borderedProminent).disabled(!model.canControlServer)
            }
            if let url = model.connectionAddress ?? model.snapshot.server?.url, model.snapshot.serverRunning {
                HStack {
                    Text(url).font(.body.monospaced()).textSelection(.enabled)
                    Button(model.text("Copy", "복사", "コピー")) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(url, forType: .string) }
                    Button(model.text("Server settings", "서버 설정", "サーバー設定")) { model.selectedSection = .serverSettings }
                }
            }
            PreparationProgressView(model: model).frame(maxWidth: 420, alignment: .leading)
            ConsoleActionsView(model: model)
            if let job = model.consoleState?.job { ConsoleJobView(model: model, job: job) }
            Text(model.text("Console", "콘솔", "コンソール")).font(.headline)
            if !model.launching && model.process?.isRunning != true {
                Button(model.text("Retry preparation", "준비 다시 시도", "準備を再試行")) { model.retryTools() }
                    .disabled(!model.canChangeStorage)
            }
            ConsoleLogView(store: model.consoleLogs)
                .background(Color(nsColor: .textBackgroundColor)).cornerRadius(8)
                .frame(minHeight: 120, maxHeight: .infinity)
                .accessibilityIdentifier("console.logs")
        }.padding(24).background(ConsoleRenderMarker())
    }
}

/// An incremental, selectable log document observes only the log store. Its
/// text storage survives ordinary state polling and menu/body reevaluations.
private struct ConsoleLogView: NSViewRepresentable {
    @ObservedObject var store: ConsoleLogStore

    final class Coordinator {
        var revision: UInt64?
        var headUTF16Offset = 0
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        let text = NSTextView(frame: scroll.contentView.bounds)
        text.isEditable = false
        text.isSelectable = true
        text.isRichText = false
        text.isVerticallyResizable = true
        text.isHorizontallyResizable = false
        text.autoresizingMask = [.width]
        text.minSize = .zero
        text.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        text.textContainer?.widthTracksTextView = true
        text.textContainer?.containerSize = NSSize(width: scroll.contentSize.width, height: CGFloat.greatestFiniteMagnitude)
        text.textContainerInset = NSSize(width: 12, height: 12)
        text.font = .monospacedSystemFont(ofSize: NSFont.smallSystemFontSize, weight: .regular)
        text.textColor = .labelColor
        text.backgroundColor = .textBackgroundColor
        text.identifier = NSUserInterfaceItemIdentifier("console.logs.document")
        text.setAccessibilityIdentifier("console.logs.document")
        scroll.documentView = text
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        let value = store.snapshot
        guard context.coordinator.revision != value.revision,
              let text = scroll.documentView as? NSTextView,
              let storage = text.textStorage else { return }
        let initial = context.coordinator.revision == nil
        let tailing = initial || (text.selectedRange().length == 0
            && scroll.contentView.bounds.maxY >= text.bounds.maxY - 20)
        let previousOrigin = scroll.contentView.bounds.origin
        let selections = text.selectedRanges.map(\.rangeValue)
        var anchor: (character: Int, y: CGFloat)?
        if !tailing, storage.length > 0, let layout = text.layoutManager,
           let container = text.textContainer {
            let point = NSPoint(x: 0, y: max(0, previousOrigin.y - text.textContainerInset.height))
            // Finish only the visible fragments before reading their on-screen
            // glyph position; hit testing can otherwise return provisional layout.
            layout.ensureLayout(forBoundingRect: NSRect(origin: point, size: scroll.contentView.bounds.size),
                                in: container)
            let character = min(storage.length - 1,
                layout.characterIndex(for: point, in: container, fractionOfDistanceBetweenInsertionPoints: nil))
            let glyph = layout.glyphIndexForCharacter(at: character)
            anchor = (character, layout.boundingRect(forGlyphRange: NSRange(location: glyph, length: 1),
                                                     in: container).minY)
        }
        let incremental = context.coordinator.revision == value.previousRevision
            && value.removedUTF16Count <= storage.length
        let headShift = max(0, value.headUTF16Offset - context.coordinator.headUTF16Offset)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: NSFont.smallSystemFontSize, weight: .regular),
            .foregroundColor: NSColor.labelColor,
        ]
        // Ask for layout only through the visible range. AppKit can leave the
        // rest of this bounded document laid out on demand.
        text.layoutManager?.allowsNonContiguousLayout = true
        storage.beginEditing()
        if incremental {
            storage.deleteCharacters(in: NSRange(location: 0, length: value.removedUTF16Count))
            storage.append(NSAttributedString(string: value.appendedText, attributes: attributes))
        } else {
            storage.setAttributedString(NSAttributedString(string: value.text, attributes: attributes))
        }
        storage.endEditing()
        context.coordinator.revision = value.revision
        context.coordinator.headUTF16Offset = value.headUTF16Offset
        if tailing {
            text.scrollToEndOfDocument(nil)
        } else {
            // Preserve the selected surviving text when old head lines expire.
            // AppKit otherwise resets selection after a text-storage edit.
            let removed = headShift
            text.selectedRanges = selections.map { range in
                let start = max(0, range.location - removed)
                let end = max(start, range.location + range.length - removed)
                return NSValue(range: NSRange(location: min(start, storage.length),
                    length: max(0, min(end, storage.length) - min(start, storage.length))))
            }
            var origin = previousOrigin
            if let anchor, storage.length > 0, let layout = text.layoutManager,
               let container = text.textContainer {
                let character = min(storage.length - 1, max(0, anchor.character - removed))
                // Head trimming can invalidate preceding wrapped paragraphs.
                // Noncontiguous layout estimates their heights until requested;
                // lay out through the retained anchor so its Y stays stable when
                // AppKit later draws. The suffix remains laid out on demand.
                layout.ensureLayout(forCharacterRange: NSRange(location: 0, length: character + 1))
                let glyph = layout.glyphIndexForCharacter(at: character)
                let range = NSRange(location: glyph, length: 1)
                origin.y = max(0, origin.y + layout.boundingRect(forGlyphRange: range, in: container).minY - anchor.y)
            }
            scroll.contentView.scroll(to: origin)
            scroll.reflectScrolledClipView(scroll.contentView)
        }
    }
}

// An attached marker lets native QA wait for this destination's actual layout
// after SwiftUI has replaced the previous page.
private struct ConsoleRenderMarker: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.identifier = NSUserInterfaceItemIdentifier("elichika.console.rendered")
        return view
    }
    func updateNSView(_ view: NSView, context: Context) {}
}

private struct ConsoleActionsView: View {
    @ObservedObject var model: AppModel
    @State private var advancedExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.resetSubmissionUncertain && !model.submittingConsoleAction {
                Label(model.text("Checking reset status…", "초기화 상태 확인 중…", "初期化の状態を確認中…"), systemImage: "clock.arrow.circlepath")
                    .font(.callout).foregroundStyle(.secondary).accessibilityIdentifier("console.checkingReset")
            }
            HStack(alignment: .top, spacing: 12) {
                GroupBox(model.text("Game data", "게임 데이터", "ゲームデータ")) {
                    VStack(spacing: 6) {
                        actionButton(.downloadArchive, symbol: "arrow.down.circle")
                        actionButton(.downloadPacks, symbol: "arrow.down.doc")
                        Button { model.presentConsole(.action(.cdnCacheToggle)) } label: {
                            Label(cacheTitle, systemImage: model.consoleState?.cacheEnabled == true ? "checkmark.circle" : "circle")
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .disabled(!model.canRunConsoleAction || model.consoleState?.cacheEnabled == nil)
                        .accessibilityIdentifier("console.cdn_cache_toggle")
                        .accessibilityValue(cacheValue)
                    }.padding(4)
                }.frame(maxWidth: .infinity).accessibilityIdentifier("console.gameData")
                GroupBox(model.text("Settings & Help", "설정 및 도움말", "設定とヘルプ")) {
                    VStack(spacing: 6) {
                        Button { model.presentConsole(.guide) } label: {
                            Label(model.text("Guide", "사용 안내", "ガイド"), systemImage: "questionmark.circle").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.guide")
                        Button { model.selectedSection = .settings } label: {
                            Label(AppSection.settings.title(model.language), systemImage: "gearshape").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.settings")
                        Button { model.selectedSection = .serverSettings } label: {
                            Label(AppSection.serverSettings.title(model.language), systemImage: "slider.horizontal.3").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.serverSettings")
                        Button { model.presentConsole(.about) } label: {
                            Label(model.text("About", "앱 정보", "このアプリについて"), systemImage: "info.circle").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.about")
                    }.padding(4)
                }.frame(maxWidth: .infinity).accessibilityIdentifier("console.settingsHelp")
                GroupBox(model.text("Mod pages", "모드 페이지", "MODページ")) {
                    VStack(spacing: 6) {
                        Link(destination: URL(string: "https://ayakamods.com/games/love-live-school-idol-festival-all-stars.217/")!) {
                            Label("AyakaMods", systemImage: "arrow.up.right.square").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.ayakamods")
                        Link(destination: URL(string: "https://gamebanana.com/games/20519")!) {
                            Label("GameBanana", systemImage: "arrow.up.right.square").frame(maxWidth: .infinity, alignment: .leading)
                        }.accessibilityIdentifier("console.gamebanana")
                    }.padding(4)
                }.frame(maxWidth: .infinity).accessibilityIdentifier("console.modPages")
            }
            DisclosureGroup(isExpanded: $advancedExpanded) {
                HStack(spacing: 8) {
                    actionButton(.rebuildAssets, symbol: "arrow.triangle.2.circlepath")
                    actionButton(.fixTrainingTrees, symbol: "wrench.and.screwdriver")
                    actionButton(.resetServer, symbol: "exclamationmark.triangle", destructive: true)
                }.padding(.top, 6)
            } label: {
                Label(model.text("Advanced", "고급", "高度な操作"), systemImage: "slider.horizontal.3").font(.callout)
            }.accessibilityIdentifier("console.advanced")
        }
        .buttonStyle(.bordered).controlSize(.small)
        .lineLimit(2).multilineTextAlignment(.leading)
        .sheet(item: $model.consolePresentation) { ConsoleSheet(model: model, presentation: $0) }
    }

    private var cacheValue: String {
        guard let enabled = model.consoleState?.cacheEnabled else { return model.text("Unavailable", "확인 불가", "確認できません") }
        return enabled ? model.text("ON", "켜짐", "オン") : model.text("OFF", "꺼짐", "オフ")
    }
    private var cacheTitle: String { ConsoleAction.cdnCacheToggle.title(model.language) + ": " + cacheValue + "…" }

    private func actionButton(_ action: ConsoleAction, symbol: String, destructive: Bool = false) -> some View {
        Button(role: destructive ? .destructive : nil) { model.presentConsole(.action(action)) } label: {
            Label(action.title(model.language), systemImage: symbol).frame(maxWidth: .infinity, alignment: .leading)
        }.disabled(!model.canRunConsoleAction).accessibilityIdentifier("console." + action.rawValue)
    }
}

private struct ConsoleJobView: View {
    @ObservedObject var model: AppModel
    let job: ConsoleState.Job
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                if job.running { ProgressView().controlSize(.small) }
                Text(job.action.title(model.language)).font(.callout.weight(.medium))
                if let region = job.region { Text(region.rawValue.uppercased()).font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Text(statusTitle).font(.caption).foregroundStyle(job.status == "error" ? Color.red : Color.secondary)
                if job.running {
                    Button(model.text("Cancel", "취소", "キャンセル")) { model.cancelConsoleAction() }
                        .disabled(!job.cancellable || model.cancellingConsoleAction || job.status == "cancelling")
                        .accessibilityIdentifier("console.cancelJob")
                }
            }
            if let fraction = job.progress?.fraction {
                HStack {
                    ProgressView(value: fraction).controlSize(.small)
                    Text("\(Int(fraction * 100))%").font(.caption).monospacedDigit()
                }
            }
            if let detail = job.error ?? job.progress?.current, !detail.isEmpty {
                Text(detail).font(.caption).foregroundStyle(job.error == nil ? Color.secondary : Color.red)
                    .lineLimit(2).textSelection(.enabled)
            }
            if job.running && !job.cancellable {
                Text(model.text("Reset must finish safely before quitting.", "안전한 종료를 위해 초기화가 끝날 때까지 기다려야 합니다.", "安全に終了するため、初期化が完了するまでお待ちください。"))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.padding(10).background(Color.secondary.opacity(0.08)).cornerRadius(8)
            .accessibilityIdentifier("console.job")
    }
    private var statusTitle: String {
        switch job.status {
        case "queued": return model.text("Queued", "대기 중", "待機中")
        case "running": return model.text("Running", "실행 중", "実行中")
        case "cancelling": return model.text("Cancelling…", "취소 중…", "キャンセル中…")
        case "done": return model.text("Complete", "완료", "完了")
        case "cancelled": return model.text("Cancelled", "취소됨", "キャンセル済み")
        case "error": return model.text("Failed", "실패", "失敗")
        default: return job.status
        }
    }
}

private struct ConsoleSheet: View {
    @ObservedObject var model: AppModel
    let presentation: ConsolePresentation

    private var action: ConsoleAction? { presentation.action }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(title).font(.title2).accessibilityAddTraits(.isHeader)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(bodyText).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    if action != nil {
                        Label(model.text("The server will be stopped first and stays stopped after the action. Start it again when you are ready.", "작업 전에 서버를 중지하며 작업 후에도 중지 상태를 유지합니다. 준비되면 서버를 다시 시작하세요.", "処理前にサーバーを停止し、完了後も停止したままになります。準備ができたら再起動してください。"), systemImage: "stop.circle")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
            }.frame(height: contentHeight)
            if action == .downloadArchive {
                Picker(model.text("Region", "지역", "地域"), selection: $model.consoleRegion) {
                    ForEach(ConsoleRegion.allCases) { value in Text(value.title(model.language)).tag(value) }
                }.pickerStyle(.radioGroup).accessibilityIdentifier("console.region")
            }
            if let error = model.consoleActionError { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled).accessibilityIdentifier("console.actionError") }
            HStack {
                Spacer()
                if let action {
                    Button(model.text("Cancel", "취소", "キャンセル")) { model.dismissConsolePresentation() }
                        .keyboardShortcut(.cancelAction).disabled(model.submittingConsoleAction)
                        .accessibilityIdentifier("console.cancel")
                    Button(role: action == .resetServer && model.consoleResetFinal ? .destructive : nil) {
                        Task { await model.confirmConsoleAction() }
                    } label: {
                        if model.submittingConsoleAction { ProgressView().controlSize(.small) }
                        else { Text(action == .resetServer && model.consoleResetFinal ? model.text("Reset everything", "전부 초기화", "すべて初期化") : model.text("Continue", "계속", "続ける")) }
                    }
                    .disabled(!model.canRunConsoleAction)
                    .accessibilityIdentifier(model.consoleResetFinal ? "console.resetFinal" : "console.confirm")
                } else {
                    Button(model.text("Close", "닫기", "閉じる")) { model.dismissConsolePresentation() }.keyboardShortcut(.cancelAction)
                        .accessibilityIdentifier("console.close")
                }
            }
        }.padding(24).frame(width: 580).accessibilityIdentifier("console.sheet")
            .interactiveDismissDisabled(model.submittingConsoleAction)
    }

    private var title: String {
        switch presentation {
        case .action(let action): return action.title(model.language)
        case .guide: return model.text("Getting started", "시작하기", "はじめに")
        case .about:
            let version = Bundle.main.object(forInfoDictionaryKey: "ElichikaVersion") as? String
                ?? Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
            let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
            return "Elichika " + version + (build.map { $0 == version ? "" : " (\($0))" } ?? "")
        }
    }
    private var contentHeight: CGFloat {
        if case .guide = presentation { return 390 }
        if case .about = presentation { return 180 }
        return action == .resetServer && !model.consoleResetFinal ? 300 : 140
    }
    private var bodyText: String {
        switch presentation {
        case .guide: return guideText
        case .about:
            return model.text(
                "Elichika is a private server for SIFAS (Love Live! School Idol Festival All Stars). This Mac app runs the server, its WebUI, and the development and modding tools.\n\nServer and development tools by the elichika project (forks of YumeMichi / arina999999997 / tatara_hisoka). Modding tools: SIFAS-MODDING-HELPING-TOOLS.",
                "Elichika는 SIFAS (Love Live! School Idol Festival All Stars)의 사설 서버입니다. 이 Mac 앱은 서버, 웹 UI, 개발 및 모딩 도구를 실행합니다.\n\n서버 및 개발 도구: elichika 프로젝트 (YumeMichi / arina999999997 / tatara_hisoka 포크). 모딩 도구: SIFAS-MODDING-HELPING-TOOLS.",
                "ElichikaはSIFAS（ラブライブ！スクールアイドルフェスティバル ALL STARS）のプライベートサーバーです。このMacアプリはサーバー、Web UI、開発・MODツールを実行します。\n\nサーバーと開発ツール：elichikaプロジェクト（YumeMichi / arina999999997 / tatara_hisokaのフォーク）。MODツール：SIFAS-MODDING-HELPING-TOOLS。")
        case .action(let action):
            switch action {
            case .downloadArchive:
                return model.text("This downloads the full game data set (several GB) from archive.org. Wi-Fi is strongly recommended. Pick a region:", "archive.org에서 전체 게임 데이터(수 GB)를 받습니다. Wi-Fi 사용을 강력히 권장합니다. 지역을 선택하세요:", "archive.orgから全ゲームデータ（数GB）をダウンロードします。Wi-Fiの使用を強く推奨します。地域を選択してください：")
            case .downloadPacks:
                return model.text("This downloads missing game packs from the CDN. The size varies and can be large. Wi-Fi is recommended.", "CDN에서 누락된 게임 팩을 받습니다. 용량은 상황에 따라 다르며 매우 클 수 있습니다. Wi-Fi 사용을 권장합니다.", "CDNから不足しているゲームパックをダウンロードします。容量は状況により大きくなります。Wi-Fiを推奨します。")
            case .cdnCacheToggle:
                return model.consoleState?.cacheEnabled == true
                    ? model.text("Turn CDN cache off? Missing original files will use the original CDN without saving new local copies. Installed mods and downloaded files remain available.", "CDN 캐시를 끌까요? 없는 원본 파일은 기존 CDN에서 받고 새로 캐시에 저장하지 않습니다. 설치한 모드와 이미 받은 파일은 계속 사용할 수 있습니다.", "CDNキャッシュをオフにしますか？不足する元ファイルは元のCDNから取得し、新しく保存しません。MODと取得済みファイルは引き続き利用できます。")
                    : model.text("Turn CDN cache on? Missing packs will download on demand during play and be saved to packs/.", "CDN 캐시를 켤까요? 플레이 중 누락된 팩을 자동으로 받아 packs/에 저장합니다.", "CDNキャッシュをオンにしますか？プレイ中に不足パックを自動取得してpacks/に保存します。")
            case .rebuildAssets: return model.text("Rebuild master data now?", "마스터 데이터를 지금 재빌드할까요?", "マスターデータを今すぐ再構築しますか？")
            case .fixTrainingTrees: return model.text("Repair training-tree data now?", "트레이닝 트리 데이터를 지금 복구할까요?", "トレーニングツリーのデータを今すぐ修復しますか？")
            case .resetServer:
                if model.consoleResetFinal {
                    return model.text("Really reset the server AND all accounts now? This CANNOT be undone.", "정말 서버와 모든 계정을 지금 초기화할까요? 되돌릴 수 없습니다.", "本当にサーバーとすべてのアカウントを今すぐ初期化しますか？元に戻せません。")
                }
                return model.text(
                    "This restores the ORIGINAL (vanilla) game data and removes EVERY installed or cloned mod costume / live / card. It ALSO resets ALL accounts to a new-account state.\n\nLogins are kept, so game clients can still connect to the fresh server.\n\nKept: settings (config), downloaded game packs, and your asset-library files (mod zips, extracted/modded bundles, backups).\n\nThis CANNOT be undone. Make a DB backup (Server content) and export your accounts (Accounts) first if you may need this data again.",
                    "원본(바닐라) 게임 데이터를 복원하여 설치·클론된 모든 모드 의상 / 라이브 / 카드를 제거합니다. 또한 모든 계정을 새 계정 상태로 초기화합니다.\n\n로그인 정보는 유지되므로 게임 클라이언트는 초기화된 서버에 계속 접속할 수 있습니다.\n\n유지되는 것: 설정(config), 다운로드한 게임 팩, 에셋 보관 폴더의 파일(모드 zip, 추출/수정 번들, 백업).\n\n되돌릴 수 없습니다. 데이터가 필요할 수 있다면 먼저 DB 백업(서버 콘텐츠)과 계정 내보내기(계정)를 해두세요.",
                    "オリジナル（バニラ）のゲームデータを復元し、インストール・クローンされたすべてのMOD衣装／ライブ／カードを削除します。さらに、すべてのアカウントを新規アカウント状態にリセットします。\n\nログイン情報は保持され、ゲームクライアントは初期化されたサーバーに引き続き接続できます。\n\n保持：設定（config）、ダウンロード済みパック、アセット保存先のファイル（MOD zip、抽出・編集済みバンドル、バックアップ）。\n\n元に戻せません。必要なら先にDBバックアップ（サーバーコンテンツ）とアカウントのエクスポート（アカウント）を行ってください。")
            }
        }
    }

    // Adapted from MainActivity.showGuide / values{,-ko,-ja}/strings.xml;
    // Mac storage uses the selected library and does not need Android permissions.
    private var guideText: String {
        let address = model.connectionAddress ?? "http://127.0.0.1:8080"
        return model.text(
            "1. Wait for the bundled tools to be ready. Your asset library is selected in App settings.\n2. Click Start server.\n3. Point the game app at \(address) (see the LL-hax guide). For another device, set the listen address to 0.0.0.0:8080 and connect the game to your Mac’s LAN address. Keep the original game CDN address unchanged.\n4. Optional: pre-download game files with Download all (archive.org) or Download missing (CDN).\n\nCDN cache: when on, missing packs download as needed during play and are saved to packs/. Pre-downloading is optional. Keep Elichika running while downloads finish.\n\nPages: Server settings / Accounts = server WebUI; Server content = development tools; Asset editing tools = modding tools; 3D model = model viewer.\n\nAsset library: \(model.libraryDirectory)\nextracted = decrypted models (edit input); modded = edited bundles (edit output); suit / live / card / livetimeline = add-on drop folders; sql = DB patches; packs = game pack cache; backup = DB backups; logs = logs.\n\nUse Server content to make DB backups and Accounts to export your accounts before resetting the server.",
            "1. 내장 도구 준비가 끝날 때까지 기다리세요. 에셋 보관 폴더는 앱 설정에서 선택합니다.\n2. ‘서버 시작’을 누르세요.\n3. 게임 앱을 \(address)으로 연결하세요(LL-hax 가이드 참고). 다른 기기는 수신 주소를 0.0.0.0:8080으로 설정하고 게임을 Mac의 LAN 주소로 연결하세요. 원본 게임 CDN 주소는 유지하세요.\n4. 선택 사항: ‘전체 받기’(archive.org) 또는 ‘누락분 받기’(CDN)로 게임 파일을 미리 받으세요.\n\nCDN 캐시: 켜져 있으면 플레이 중 필요한 팩을 자동으로 받아 packs/에 저장합니다. 미리 받기는 필수가 아닙니다. 다운로드가 끝날 때까지 Elichika를 실행해 두세요.\n\n화면: 서버 설정 / 계정 = 서버 웹 UI; 서버 콘텐츠 = 개발 도구; 에셋 편집 도구 = 모딩 도구; 3D 모델 = 모델 뷰어.\n\n에셋 보관 폴더: \(model.libraryDirectory)\nextracted = 복호화된 모델(편집 입력); modded = 편집된 번들(편집 출력); suit / live / card / livetimeline = 애드온 드롭 폴더; sql = DB 패치; packs = 게임 팩 캐시; backup = DB 백업; logs = 로그.\n\n서버 초기화 전에 서버 콘텐츠에서 DB를 백업하고 계정에서 계정을 내보내세요.",
            "1. 内蔵ツールの準備が終わるまでお待ちください。アセット保存先はアプリ設定で選択できます。\n2. 「サーバー起動」をクリック。\n3. ゲームアプリを\(address)に接続（LL-haxガイド参照）。別端末では待ち受けアドレスを0.0.0.0:8080にし、MacのLANアドレスに接続してください。元のゲームCDNアドレスは維持してください。\n4. 任意：「全ファイル取得」（archive.org）または「不足分を取得」（CDN）で事前ダウンロード。\n\nCDNキャッシュ：オンの場合、プレイ中に必要なパックを自動取得してpacks/に保存します。事前取得は任意です。完了までElichikaを起動したままにしてください。\n\n画面：サーバー設定 / アカウント = サーバーWeb UI、サーバーコンテンツ = 開発ツール、アセット編集ツール = MODツール、3Dモデル = モデルビューア。\n\nアセット保存先：\(model.libraryDirectory)\nextracted = 復号済みモデル（編集入力）、modded = 編集済みバンドル（編集出力）、suit / live / card / livetimeline = アドオンのドロップ先、sql = DBパッチ、packs = パックキャッシュ、backup = DBバックアップ、logs = ログ。\n\nサーバー初期化前に、サーバーコンテンツでDBをバックアップし、アカウントでエクスポートしてください。")
    }
}

private struct SettingsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
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
                    .disabled(!model.canChangeStorage || !model.networkReady || model.savingNetwork)
                TextField(model.text("Original game CDN URL", "원본 게임 CDN 주소", "元のゲームCDN URL"), text: $model.cdnServerDraft)
                    .disabled(!model.canChangeStorage || !model.networkReady || model.savingNetwork)
                Text(model.text("Keep the original CDN address here. Installed mod files are provided by Elichika automatically. CDN cache controls whether missing original files are saved locally. For another device, listen on 0.0.0.0:8080 and connect the game to your Mac's LAN address.", "여기에는 기존 원본 CDN 주소를 유지하세요. 설치한 모드 파일은 Elichika에서 자동으로 제공합니다. CDN 캐시는 누락된 원본 파일을 로컬에 저장할지 결정합니다. 다른 기기는 수신 주소를 0.0.0.0:8080으로 설정하고 게임을 맥의 LAN 주소로 연결하세요.", "元のCDNアドレスを維持してください。インストールしたMODファイルはElichikaが自動配信します。CDNキャッシュは不足している元ファイルを保存するかを設定します。別端末からは0.0.0.0:8080で待ち受け、MacのLANアドレスに接続してください。"))
                    .font(.caption).foregroundStyle(.secondary)
                if let original = model.defaultCdnServer {
                    Button(model.text("Use default original CDN", "기본 원본 CDN 주소 사용", "既定の元CDNを使用")) { model.cdnServerDraft = original }
                        .disabled(!model.canChangeStorage || model.savingNetwork || model.cdnServerDraft == original)
                }
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
            .onAppear {
                if !model.networkChanged { Task { await model.loadNetworkConfig() } }
            }
    }
}
