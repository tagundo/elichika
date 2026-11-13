import Foundation
import AppKit
import Combine
import XCTest
import UniformTypeIdentifiers
@testable import ElichikaMac

final class RuntimeContractTests: XCTestCase {
    @MainActor
    func testKnownTextureDownloadsUseAppKitPNGAndJSONSaveTypes() {
        _ = NSApplication.shared
        for (filename, expected) in [("costume.PNG", UTType.png), ("skin copy.png", UTType.png),
                                     ("user renamed.JSON", UTType.json), ("costume.elichika-texture.json", UTType.json)] {
            let panel = NSSavePanel()
            panel.nameFieldStringValue = "Renamed without extension"
            BrowserDownloadSavePolicy.configure(panel, suggestedFilename: filename)
            XCTAssertEqual(panel.allowedContentTypes, [expected])
            XCTAssertFalse(panel.allowsOtherFileTypes)
            panel.close()
        }
    }

    @MainActor
    func testUnknownBundleDownloadsRetainTheirExistingUnconstrainedSaveBehavior() {
        _ = NSApplication.shared
        for filename in ["costume.unity", "costume.zip", "texture.png.unity", "folder.json/model.bundle", "download"] {
            let panel = NSSavePanel()
            panel.allowedContentTypes = [.zip]
            panel.allowsOtherFileTypes = true
            BrowserDownloadSavePolicy.configure(panel, suggestedFilename: filename)
            XCTAssertEqual(panel.allowedContentTypes, [.zip])
            XCTAssertTrue(panel.allowsOtherFileTypes)
            XCTAssertNil(BrowserDownloadSavePolicy.contentType(for: filename))
            panel.close()
        }
    }

    func testTrustedOriginRejectsRemoteHostsAndCredentialURLs() {
        for value in ["https://127.0.0.1:8000/", "http://localhost:8000/", "http://127.0.0.1.attacker.example:8000/",
                      "http://127.0.0.1:8000@attacker.example/", "file:///tmp/model.unity", "http://127.0.0.1/"] {
            XCTAssertNil(TrustedOrigin(URL(string: value)!))
        }
        let origin = TrustedOrigin(URL(string: "http://127.0.0.1:8123/")!)!
        XCTAssertTrue(origin.contains(URL(string: "http://127.0.0.1:8123/api/viewer")!))
        XCTAssertFalse(origin.contains(URL(string: "http://127.0.0.1:8124/api/viewer")!))
    }

    func testReadinessRequiresDistinctUIAndControlSecretsAndPorts() throws {
        func ready(token: String, uiToken: String, tools: String) throws -> RuntimeReady {
            let data = try JSONSerialization.data(withJSONObject: ["control_url": "http://127.0.0.1:8100/", "admin_url": "http://127.0.0.1:8101/",
                "tools_url": tools, "token": token, "ui_token": uiToken, "data_dir": "/tmp/private", "sukusta_dir": "/tmp/library"])
            return try JSONDecoder().decode(RuntimeReady.self, from: data)
        }
        let a = String(repeating: "a", count: 32), b = String(repeating: "b", count: 32)
        XCTAssertNoThrow(try ready(token: a, uiToken: b, tools: "http://127.0.0.1:8102/").validate())
        XCTAssertThrowsError(try ready(token: a, uiToken: a, tools: "http://127.0.0.1:8102/").validate())
        XCTAssertThrowsError(try ready(token: a, uiToken: b, tools: "http://127.0.0.1:8100/").validate())
        XCTAssertThrowsError(try ready(token: a, uiToken: b, tools: "http://external.example:8102/").validate())
    }

    func testNativeBridgeRefusesUnknownActionsAndOversizedBodies() throws {
        XCTAssertThrowsError(try NativeRequest.parse(["id": "1", "action": "runShell", "command": "anything"]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "1", "action": "openFiles", "title": String(repeating: "x", count: 40_000)]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "", "action": "openFiles"]))
        let request = try NativeRequest.parse(["id": "desktop-7", "action": "openFiles", "multiple": true, "extensions": ["unity", "zip"]])
        XCTAssertEqual(request.action, .openFiles)
        XCTAssertEqual(request.multiple, true)
        for width in [0, 240, 416, 640, 641, 1024, 16_384] {
            let preference = try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": width])
            XCTAssertEqual(preference.width, width)
        }
        for width in [-1, 239, 16_385] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": width]))
        }
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth"]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": 300.5]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": true]))
        for width in [Double.infinity, -Double.infinity, Double.nan] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": width]))
        }
        for width in [0, 160, 224, 360] {
            XCTAssertEqual(try NativeRequest.parse(["id": "files-1", "action": "setViewerFilesWidth", "width": width]).width, width)
        }
        for width in [-1, 159, 361] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "files-1", "action": "setViewerFilesWidth", "width": width]))
        }
    }

    func testPanelSettingsBridgeLimitsScopesAndRestoresValidatedPreferences() throws {
        let settings: [String: Any] = ["hidden": ["viewer-adjustments"], "order": ["viewer-body-adjustments", "viewer-adjustments"]]
        for scope in ["viewer", "tools", "content"] {
            let request = try NativeRequest.parse(["id": "panels-1", "action": "setPanelSettings", "panelScope": scope, "panelSettings": settings])
            XCTAssertEqual(request.panelScope, scope)
            XCTAssertEqual(request.panelSettings?.hidden, ["viewer-adjustments"])
            let encoded = try JSONEncoder().encode(request.panelSettings!)
            let restored = try JSONDecoder().decode(NativeRequest.PanelPreferences.self, from: encoded)
            XCTAssertTrue(restored.isValid)
            XCTAssertEqual(restored.order, ["viewer-body-adjustments", "viewer-adjustments"])
        }
        for scope in ["", "../outside", "server"] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "panels-1", "action": "setPanelSettings", "panelScope": scope, "panelSettings": settings]))
        }
        let invalidSettings: [[String: Any]] = [
            ["hidden": ["../outside"], "order": []], ["hidden": ["same", "same"], "order": []],
            ["hidden": [], "order": Array(repeating: "panel", count: 257)],
            ["hidden": [], "order": [String(repeating: "x", count: 129)]],
            ["hidden": "invalid", "order": []], ["hidden": [], "order": [true]],
        ]
        for invalid in invalidSettings {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "panels-1", "action": "setPanelSettings", "panelScope": "viewer", "panelSettings": invalid]))
        }
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panels-1", "action": "setPanelSettings", "panelScope": "viewer"]))
    }

    func testNativeEditorNavigationKeepsAdjacentSurfacesAndRejectsUnknownViews() throws {
        let sections = AppSection.allCases
        let tools = try XCTUnwrap(sections.firstIndex(of: .assets))
        XCTAssertEqual(sections[tools + 1], .viewer)
        XCTAssertEqual(AppSection.assets.title("ko"), "에셋 편집 도구")
        XCTAssertEqual(AppSection.viewer.title("ko"), "3D 모델")
        XCTAssertEqual(EditorSurface.tools.section, .assets)
        XCTAssertEqual(EditorSurface.viewer.section, .viewer)
        XCTAssertEqual(EditorSurface.tools.command, "showTools")
        XCTAssertEqual(EditorSurface.viewer.command, "showViewer")
        for name in ["tools", "viewer"] {
            let request = try NativeRequest.parse(["id": "editor-1", "action": "setEditorSurface", "editorSurface": name])
            XCTAssertEqual(request.editorSurface?.rawValue, name)
        }
        let invalidViews: [Any] = ["gallery", "../outside", true, 1, ["tools"]]
        for invalid in invalidViews {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "editor-1", "action": "setEditorSurface", "editorSurface": invalid]))
        }
        XCTAssertThrowsError(try NativeRequest.parse(["id": "editor-1", "action": "setEditorSurface"]))
    }

    func testOptionalRuntimeStatusDoesNotInventRunningServer() throws {
        let value = try JSONDecoder().decode(RuntimeState.self, from: Data("{\"phase\":\"preparing\",\"prepared\":false}".utf8))
        XCTAssertFalse(value.serverRunning)
        XCTAssertFalse(value.prepared)
        XCTAssertEqual(value.phase, "preparing")
    }

    func testServerAddressAcceptsLiteralIPsWithoutResolvingArbitraryNames() {
        XCTAssertTrue(IPAddress.isLiteral("127.0.0.1"))
        XCTAssertTrue(IPAddress.isLiteral("192.168.1.20"))
        XCTAssertTrue(IPAddress.isLiteral("::1"))
        XCTAssertFalse(IPAddress.isLiteral("attacker.example"))
        XCTAssertFalse(IPAddress.isLiteral("127.0.0.1.attacker.example"))
        XCTAssertFalse(IPAddress.isLiteral("192.168.1.20:8080"))
    }

    func testColdOpenWaitsBeforeProcessCreationAndThroughoutPreparation() {
        let startup = [
            (launching: true, running: false, ready: false),
            (launching: true, running: true, ready: false),
            (launching: false, running: true, ready: false),
            (launching: false, running: true, ready: true),
        ]
        let decisions = startup.map {
            RuntimePreparationGate.evaluate(ready: $0.ready, launching: $0.launching,
                                            running: $0.running, failed: false, stopping: false)
        }
        XCTAssertEqual(decisions, [.waiting, .waiting, .waiting, .ready])
    }

    func testPendingDocumentDoesNotWaitAfterStartupFailureOrQuit() {
        XCTAssertEqual(RuntimePreparationGate.evaluate(ready: false, launching: false,
            running: false, failed: false, stopping: false), .unavailable)
        XCTAssertEqual(RuntimePreparationGate.evaluate(ready: false, launching: false,
            running: true, failed: true, stopping: false), .unavailable)
        XCTAssertEqual(RuntimePreparationGate.evaluate(ready: true, launching: false,
            running: true, failed: false, stopping: true), .unavailable)
    }

    func testQuitCleansUpOnceAndTerminatesOnlyOnTheCompletedRequest() {
        var gate = AppTerminationGate()
        XCTAssertEqual(gate.request(), .cleanUp)
        XCTAssertEqual(gate.request(), .cancel)
        XCTAssertEqual(gate.request(), .cancel)
        gate.cleanupFinished()
        XCTAssertEqual(gate.request(), .terminate)
        XCTAssertEqual(gate.request(), .terminate)
    }

    func testUnsolicitedCleanupCompletionCannotSkipChildCleanup() {
        var gate = AppTerminationGate()
        gate.cleanupFinished()
        XCTAssertEqual(gate.request(), .cleanUp)
    }
    func testPreparationUsesSharedPercentAndRequiresDurableCompletion() throws {
        func state(_ phase: String = "preparing", stage: String = "merging", done: Int = 1, total: Int = 2, percent: Int = 60) throws -> RuntimeState {
            let data = try JSONSerialization.data(withJSONObject: ["phase": phase, "prepared": false,
                "progress": ["stage": stage, "completed": done, "total": total, "percent": percent, "current": "masterdata.db"]])
            return try JSONDecoder().decode(RuntimeState.self, from: data)
        }
        let merging = try state()
        XCTAssertEqual(merging.preparationPercent, 60)
        XCTAssertFalse(merging.serverRunning)
        XCTAssertNil(try state(stage: "publishing", done: 1, total: 1, percent: 100).preparationPercent)
        XCTAssertNil(try state("error", stage: "complete", done: 1, total: 1, percent: 100).preparationPercent)
        XCTAssertNil(try state("stopping", stage: "complete", done: 1, total: 1, percent: 100).preparationPercent)
        XCTAssertNil(try state(stage: "complete", done: 0, total: 1, percent: 100).preparationPercent)
        XCTAssertEqual(try state(stage: "complete", done: 1, total: 1, percent: 100).preparationPercent, 100)
        XCTAssertNil(try state(stage: "unknown", percent: 60).preparationPercent)
        XCTAssertNil(try state(done: -1).preparationPercent)
        XCTAssertNil(try state(total: 0).preparationPercent)
        XCTAssertNil(RuntimeState().preparationPercent)
    }

    func testServerProcessRemainsLoadingUntilHttpReadinessAndCanRemainStopped() throws {
        func state(_ running: Bool, _ ready: Bool?) throws -> RuntimeState {
            var server: [String: Any] = ["running": running]
            if let ready { server["http_ready"] = ready }
            let data = try JSONSerialization.data(withJSONObject: ["phase": "ready", "prepared": true,
                "server_running": running, "server": server])
            return try JSONDecoder().decode(RuntimeState.self, from: data)
        }
        XCTAssertTrue(try state(true, false).serverLoading)
        XCTAssertTrue(try state(true, nil).serverLoading)
        XCTAssertFalse(try state(true, true).serverLoading)
        XCTAssertFalse(try state(false, false).serverLoading)
        XCTAssertFalse(try state(false, true).serverLoading)
        XCTAssertFalse(RuntimeState().serverLoading)
    }

    func testAssetToolsAndViewerAreAdjacentNativeDestinationsForOneEditor() throws {
        let sections = AppSection.allCases
        let tools = try XCTUnwrap(sections.firstIndex(of: .assets))
        XCTAssertEqual(sections[tools + 1], .viewer)
        XCTAssertEqual(AppSection.assets.title("ko"), "에셋 편집 도구")
        XCTAssertEqual(AppSection.viewer.title("ko"), "3D 모델")
        XCTAssertEqual(AppSection.assets.assetEditorSection, .tools)
        XCTAssertEqual(AppSection.viewer.assetEditorSection, .viewer)
        XCTAssertNil(AppSection.server.assetEditorSection)
        XCTAssertEqual(AssetEditorSection.tools.appSection, .assets)
        XCTAssertEqual(AssetEditorSection.viewer.appSection, .viewer)
    }

    func testEmbeddedAssetDestinationKeepsTheTrustedOriginAndExistingQuery() throws {
        let base = URL(string: "http://127.0.0.1:8123/editor?theme=dark&embedded=0#old")!
        for section in AssetEditorSection.allCases {
            let url = try XCTUnwrap(AssetEditorSection.embeddedURL(base, section: section))
            let components = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
            XCTAssertEqual(TrustedOrigin(url), TrustedOrigin(base))
            XCTAssertEqual(url.path, "/editor")
            XCTAssertEqual(components.fragment, section.rawValue)
            XCTAssertEqual(components.queryItems?.filter { $0.name == "embedded" }, [URLQueryItem(name: "embedded", value: "1")])
            XCTAssertTrue(components.queryItems?.contains(URLQueryItem(name: "theme", value: "dark")) == true)
        }
        XCTAssertNil(AssetEditorSection.embeddedURL(URL(string: "https://external.example/")!, section: .viewer))
    }

    func testPendingAssetNavigationKeepsTheLatestNativeSelectionAcrossPageReady() {
        var navigation = AssetNavigationState()
        navigation.select(.viewer)
        navigation.pageReady()
        XCTAssertEqual(navigation.desired, .viewer)
        XCTAssertTrue(navigation.needsUpdate)
        navigation.markSent(.tools) // An old completion cannot acknowledge the new destination.
        XCTAssertTrue(navigation.needsUpdate)
        navigation.markSent(.viewer)
        XCTAssertFalse(navigation.needsUpdate)
        navigation.select(.tools)
        navigation.retry(.viewer)
        XCTAssertEqual(navigation.desired, .tools)
        XCTAssertTrue(navigation.needsUpdate)
        navigation.pageChanged(.viewer)
        XCTAssertEqual(navigation.desired, .viewer)
        XCTAssertFalse(navigation.needsUpdate)
    }

    func testStaleRenderedAssetSectionCannotReplaceCurrentPageSelection() {
        for (current, stale) in [(AssetEditorSection.viewer, AssetEditorSection.tools),
                                 (AssetEditorSection.tools, AssetEditorSection.viewer)] {
            var navigation = AssetNavigationState(desired: stale)
            navigation.markSent(stale)
            navigation.pageChanged(current)

            XCTAssertFalse(navigation.selectFromRender(stale, currentSelection: current))
            XCTAssertEqual(navigation.desired, current)
            XCTAssertEqual(navigation.sent, current)
            XCTAssertFalse(navigation.needsUpdate)

            // A subsequent user selection of the other tab still takes effect.
            XCTAssertTrue(navigation.selectFromRender(stale, currentSelection: stale))
            XCTAssertEqual(navigation.desired, stale)
            XCTAssertTrue(navigation.needsUpdate)
            navigation.markSent(stale)
            XCTAssertFalse(navigation.needsUpdate)
        }
    }

    func testHiddenEditorRenderCannotChangeNavigationOrAcknowledgeReadiness() {
        var navigation = AssetNavigationState(desired: .viewer)
        navigation.markSent(.viewer)
        for rendered in AssetEditorSection.allCases {
            XCTAssertFalse(navigation.selectFromRender(rendered, currentSelection: nil))
            XCTAssertEqual(navigation.desired, .viewer)
            XCTAssertEqual(navigation.sent, .viewer)
            XCTAssertFalse(navigation.needsUpdate)
        }
        navigation.pageReady()
        XCTAssertFalse(navigation.selectFromRender(.tools, currentSelection: nil))
        XCTAssertEqual(navigation.desired, .viewer)
        XCTAssertNil(navigation.sent)
        XCTAssertTrue(navigation.needsUpdate)
    }

    func testCurrentRenderedNavigationRetainsRetryAndPageReadyTransitions() {
        var navigation = AssetNavigationState()
        navigation.markSent(.tools)
        XCTAssertTrue(navigation.selectFromRender(.viewer, currentSelection: .viewer))
        navigation.markSent(.viewer)
        navigation.retry(.viewer)
        XCTAssertNil(navigation.sent)
        XCTAssertTrue(navigation.needsUpdate)

        XCTAssertFalse(navigation.selectFromRender(.tools, currentSelection: .viewer))
        XCTAssertEqual(navigation.desired, .viewer)
        XCTAssertNil(navigation.sent)
        navigation.pageReady()
        XCTAssertTrue(navigation.selectFromRender(.viewer, currentSelection: .viewer))
        XCTAssertTrue(navigation.needsUpdate)
        navigation.markSent(.viewer)
        XCTAssertFalse(navigation.needsUpdate)

        navigation.retry(.tools)
        XCTAssertEqual(navigation.sent, .viewer)
        XCTAssertFalse(navigation.needsUpdate)
    }

    func testAssetSectionBridgeAcceptsOnlyKnownSectionsAndEvents() throws {
        for section in AssetEditorSection.allCases {
            for event in ["ready", "change"] {
                let request = try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": section.rawValue, "event": event])
                XCTAssertEqual(request.action, .setSection)
                XCTAssertEqual(request.section, section.rawValue)
                XCTAssertEqual(request.event, event)
            }
        }
        XCTAssertNoThrow(try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": "viewer"]))
        for section in ["", "textures", "assets", "../../viewer", "https://external.example"] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": section]))
        }
        XCTAssertThrowsError(try NativeRequest.parse(["id": "navigation-1", "action": "setSection"]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": true]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": "viewer", "event": "unknown"]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "navigation-1", "action": "setSection", "section": "viewer", "event": true]))
    }

    func testConsoleRegionUsesJapaneseOnlyForJapaneseAndKeepsExplicitChoices() {
        XCTAssertEqual(ConsoleRegion.defaultRegion(language: "ja"), .jp)
        for language in ["en", "ko", "zh", "", "unknown"] {
            XCTAssertEqual(ConsoleRegion.defaultRegion(language: language), .gl)
        }
        XCTAssertEqual(Set(ConsoleRegion.allCases.map(\.rawValue)), ["gl", "jp", "both"])
        XCTAssertEqual(ConsoleAction.downloadArchive.requestBody(region: .both)["region"], "both")
        XCTAssertNil(ConsoleAction.downloadPacks.requestBody(region: .jp)["region"])
    }

    func testConsoleActionsUseFixedNamesAndExplicitResetConfirmation() throws {
        let actions: [ConsoleAction] = [.downloadArchive, .downloadPacks, .cdnCacheToggle,
                                       .rebuildAssets, .fixTrainingTrees, .resetServer]
        XCTAssertEqual(Set(actions.map(\.rawValue)), ["download_archive", "download_packs", "cdn_cache_toggle",
                                                     "rebuild_assets", "fix_training_trees", "reset_server"])
        for action in actions {
            let body = action.requestBody(region: .gl)
            XCTAssertEqual(body["action"], action.rawValue)
            XCTAssertEqual(body["confirmation"], "STOP_SERVER")
            if action == .resetServer {
                XCTAssertEqual(body["reset_confirmation"], "RESET_SERVER_AND_ACCOUNTS")
            } else {
                XCTAssertNil(body["reset_confirmation"])
            }
        }
        for action in ["runShell", "reset_accounts", "../download_archive", "download_packs; echo invalid"] {
            let encoded = try JSONSerialization.data(withJSONObject: action, options: .fragmentsAllowed)
            XCTAssertThrowsError(try JSONDecoder().decode(ConsoleAction.self, from: encoded))
        }
    }

    func testConsoleStateDecodesProgressAndRejectsUnknownActions() throws {
        let job: [String: Any] = ["id": "private-job-1", "action": "download_archive", "region": "gl",
            "status": "running", "running": true, "cancellable": true, "message": "Downloading",
            "progress": ["stage": "download", "completed": 5, "total": 10]]
        let encoded = try JSONSerialization.data(withJSONObject: ["cache_enabled": true, "job": job])
        let state = try JSONDecoder().decode(ConsoleState.self, from: encoded)
        XCTAssertEqual(state.cacheEnabled, true)
        XCTAssertEqual(state.job?.action, .downloadArchive)
        XCTAssertEqual(state.job?.region, .gl)
        XCTAssertEqual(state.job?.progress?.fraction, 0.5)
        let invalidProgress = try JSONSerialization.data(withJSONObject: ["completed": 11, "total": 10])
        XCTAssertNil(try JSONDecoder().decode(ConsoleState.Job.Progress.self, from: invalidProgress).fraction)
        var invalidJob = job
        invalidJob["action"] = "runShell"
        let invalid = try JSONSerialization.data(withJSONObject: ["job": invalidJob])
        XCTAssertThrowsError(try JSONDecoder().decode(ConsoleState.self, from: invalid))
        XCTAssertNil(try JSONDecoder().decode(RuntimeState.self, from: Data("{}".utf8)).console)
    }

    func testOfflineManagementProvidesOnlyPreparedLoopbackWebUIPages() throws {
        let data = Data("""
            {"server_running":false,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127"}}
            """.utf8)
        let state = try JSONDecoder().decode(RuntimeState.self, from: data)
        XCTAssertFalse(state.serverRunning)
        XCTAssertEqual(state.webUIURL(path: "/webui/admin/")?.absoluteString, "http://127.0.0.1:43127/webui/admin/")
        XCTAssertEqual(state.webUIURL(path: "/webui/user/")?.absoluteString, "http://127.0.0.1:43127/webui/user/")
        XCTAssertNil(state.webUIURL(path: "/asset/getPackUrl"))
        XCTAssertNil(state.webUIURL(path: "/static/test.pack"))
        let pending = try JSONDecoder().decode(RuntimeState.self,
            from: Data("{\"management\":{\"running\":true,\"http_ready\":false,\"url\":\"http://127.0.0.1:43127\"}}".utf8))
        XCTAssertNil(pending.webUIURL(path: "/webui/user/"))
    }

    func testOfflineManagementRefusesForeignAndMalformedOrigins() throws {
        for url in ["http://localhost:8123", "http://0.0.0.0:8123", "http://192.0.2.5:8123",
                    "http://127.0.0.1.attacker.example:8123", "https://127.0.0.1:8123",
                    "http://user@127.0.0.1:8123", "http://127.0.0.1:8123/path",
                    "http://127.0.0.1:8123/?query=1", "http://127.0.0.1:8123/#fragment", "http://127.0.0.1:0"] {
            let data = try JSONSerialization.data(withJSONObject: ["management": ["running": true, "http_ready": true, "url": url]])
            let state = try JSONDecoder().decode(RuntimeState.self, from: data)
            XCTAssertNil(state.webUIURL(path: "/webui/admin/"), url)
        }
    }

    func testWebUIRoutingFollowsTheReadyGameOrOfflineManagementRole() throws {
        var value: [String: Any] = ["server_running": true,
            "server": ["running": true, "http_ready": true, "url": "http://0.0.0.0:18080"],
            "management": ["running": true, "http_ready": true, "url": "http://127.0.0.1:43127"]]
        func state() throws -> RuntimeState {
            try JSONDecoder().decode(RuntimeState.self, from: JSONSerialization.data(withJSONObject: value))
        }
        XCTAssertEqual(try state().webUIURL(path: "/webui/admin/")?.absoluteString, "http://127.0.0.1:18080/webui/admin/")
        value["server"] = ["running": true, "http_ready": false, "url": "http://0.0.0.0:18080"]
        XCTAssertNil(try state().webUIURL(path: "/webui/admin/"))
        value["server_running"] = false
        XCTAssertEqual(try state().webUIURL(path: "/webui/admin/")?.port, 43127)
    }

    func testGameConnectionAddressDoesNotFollowTheSourceCDN() throws {
        let data = Data("""
            {"server_address":"0.0.0.0:18080","cdn_server":"https://original.example/static/","default_cdn_server":"https://default.example/static/"}
            """.utf8)
        let config = try JSONDecoder().decode(ServerNetworkConfig.self, from: data)
        XCTAssertEqual(config.localServerURL?.absoluteString, "http://127.0.0.1:18080")
        XCTAssertEqual(config.cdnServer, "https://original.example/static/")
        XCTAssertEqual(config.defaultCdnServer, "https://default.example/static/")
        XCTAssertEqual(ServerNetworkConfig(serverAddress: "[::]:8080", cdnServer: "https://other.example/").localServerURL?.absoluteString,
                       "http://[::1]:8080")
        XCTAssertNil(ServerNetworkConfig(serverAddress: "untrusted.example:8080", cdnServer: "https://original.example/").localServerURL)
    }

    @MainActor
    func testManagementDemandIsLazyAndSurvivesMenuChangesWhilePreparing() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        model.selectedSection = .viewer
        model.retryManagement()
        XCTAssertFalse(model.managementSessionWanted)
        XCTAssertNil(model.process)

        model.selectedSection = .settings
        model.retryManagement()
        XCTAssertFalse(model.managementSessionWanted)
        model.selectedSection = .serverSettings
        model.retryManagement()
        XCTAssertTrue(model.managementSessionWanted)
        XCTAssertNil(model.process, "Opening management during preparation must record demand without eagerly launching another runtime.")

        for section in [AppSection.viewer, .content, .server, .accounts, .settings, .serverSettings] {
            model.selectedSection = section
            model.retryManagement()
            XCTAssertTrue(model.managementSessionWanted, "Navigating away must not revoke the app session's management demand.")
        }
        await model.stopRuntime()
        XCTAssertFalse(model.managementSessionWanted, "Runtime shutdown must release retained management demand.")
    }

    @MainActor
    func testManagementMenuRoundTripsKeepBothBrowsersAndTheirOrigin() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        let ready = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127"}}
            """.utf8))
        XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
        let settings = model.browser(.serverSettings)
        let accounts = model.browser(.accounts)
        defer { model.clearGoBrowsers() }
        model.selectedSection = .accounts
        model.retryManagement()

        for section in [AppSection.viewer, .content, .server, .settings, .serverSettings, .accounts] {
            model.selectedSection = section
            XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
            XCTAssertTrue(model.managementSessionWanted)
            XCTAssertEqual(model.goURL(path: "/webui/admin/")?.port, 43127)
            XCTAssertTrue(model.browser(.serverSettings) === settings)
            XCTAssertTrue(model.browser(.accounts) === accounts)
            XCTAssertNotNil(settings.webView.navigationDelegate)
            XCTAssertNotNil(accounts.webView.navigationDelegate)
        }
        model.quitting = true
        XCTAssertFalse(model.managementSessionWanted)
    }

    @MainActor
    func testLateRefreshCannotReplaceTheBrowserPublishedByManagementAcknowledgement() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        let ready = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127"}}
            """.utf8))
        let delayedRefresh = model.beginRuntimeStateRequest()
        let managementAcknowledgement = model.beginRuntimeStateRequest()
        XCTAssertTrue(model.applyRuntimeState(ready, for: managementAcknowledgement))
        let settings = model.browser(.serverSettings)
        let accounts = model.browser(.accounts)
        let editor = model.browser(.assets)
        defer { model.clearGoBrowsers(); editor.dispose() }

        // The ready acknowledgement can mount a page before the older GET ends.
        XCTAssertFalse(model.applyRuntimeState(ready, for: delayedRefresh))
        XCTAssertTrue(model.browser(.serverSettings) === settings)
        XCTAssertTrue(model.browser(.accounts) === accounts)
        XCTAssertNotNil(settings.webView.navigationDelegate)
        XCTAssertNotNil(accounts.webView.navigationDelegate)
        XCTAssertTrue(model.browser(.assets) === editor)
    }

    @MainActor
    func testChangedManagementOriginDisposesOldSessionsBeforePublishingTheNewSnapshot() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        func ready(_ port: Int) throws -> RuntimeState {
            try JSONDecoder().decode(RuntimeState.self, from: Data("""
                {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:\(port)"}}
                """.utf8))
        }
        XCTAssertTrue(model.applyRuntimeState(try ready(43127), for: model.beginRuntimeStateRequest()))
        let settings = model.browser(.serverSettings)
        let accounts = model.browser(.accounts)
        let editor = model.browser(.assets)
        defer { model.clearGoBrowsers(); editor.dispose() }
        var invalidatedBeforePublication = false
        let observation = model.$snapshot.dropFirst().sink { value in
            if value.webUIURL(path: "/webui/admin/")?.port == 43128 {
                invalidatedBeforePublication = settings.webView.navigationDelegate == nil
                    && accounts.webView.navigationDelegate == nil
            }
        }
        defer { observation.cancel() }

        XCTAssertTrue(model.applyRuntimeState(try ready(43128), for: model.beginRuntimeStateRequest()))
        XCTAssertTrue(invalidatedBeforePublication)
        XCTAssertEqual(model.goURL(path: "/webui/admin/")?.port, 43128)
        let replacement = model.browser(.serverSettings)
        XCTAssertFalse(replacement === settings)
        XCTAssertTrue(model.browser(.serverSettings) === replacement)
        XCTAssertFalse(model.browser(.accounts) === accounts)
        XCTAssertTrue(model.browser(.assets) === editor)
    }

    @MainActor
    func testSameURLBrowserReloadChangesViewIdentityAndRejectsEarlierEpochResponses() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        let ready = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127"}}
            """.utf8))
        XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
        let previous = model.browser(.serverSettings)
        let editor = model.browser(.assets)
        defer { model.clearGoBrowsers(); editor.dispose() }
        let delayedResponse = model.beginRuntimeStateRequest()
        let staleOrigin = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43126"}}
            """.utf8))
        let revision = model.goBrowserRevision

        model.clearGoBrowsers()
        let visible = model.browser(.serverSettings)
        XCTAssertNotEqual(ObjectIdentifier(visible.webView), ObjectIdentifier(previous.webView))
        XCTAssertEqual(model.goBrowserRevision, revision + 1)
        XCTAssertNil(previous.webView.navigationDelegate)
        XCTAssertFalse(model.applyRuntimeState(staleOrigin, for: delayedResponse))
        XCTAssertTrue(model.browser(.serverSettings) === visible)
        XCTAssertEqual(model.goURL(path: "/webui/admin/")?.port, 43127)
        XCTAssertTrue(model.browser(.assets) === editor)
    }

    func testAppAndServerSettingsAreDistinctLocalizedSidebarDestinations() {
        XCTAssertTrue(AppSection.allCases.contains(.settings))
        XCTAssertTrue(AppSection.allCases.contains(.serverSettings))
        for (language, app, server) in [("en", "App settings", "Server settings"),
                                      ("ko", "앱 설정", "서버 설정"), ("ja", "アプリ設定", "サーバー設定")] {
            XCTAssertEqual(AppSection.settings.title(language), app)
            XCTAssertEqual(AppSection.serverSettings.title(language), server)
        }
        XCTAssertNotEqual(AppSection.settings.symbol, AppSection.serverSettings.symbol)
        XCTAssertNil(AppSection.serverSettings.assetEditorSection)
    }

    func testLocalWebUICapabilityFollowsTheReadyRoleAndIsNeverAURLParameter() throws {
        let main = String(repeating: "a", count: 32), management = String(repeating: "b", count: 32)
        func state(running: Bool, ready: Bool = true) throws -> RuntimeState {
            let value: [String: Any] = ["server_running": running,
                "server": ["running": true, "http_ready": ready, "url": "http://0.0.0.0:18080", "local_webui_token": main],
                "management": ["running": true, "http_ready": true, "url": "http://127.0.0.1:43127", "local_webui_token": management]]
            return try JSONDecoder().decode(RuntimeState.self, from: JSONSerialization.data(withJSONObject: value))
        }
        for (running, expected, port) in [(true, main, 18080), (false, management, 43127)] {
            for path in ["/webui/admin/", "/webui/user/"] {
                let endpoint = try XCTUnwrap(try state(running: running).webUIEndpoint(path: path))
                XCTAssertEqual(endpoint.localWebUIToken, expected)
                XCTAssertEqual(endpoint.url.port, port)
                XCTAssertNil(URLComponents(url: endpoint.url, resolvingAgainstBaseURL: false)?.query)
                XCTAssertEqual(endpoint.initialRequest.value(forHTTPHeaderField: "X-Elichika-Local-Access"), expected)
                XCTAssertNil(endpoint.initialRequest.value(forHTTPHeaderField: "X-Elichika-Session"))
            }
        }
        XCTAssertNil(try state(running: true, ready: false).webUIEndpoint(path: "/webui/admin/"),
                     "A starting game role must never borrow the management role's capability.")
    }

    func testLocalWebUICapabilityIsOptionalAndRefusedForRemoteOrMalformedTokens() throws {
        let token = String(repeating: "a", count: 32)
        func endpoint(url: String, token: String?) throws -> RuntimeState.WebUIEndpoint? {
            var server: [String: Any] = ["running": true, "http_ready": true, "url": url]
            if let token { server["local_webui_token"] = token }
            let data = try JSONSerialization.data(withJSONObject: ["server_running": true, "server": server])
            return try JSONDecoder().decode(RuntimeState.self, from: data).webUIEndpoint(path: "/webui/admin/")
        }
        for value in [nil, "", "short", token + "\n", token + "\r\nInjected: true", String(repeating: "g", count: 32), String(repeating: "A", count: 32), String(repeating: "a", count: 64)] {
            let target = try XCTUnwrap(try endpoint(url: "http://127.0.0.1:18080", token: value))
            XCTAssertNil(target.localWebUIToken)
            XCTAssertNil(target.initialRequest.value(forHTTPHeaderField: "X-Elichika-Local-Access"))
        }
        for address in ["192.0.2.8", "[2001:db8::8]"] {
            let target = try XCTUnwrap(try endpoint(url: "http://\(address):18080", token: token))
            XCTAssertNil(target.localWebUIToken)
            XCTAssertNil(target.initialRequest.value(forHTTPHeaderField: "X-Elichika-Local-Access"))
        }
        let ipv6 = try XCTUnwrap(try endpoint(url: "http://[::]:18080", token: token))
        XCTAssertEqual(ipv6.url.absoluteString, "http://[::1]:18080/webui/admin/")
        XCTAssertEqual(ipv6.initialRequest.value(forHTTPHeaderField: "X-Elichika-Local-Access"), token)
    }

    @MainActor
    func testCapabilityRotationAtTheSamePortDisposesOnlyGoBrowsersBeforePublication() throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        func ready(_ token: String) throws -> RuntimeState {
            try JSONDecoder().decode(RuntimeState.self, from: Data("""
                {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127","local_webui_token":"\(token)"}}
                """.utf8))
        }
        let oldToken = String(repeating: "a", count: 32), newToken = String(repeating: "b", count: 32)
        XCTAssertTrue(model.applyRuntimeState(try ready(oldToken), for: model.beginRuntimeStateRequest()))
        let settings = model.browser(.serverSettings), accounts = model.browser(.accounts), editor = model.browser(.assets)
        defer { model.clearGoBrowsers(); editor.dispose() }
        XCTAssertEqual(settings.initialRequest?.value(forHTTPHeaderField: "X-Elichika-Local-Access"), oldToken)
        XCTAssertEqual(accounts.initialRequest?.value(forHTTPHeaderField: "X-Elichika-Local-Access"), oldToken)
        XCTAssertNil(editor.initialRequest)
        var invalidatedBeforePublication = false
        let observation = model.$snapshot.dropFirst().sink { value in
            if value.management?.localWebUIToken == newToken {
                invalidatedBeforePublication = settings.webView.navigationDelegate == nil && accounts.webView.navigationDelegate == nil
            }
        }
        defer { observation.cancel() }
        let revision = model.goBrowserRevision
        XCTAssertTrue(model.applyRuntimeState(try ready(newToken), for: model.beginRuntimeStateRequest()))
        XCTAssertTrue(invalidatedBeforePublication)
        XCTAssertEqual(model.goBrowserRevision, revision + 1)
        XCTAssertFalse(model.browser(.serverSettings) === settings)
        XCTAssertFalse(model.browser(.accounts) === accounts)
        XCTAssertEqual(model.browser(.serverSettings).initialRequest?.value(forHTTPHeaderField: "X-Elichika-Local-Access"), newToken)
        XCTAssertTrue(model.browser(.assets) === editor)
    }

    @MainActor
    func testSameCapabilityMenuRoundTripsPreserveAuthorizedBrowserRequestsAndSessions() throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        let token = String(repeating: "a", count: 32)
        let ready = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127","local_webui_token":"\(token)"}}
            """.utf8))
        XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
        let settings = model.browser(.serverSettings), accounts = model.browser(.accounts)
        defer { model.clearGoBrowsers() }
        let revision = model.goBrowserRevision
        for section in AppSection.allCases {
            model.selectedSection = section
            model.retryManagement()
            XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
            XCTAssertTrue(model.browser(.serverSettings) === settings)
            XCTAssertTrue(model.browser(.accounts) === accounts)
            XCTAssertEqual(model.goBrowserRevision, revision)
            XCTAssertEqual(accounts.initialRequest?.value(forHTTPHeaderField: "X-Elichika-Local-Access"), token)
        }
    }

    @MainActor
    func testActiveGameRoleOwnsBothNativeBrowserBootstrapRequests() throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        let mainToken = String(repeating: "a", count: 32), managementToken = String(repeating: "b", count: 32)
        let ready = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"server_running":true,
             "server":{"running":true,"http_ready":true,"url":"http://0.0.0.0:18080","local_webui_token":"\(mainToken)"},
             "management":{"running":true,"http_ready":true,"url":"http://127.0.0.1:43127","local_webui_token":"\(managementToken)"}}
            """.utf8))
        XCTAssertTrue(model.applyRuntimeState(ready, for: model.beginRuntimeStateRequest()))
        defer { model.clearGoBrowsers() }
        for route in [BrowserRoute.serverSettings, .accounts] {
            let request = try XCTUnwrap(model.browser(route).initialRequest)
            XCTAssertEqual(request.url?.host, "127.0.0.1")
            XCTAssertEqual(request.url?.port, 18080)
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Elichika-Local-Access"), mainToken)
            XCTAssertNil(request.value(forHTTPHeaderField: "X-Elichika-Session"))
        }
    }

}
