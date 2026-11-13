import AppKit
import Foundation
import SwiftUI
import XCTest
@testable import ElichikaMac

final class ConsoleWrappedScrollTests: XCTestCase {
    @MainActor
    func testWrappedUnicodeScrollbackSurvivesCoalescedHeadTrimming() async throws {
        _ = NSApplication.shared
        let model = AppModel(arguments: [], resources: nil)
        model.selectedSection = .server
        let host = NSHostingView(rootView: RootView(model: model))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                              styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.makeKeyAndOrderFront(nil)
        defer { window.orderOut(nil); window.contentView = nil; window.close() }
        // Match actual log loading: the empty native document must already
        // have its real window width before the first large batch arrives.
        // Seeding before window creation can eagerly lay out the whole prefix
        // during initial sizing and miss the noncontiguous-layout regression.
        try await waitUntil { self.logDocument(in: host) != nil }
        let text = try XCTUnwrap(logDocument(in: host))
        let scroll = try XCTUnwrap(text.enclosingScrollView)
        host.layoutSubtreeIfNeeded(); scroll.layoutSubtreeIfNeeded()
        text.displayIfNeeded(); window.displayIfNeeded()
        XCTAssertTrue(text.string.isEmpty)
        XCTAssertGreaterThan(scroll.contentView.bounds.width, 0)
        try await Task.sleep(nanoseconds: 200_000_000)
        model.appendLogs((0..<1500).map {
            String(format: "resident-%04d Unicode 測定 😀 ", $0) + String(repeating: "x", count: 480)
        })
        try await waitUntil { text.string.hasSuffix(String(repeating: "x", count: 480)) }
        let lines = text.string.components(separatedBy: "\n")
        XCTAssertEqual(lines.count, 1500)
        let middle = lines.count / 2
        let location = lines.prefix(middle).reduce(0) { $0 + ($1 as NSString).length + 1 }
        text.setSelectedRange(NSRange(location: location, length: (lines[middle] as NSString).length))
        text.scrollRangeToVisible(text.selectedRange())
        let before = try await settledAnchor(text, scroll)
        let beforeHead = model.consoleLogs.snapshot.headUTF16Offset
        let selected = (text.string as NSString).substring(with: text.selectedRange())
        let beforePixels = try viewportPixels(scroll)

        // No suspension between appends: exercise SwiftUI's skipped render
        // revision path while 80 long, wrapped Unicode paragraphs expire.
        model.appendLogs((0..<40).map { "QA coalesced A \($0)" })
        model.appendLogs((0..<40).map { "QA coalesced B \($0)" })
        try await waitUntil { text.string.hasSuffix("QA coalesced B 39") }
        let after = try await settledAnchor(text, scroll)
        let removed = model.consoleLogs.snapshot.headUTF16Offset - beforeHead
        XCTAssertEqual(removed, 40720)
        XCTAssertEqual(after.line, before.line, "The same wrapped paragraph must stay visible.")
        XCTAssertLessThanOrEqual(abs(after.character - (before.character - removed)), 1)
        XCTAssertLessThanOrEqual(abs(after.offset - before.offset), 1.5)
        XCTAssertEqual((text.string as NSString).substring(with: text.selectedRange()), selected)
        text.copy(nil)
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), selected)
        NSPasteboard.general.clearContents()
        XCTAssertEqual(try viewportPixels(scroll), beforePixels,
                       "Appending logs must preserve the pixels the reader was viewing.")
        text.setSelectedRange(NSRange(location: (text.string as NSString).length, length: 0))
        text.scrollToEndOfDocument(nil)
        model.appendLogs(["QA tail follows last appended line"])
        try await waitUntil { text.string.hasSuffix("QA tail follows last appended line") }
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertGreaterThanOrEqual(scroll.contentView.bounds.maxY, text.bounds.maxY - 20)
    }

    @MainActor
    private func logDocument(in view: NSView) -> NSTextView? {
        if let text = view as? NSTextView, text.identifier?.rawValue == "console.logs.document" { return text }
        for child in view.subviews { if let found = logDocument(in: child) { return found } }
        return nil
    }

    @MainActor
    private func waitUntil(_ condition: () -> Bool) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 10
        while !condition(), ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertTrue(condition(), "The actual native document did not update before the deadline.")
    }

    @MainActor
    private func anchor(_ text: NSTextView, _ scroll: NSScrollView) throws -> (character: Int, offset: CGFloat, line: String) {
        let layout = try XCTUnwrap(text.layoutManager), container = try XCTUnwrap(text.textContainer)
        let raw = text.string as NSString
        guard raw.length > 0 else {
            XCTFail("The native document is empty; a visible glyph cannot be sampled.")
            throw NSError(domain: "ConsoleWrappedScrollEmptyDocument", code: 1)
        }
        let point = NSPoint(x: 0, y: max(0, scroll.contentView.bounds.origin.y - text.textContainerInset.height))
        let index = min(raw.length - 1, layout.characterIndex(for: point, in: container,
                            fractionOfDistanceBetweenInsertionPoints: nil))
        let glyph = layout.glyphIndexForCharacter(at: index)
        let y = layout.boundingRect(forGlyphRange: NSRange(location: glyph, length: 1), in: container).minY
        return (index, y + text.textContainerInset.height - scroll.contentView.bounds.origin.y,
                raw.substring(with: raw.lineRange(for: NSRange(location: index, length: 0))))
    }

    @MainActor
    private func settledAnchor(_ text: NSTextView, _ scroll: NSScrollView) async throws -> (character: Int, offset: CGFloat, line: String) {
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        var previous: (character: Int, offset: CGFloat, line: String)?
        var stable = 0
        while ProcessInfo.processInfo.systemUptime < deadline {
            text.layoutSubtreeIfNeeded(); scroll.layoutSubtreeIfNeeded()
            if let layout = text.layoutManager, let container = text.textContainer {
                layout.ensureLayout(forBoundingRect: text.visibleRect, in: container)
            }
            text.displayIfNeeded(); scroll.displayIfNeeded()
            let current = try anchor(text, scroll)
            if let previous, previous.character == current.character, abs(previous.offset - current.offset) < 0.01 {
                stable += 1
            } else { stable = 0 }
            if stable >= 2 { return current }
            previous = current
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTFail("Visible native layout did not settle.")
        return try anchor(text, scroll)
    }

    @MainActor
    private func viewportPixels(_ scroll: NSScrollView) throws -> Data {
        let view = scroll.contentView
        let image = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: image)
        guard !image.isPlanar, image.bitsPerPixel % 8 == 0 else {
            XCTFail("The viewport bitmap must use a packed whole-byte pixel format.")
            throw NSError(domain: "ConsoleWrappedScrollBitmapFormat", code: 1)
        }
        let bytes = try XCTUnwrap(image.bitmapData)
        // Include format/dimensions and only actual pixel bytes. Row padding
        // is not image content and may contain unspecified allocator bytes.
        var pixels = Data("\(image.pixelsWide),\(image.pixelsHigh),\(image.bitsPerPixel),\(image.samplesPerPixel),\(image.bitmapFormat.rawValue)\n".utf8)
        let rowBytes = image.pixelsWide * image.bitsPerPixel / 8
        for row in 0..<image.pixelsHigh {
            pixels.append(bytes.advanced(by: row * image.bytesPerRow), count: rowBytes)
        }
        return pixels
    }
}
