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
}
