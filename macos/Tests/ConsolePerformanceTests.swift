import AppKit
import Combine
import Foundation
import XCTest
@testable import ElichikaMac

final class ConsolePerformanceTests: XCTestCase {
    @MainActor
    func testUnchangedPollsDoNotPublishRuntimeState() throws {
        let model = AppModel(arguments: [], resources: nil)
        let state = try JSONDecoder().decode(RuntimeState.self, from: Data("""
            {"phase":"ready","prepared":true,"server_running":true,
             "server":{"running":true,"http_ready":true,"url":"http://127.0.0.1:8080"}}
            """.utf8))
        XCTAssertTrue(model.applyRuntimeState(state, for: model.beginRuntimeStateRequest()))
        var publications = 0
        let observer = model.objectWillChange.sink { publications += 1 }
        for _ in 0..<100 {
            XCTAssertTrue(model.applyRuntimeState(state, for: model.beginRuntimeStateRequest()))
        }
        XCTAssertEqual(publications, 0)
        var changed = state
        changed.serverRunning = false
        XCTAssertTrue(model.applyRuntimeState(changed, for: model.beginRuntimeStateRequest()))
        XCTAssertGreaterThan(publications, 0, "A real server transition must still reach controls immediately.")
        withExtendedLifetime(observer) {}
    }

    @MainActor
    func testOneLogBatchPublishesOnlyTheLogLeafAndKeepsExactTail() {
        let model = AppModel(arguments: [], resources: nil)
        var rootPublications = 0, logPublications = 0
        let root = model.objectWillChange.sink { rootPublications += 1 }
        let leaf = model.consoleLogs.objectWillChange.sink { logPublications += 1 }
        let incoming = (0..<2000).map { "line \($0)" }
        model.appendLogs(incoming)
        XCTAssertEqual(rootPublications, 0)
        XCTAssertEqual(logPublications, 1)
        XCTAssertEqual(model.console, Array(incoming.suffix(1500)))
        XCTAssertEqual(model.consoleLogs.snapshot.text, model.console.joined(separator: "\n"))
        model.appendLogs([])
        XCTAssertEqual(logPublications, 1)
        withExtendedLifetime([root, leaf]) {}
    }

    @MainActor
    func testUnicodeRollingDeltasRebuildTheSameSelectableDocument() {
        let store = ConsoleLogStore(limit: 3)
        var rendered = NSMutableString(string: "")
        for incoming in [["가나🙂", "second"], ["third"], ["fourth", "다섯🙂"],
                         ["six", "seven", "eight", "nine"], ["final"]] {
            let previous = store.snapshot.revision
            store.append(contentsOf: incoming)
            let update = store.snapshot
            XCTAssertEqual(update.previousRevision, previous)
            XCTAssertLessThanOrEqual(update.removedUTF16Count, rendered.length)
            rendered.deleteCharacters(in: NSRange(location: 0, length: update.removedUTF16Count))
            rendered.append(update.appendedText)
            XCTAssertEqual(rendered as String, update.text)
            XCTAssertLessThanOrEqual(store.lines.count, 3)
        }
    }

    @MainActor
    func testLongLinesAndErrorsRemainOrderedAndImmediatelyAvailable() {
        let store = ConsoleLogStore(limit: 3)
        store.append(contentsOf: [String(repeating: "🙂", count: 5000), "ordinary", "ERROR: synthetic failure"])
        XCTAssertEqual(store.lines.first?.count, 4096)
        XCTAssertEqual(store.lines.last, "ERROR: synthetic failure")
        XCTAssertTrue(store.snapshot.text.hasSuffix("ordinary\nERROR: synthetic failure"))
    }

    @MainActor
    func testSkippedRenderRevisionsKeepTheSameSurvivingSelection() {
        let store = ConsoleLogStore(limit: 5)
        store.append(contentsOf: ["remove🙂", "keep selected", "anchor", "tail"])
        let displayed = store.snapshot
        let selection = (displayed.text as NSString).range(of: "keep selected")
        store.append(contentsOf: ["new one"])
        store.append(contentsOf: ["new two"])
        let coalesced = store.snapshot
        XCTAssertNotEqual(coalesced.previousRevision, displayed.revision)
        let shift = coalesced.headUTF16Offset - displayed.headUTF16Offset
        let surviving = NSRange(location: selection.location - shift, length: selection.length)
        XCTAssertEqual((coalesced.text as NSString).substring(with: surviving), "keep selected")
        XCTAssertEqual(shift, ("remove🙂\n" as NSString).length)
    }

    func testRuntimeEqualityIncludesErrorsReadinessAndPrivateTokenRotation() throws {
        func state(_ token: String, error: String = "") throws -> RuntimeState {
            let raw: [String: Any] = ["phase": "ready", "prepared": true, "error": error,
                "management": ["running": true, "http_ready": true, "url": "http://127.0.0.1:43127",
                               "local_webui_token": token]]
            return try JSONDecoder().decode(RuntimeState.self, from: JSONSerialization.data(withJSONObject: raw))
        }
        let first = try state(String(repeating: "a", count: 32))
        XCTAssertEqual(first, try state(String(repeating: "a", count: 32)))
        XCTAssertNotEqual(first, try state(String(repeating: "b", count: 32)))
        XCTAssertNotEqual(first, try state(String(repeating: "a", count: 32), error: "new failure"))
    }
}
