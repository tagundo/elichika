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
        XCTAssertEqual(AppSection.assets.title("ko"), "에셋 편집툴")
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

}
