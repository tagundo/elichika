import Foundation
import XCTest
@testable import ElichikaMac

final class RuntimeContractTests: XCTestCase {
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
        for width in [0, 240, 416, 640] {
            let preference = try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": width])
            XCTAssertEqual(preference.width, width)
        }
        for width in [-1, 239, 641] {
            XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": width]))
        }
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth"]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": 300.5]))
        XCTAssertThrowsError(try NativeRequest.parse(["id": "panel-1", "action": "setViewerPanelWidth", "width": true]))
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
        XCTAssertEqual(sections[tools + 1], .model)
        XCTAssertEqual(AppSection.assets.title("ko"), "에셋 편집 도구")
        XCTAssertEqual(AppSection.model.title("ko"), "3D 모델")
        XCTAssertEqual(EditorSurface.tools.section, .assets)
        XCTAssertEqual(EditorSurface.viewer.section, .model)
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

}
