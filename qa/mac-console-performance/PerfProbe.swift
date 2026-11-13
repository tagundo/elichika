// QA only. Compile the same file with the C3 and patched production sources.
// Remove only the @main attribute on ElichikaMacApp in each temporary copy.
import AppKit
import Combine
import CryptoKit
import Darwin
import Foundation
import SwiftUI

private func digest(_ text: String) -> String {
    SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
}

private final class LatencySampler {
    private let queue = DispatchQueue(label: "elichika.qa.main-queue-latency")
    private var timer: DispatchSourceTimer?
    private var pending = false
    private var running = false
    private var samples: [Double] = []
    private var missed = 0

    func start() {
        queue.sync { running = true; samples = []; missed = 0 }
        let source = DispatchSource.makeTimerSource(queue: queue)
        source.schedule(deadline: .now(), repeating: .milliseconds(20))
        source.setEventHandler { [weak self] in
            guard let self else { return }
            guard self.running, !self.pending else {
                self.missed += 1; return
            }
            self.pending = true
            let sent = DispatchTime.now().uptimeNanoseconds
            DispatchQueue.main.async {
                let milliseconds = Double(DispatchTime.now().uptimeNanoseconds - sent) / 1_000_000
                self.queue.async {
                    if self.running { self.samples.append(milliseconds) }
                    self.pending = false
                }
            }
        }
        timer = source; source.resume()
    }

    func stop() -> [String: Any] {
        let source = timer
        source?.cancel()
        // The serial worker only sends asynchronous work to main; it never
        // waits for main. This snapshot has no NSLock or cross-queue cycle.
        let result: [String: Any] = queue.sync {
            running = false
            let values = samples.sorted()
            func percentile(_ fraction: Double) -> Double {
                guard !values.isEmpty else { return -1 }
                return values[min(values.count - 1, Int(Double(values.count - 1) * fraction))]
            }
            let maximum: Double = values.last ?? -1
            return ["samples": values.count, "p50_ms": percentile(0.50), "p95_ms": percentile(0.95),
                    "max_ms": maximum, "busy_timer_ticks": missed]
        }
        timer = nil
        withExtendedLifetime(source) {}
        return result
    }
}

@MainActor
private final class ProbeHostingView: NSHostingView<RootView> {
    var layoutPasses = 0
    var drawPasses = 0
    override func layout() { layoutPasses += 1; super.layout() }
    override func draw(_ dirtyRect: NSRect) { drawPasses += 1; super.draw(dirtyRect) }
}

@MainActor
private final class PerformanceProbe {
    let output: URL
    let model: AppModel
    let host: ProbeHostingView
    let window: NSWindow
    let resident: Int
    let visible: Bool
    let duration: Double
    let variant: String
    private var polling: Task<Void, Never>?
    private var pollingWanted = true
    private var refreshInFlight = false
    private var pollingFinished = false
    private var observers: [AnyCancellable] = []
    private var rootPublications = 0
    private var logPublications = 0
    private var result: [String: Any] = [:]

    init(arguments: [String]) throws {
        var options: [String: String] = [:]
        var index = 1
        while index + 1 < arguments.count {
            options[arguments[index]] = arguments[index + 1]; index += 2
        }
        guard let readyPath = options["--ready-file"], let outputPath = options["--output-dir"],
              let resident = Int(options["--resident-lines"] ?? ""), [0, 500, 1500].contains(resident),
              let duration = Double(options["--duration"] ?? "8"), (2...30).contains(duration),
              ["visible", "hidden"].contains(options["--visibility"] ?? ""),
              ["baseline", "patched"].contains(options["--variant"] ?? "") else {
            throw NSError(domain: "PerfProbeArguments", code: 1)
        }
        output = URL(fileURLWithPath: outputPath, isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let ready = try JSONDecoder().decode(RuntimeReady.self, from: Data(contentsOf: URL(fileURLWithPath: readyPath)))
        try ready.validate()
        self.resident = resident; self.duration = duration
        visible = options["--visibility"] == "visible"; variant = options["--variant"]!
        model = AppModel(arguments: ["perf-probe", "--smoke-test", output.path], resources: nil)
        model.connection = ready
        model.selectedSection = visible ? .server : .settings
        host = ProbeHostingView(rootView: RootView(model: model))
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Elichika native console performance QA"
        window.contentView = host
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        observers.append(model.objectWillChange.sink { [weak self] in self?.rootPublications += 1 })
        #if ELICHIKA_PERF_PATCHED
        observers.append(model.consoleLogs.objectWillChange.sink { [weak self] in self?.logPublications += 1 })
        #endif
    }

    private func write(_ filename: String, _ value: [String: Any]) throws {
        var types: [String] = []
        func inspect(_ member: Any, path: String) {
            types.append(path + ": " + String(reflecting: type(of: member)))
            if let values = member as? [String: Any] {
                for key in values.keys.sorted() {
                    if let child = values[key] { inspect(child, path: path + "." + key) }
                }
            } else if let values = member as? [Any] {
                for (index, child) in values.enumerated() { inspect(child, path: path + "[\(index)]") }
            } else if Mirror(reflecting: member).displayStyle == .optional {
                for child in Mirror(reflecting: member).children { inspect(child.value, path: path + "?") }
            } else if let number = member as? Double {
                types.append(path + ".is_finite: " + String(number.isFinite))
            }
        }
        inspect(value, path: "$")
        guard JSONSerialization.isValidJSONObject(value) else {
            try? Data(types.joined(separator: "\n").utf8).write(
                to: output.appendingPathComponent(filename + ".failed-type-diagnostics.txt"), options: .atomic)
            fputs("QA_JSON_TYPE_FAILURE \(filename)\n" + types.joined(separator: "\n") + "\n", stderr)
            throw NSError(domain: "PerfProbeUnsupportedJSON", code: 6)
        }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        if filename == "native-performance.json" {
            try Data(types.joined(separator: "\n").utf8).write(
                to: output.appendingPathComponent(filename + ".type-diagnostics.txt"), options: .atomic)
        }
        try data.write(to: output.appendingPathComponent(filename), options: .atomic)
    }

    private func cpu() -> (seconds: Double, rss: Int64) {
        var usage = rusage()
        getrusage(RUSAGE_SELF, &usage)
        return (Double(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec)
            + Double(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1_000_000, Int64(usage.ru_maxrss))
    }

    private func finishApplicationLoop() {
        NSApp.stop(nil)
        // stop() takes effect after nextEvent returns. An owned empty AppKit
        // event wakes that wait without touching a game or sending user input.
        if let wake = NSEvent.otherEvent(with: .applicationDefined, location: .zero,
                modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: 0, context: nil, subtype: 0, data1: 0, data2: 0) {
            NSApp.postEvent(wake, atStart: true)
        }
        CFRunLoopWakeUp(CFRunLoopGetMain())
    }

    func run() async {
        do {
            polling = Task { [weak self] in
                guard let self else { return }
                defer { self.pollingFinished = true }
                while self.pollingWanted && !Task.isCancelled {
                    self.refreshInFlight = true
                    await self.model.refresh()
                    self.refreshInFlight = false
                    guard self.pollingWanted, !Task.isCancelled else { break }
                    do { try await Task.sleep(nanoseconds: 700_000_000) }
                    catch { break }
                }
            }
            let readyDeadline = ProcessInfo.processInfo.systemUptime + 120
            while (!model.snapshot.serverRunning || model.console.count < resident)
                && ProcessInfo.processInfo.systemUptime < readyDeadline {
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            guard model.snapshot.serverRunning, model.console.count >= resident else {
                throw NSError(domain: "PerfProbeReadiness", code: 2)
            }
            // Let initial decoding and first document layout finish before CPU
            // timing. No workload or log content is omitted from the real view.
            try await Task.sleep(nanoseconds: 700_000_000)
            try write("ready-for-workload.json", ["status": "READY", "pid": ProcessInfo.processInfo.processIdentifier,
                "resident_lines": model.console.count, "visibility": visible ? "visible" : "hidden", "variant": variant])
            let command = output.appendingPathComponent("workload-started.json")
            let startDeadline = ProcessInfo.processInfo.systemUptime + 30
            while !FileManager.default.fileExists(atPath: command.path)
                && ProcessInfo.processInfo.systemUptime < startDeadline {
                try await Task.sleep(nanoseconds: 20_000_000)
            }
            guard FileManager.default.fileExists(atPath: command.path) else {
                throw NSError(domain: "PerfProbeWorkloadStart", code: 3)
            }
            rootPublications = 0; logPublications = 0; host.layoutPasses = 0; host.drawPasses = 0
            let latency = LatencySampler()
            let before = cpu(); let start = ProcessInfo.processInfo.systemUptime
            latency.start()
            try write("measurement-started.json", ["status": "MEASURING", "uptime_seconds": start])
            try await Task.sleep(nanoseconds: UInt64(duration * 1_000_000_000))
            let end = ProcessInfo.processInfo.systemUptime
            let wall = end - start; let after = cpu()
            let cpuSeconds = after.seconds - before.seconds
            try write("native-stage.json", ["stage": "cpu_captured", "uptime_seconds": end,
                "wall_seconds": wall, "app_cpu_seconds": cpuSeconds, "app_cpu_percent": 100 * cpuSeconds / wall])
            let latencyResult = latency.stop()
            try write("measurement-ended.json", ["status": "MEASURED", "uptime_seconds": end])
            result = ["schema_version": 1, "status": "MEASURED_POSTCHECKS_PENDING",
                "variant": variant, "visibility": visible ? "visible" : "hidden",
                "resident_lines": resident, "retained_lines_at_end": model.console.count,
                "measurement_start_uptime": start, "measurement_end_uptime": end,
                "wall_seconds": wall, "app_cpu_seconds": cpuSeconds, "app_cpu_percent": 100 * cpuSeconds / wall,
                "peak_rss_bytes": after.rss, "main_queue_latency": latencyResult,
                "app_model_publications": rootPublications, "log_leaf_publications": logPublications,
                "hosting_layout_passes": host.layoutPasses, "hosting_draw_passes": host.drawPasses,
                "runtime_error_visible": model.message != nil,
                "original_full_app_runtime_validation": false]
            // Preserve numeric evidence even if task drain or native document
            // checks fail. Pending/failed records cannot satisfy the driver.
            try write("native-performance.json", result)
            pollingWanted = false
            polling?.cancel()
            try write("native-stage.json", ["stage": "poll_cancelled"])
            let drainDeadline = ProcessInfo.processInfo.systemUptime + 5
            while (!pollingFinished || refreshInFlight)
                && ProcessInfo.processInfo.systemUptime < drainDeadline {
                try await Task.sleep(nanoseconds: 20_000_000)
            }
            result["poll_drain_completed"] = pollingFinished && !refreshInFlight
            guard pollingFinished, !refreshInFlight else {
                try write("native-stage.json", ["stage": "poll_drain_timeout"])
                throw NSError(domain: "PerfProbePollDrain", code: 4)
            }
            polling = nil
            try write("native-stage.json", ["stage": "poll_drained"])
            result["selection_scroll_copy"] = await testSelectionScrollCopy()
            try write("native-stage.json", ["stage": "document_checked"])
            result["status"] = "MEASURED_SYNTHETIC_PROTOCOL_FIXTURE"
            try write("native-performance.json", result)
            try write("measurement-finished.json", ["status": "COMPLETE"])
            finishApplicationLoop()
        } catch {
            pollingWanted = false
            polling?.cancel()
            // Never serialize readiness, URLs, headers or arbitrary exception
            // text. The controller retains private fixture stderr separately.
            result["schema_version"] = 1
            result["status"] = "FAILED_NATIVE_PROBE"
            result["variant"] = variant
            result["error_type"] = String(describing: type(of: error))
            do { try write("native-performance.json", result) }
            catch {
                try? write("native-performance.json", ["schema_version": 1, "status": "FAILED_NATIVE_PROBE",
                    "variant": variant, "error_type": "Unsupported metric value; see failed type diagnostics"])
            }
            finishApplicationLoop()
        }
    }

    private func logDocument(in view: NSView) -> NSTextView? {
        if let text = view as? NSTextView, text.identifier?.rawValue == "console.logs.document" { return text }
        for child in view.subviews { if let found = logDocument(in: child) { return found } }
        return nil
    }

    private func visibleAnchor(_ text: NSTextView, _ scroll: NSScrollView) -> (line: String, character: Int, offset: Double)? {
        guard let layout = text.layoutManager, let container = text.textContainer,
              (text.string as NSString).length > 0 else { return nil }
        let point = NSPoint(x: 0, y: max(0, scroll.contentView.bounds.origin.y - text.textContainerInset.height))
        let raw = text.string as NSString
        let index = min(raw.length - 1, layout.characterIndex(for: point, in: container,
                            fractionOfDistanceBetweenInsertionPoints: nil))
        let glyph = layout.glyphIndexForCharacter(at: index)
        let y = layout.boundingRect(forGlyphRange: NSRange(location: glyph, length: 1), in: container).minY
        return (raw.substring(with: raw.lineRange(for: NSRange(location: index, length: 0))), index,
                Double(y + text.textContainerInset.height - scroll.contentView.bounds.origin.y))
    }

    private func viewportState(_ text: NSTextView, _ scroll: NSScrollView) -> [String: Any] {
        var state: [String: Any] = [
            "origin_x": Double(scroll.contentView.bounds.origin.x),
            "origin_y": Double(scroll.contentView.bounds.origin.y),
            "viewport_width": Double(scroll.contentView.bounds.width),
            "viewport_height": Double(scroll.contentView.bounds.height),
            "document_height": Double(text.bounds.height),
            "container_inset_y": Double(text.textContainerInset.height),
            "selected_location": text.selectedRange().location,
            "selected_length": text.selectedRange().length,
            "text_utf16_count": (text.string as NSString).length,
        ]
        if let anchor = visibleAnchor(text, scroll) {
            state["visible_character"] = anchor.character
            state["glyph_offset_y"] = anchor.offset
            state["visible_line_sha256"] = digest(anchor.line)
        }
        return state
    }

    private func captureViewport(_ scroll: NSScrollView, filename: String) -> Bool {
        let view = scroll.contentView
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { return false }
        do { try data.write(to: output.appendingPathComponent(filename), options: .atomic); return true }
        catch { return false }
    }

    private struct SettledViewport {
        let anchor: (line: String, character: Int, offset: Double)
        let witnesses: [[String: Any]]
    }

    private func settleVisibleViewport(_ text: NSTextView, _ scroll: NSScrollView) async -> SettledViewport? {
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        var previous: (character: Int, offset: Double, originX: Double, originY: Double)?
        var stableReads = 0
        var witnesses: [[String: Any]] = []
        while ProcessInfo.processInfo.systemUptime < deadline {
            host.layoutSubtreeIfNeeded()
            scroll.layoutSubtreeIfNeeded()
            text.layoutSubtreeIfNeeded()
            if let layout = text.layoutManager, let container = text.textContainer {
                layout.ensureLayout(forBoundingRect: text.visibleRect, in: container)
            }
            text.displayIfNeeded(); scroll.displayIfNeeded()
            guard let anchor = visibleAnchor(text, scroll) else { return nil }
            let x = Double(scroll.contentView.bounds.origin.x)
            let y = Double(scroll.contentView.bounds.origin.y)
            let witness = viewportState(text, scroll)
            witnesses.append(witness)
            let sameTurnStable = (witness["visible_character"] as? Int) == anchor.character
                && (witness["glyph_offset_y"] as? Double).map { abs($0 - anchor.offset) <= 0.01 } == true
                && (witness["origin_x"] as? Double) == x && (witness["origin_y"] as? Double) == y
            if sameTurnStable, let previous, previous.character == anchor.character,
               abs(previous.offset - anchor.offset) <= 0.01,
               abs(previous.originX - x) <= 0.01, abs(previous.originY - y) <= 0.01 {
                stableReads += 1
            } else { stableReads = 0 }
            if stableReads >= 2 { return SettledViewport(anchor: anchor, witnesses: witnesses) }
            previous = (anchor.character, anchor.offset, x, y)
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        return nil
    }

    private func testSelectionScrollCopy() async -> [String: Any] {
        #if ELICHIKA_PERF_PATCHED
        model.selectedSection = .server
        try? await Task.sleep(nanoseconds: 200_000_000)
        guard let text = logDocument(in: host), let scroll = text.enclosingScrollView else {
            return ["status": "FAIL", "reason": "Actual native log document is absent"]
        }
        if model.console.count < 1500 {
            model.appendLogs((0..<1500).map { "QA resident line \($0) keep-copy-scroll-marker" })
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
        let lines = text.string.components(separatedBy: "\n")
        guard lines.count >= 500 else { return ["status": "FAIL", "reason": "Document did not render the resident lines"] }
        let line = lines.count / 2
        let location = lines.prefix(line).reduce(0) { $0 + ($1 as NSString).length + 1 }
        let range = NSRange(location: location, length: (lines[line] as NSString).length)
        guard range.length > 0 else { return ["status": "FAIL", "reason": "Empty selection fixture"] }
        text.setSelectedRange(range); text.scrollRangeToVisible(range)
        guard let beforeSettled = await settleVisibleViewport(text, scroll) else {
            return ["status": "FAIL", "reason": "Visible layout did not settle before the reader anchor"]
        }
        let selected = (text.string as NSString).substring(with: text.selectedRange())
        let anchor = beforeSettled.anchor
        let beforeHead = model.consoleLogs.snapshot.headUTF16Offset
        let beforeViewport = viewportState(text, scroll)
        let beforeImage = captureViewport(scroll, filename: "viewport-before.png")
        let beforeCaptureViewport = viewportState(text, scroll)
        // No await between these appends: SwiftUI must be allowed to coalesce
        // both store revisions before updating the actual NSTextView.
        model.appendLogs((0..<40).map { "QA coalesced A \($0)" })
        model.appendLogs((0..<40).map { "QA coalesced B \($0)" })
        let renderDeadline = ProcessInfo.processInfo.systemUptime + 2
        while !text.string.hasSuffix("QA coalesced B 39") && ProcessInfo.processInfo.systemUptime < renderDeadline {
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        guard text.string.hasSuffix("QA coalesced B 39"),
              let afterSettled = await settleVisibleViewport(text, scroll) else {
            return ["status": "FAIL", "reason": "Updated native text or visible layout did not settle"]
        }
        let after = (text.string as NSString).substring(with: text.selectedRange())
        let afterAnchor = afterSettled.anchor
        let headShift = model.consoleLogs.snapshot.headUTF16Offset - beforeHead
        let afterViewport = viewportState(text, scroll)
        let afterImage = captureViewport(scroll, filename: "viewport-after.png")
        let afterCaptureViewport = viewportState(text, scroll)
        try? write("viewport-state.json", ["before": beforeViewport, "before_after_capture": beforeCaptureViewport,
            "after": afterViewport, "after_after_capture": afterCaptureViewport,
            "before_layout_witnesses": beforeSettled.witnesses, "after_layout_witnesses": afterSettled.witnesses,
            "head_shift_utf16": headShift, "before_head_utf16": beforeHead,
            "after_head_utf16": model.consoleLogs.snapshot.headUTF16Offset])
        text.copy(nil)
        let copied = NSPasteboard.general.string(forType: .string)
        let selectionOK = after == selected && copied == selected
        NSPasteboard.general.clearContents()
        let characterDelta = abs(afterAnchor.character - max(0, anchor.character - headShift))
        let pixelDelta = abs(afterAnchor.offset - anchor.offset)
        let anchorOK = anchor.line == afterAnchor.line && characterDelta <= 1 && pixelDelta <= 1.5
        text.setSelectedRange(NSRange(location: (text.string as NSString).length, length: 0))
        text.scrollToEndOfDocument(nil)
        model.appendLogs(["QA tail follows last appended line"])
        try? await Task.sleep(nanoseconds: 100_000_000)
        let tailOK = scroll.contentView.bounds.maxY >= text.bounds.maxY - 20
        return ["status": selectionOK && anchorOK && tailOK && beforeImage && afterImage ? "PASS" : "FAIL",
            "same_selection_and_copy": selectionOK, "same_visible_anchor_after_two_coalesced_batches": anchorOK,
            "visible_anchor_character_delta": characterDelta, "visible_anchor_pixel_offset_delta": pixelDelta,
            "viewport_before": beforeViewport, "viewport_after": afterViewport,
            "viewport_images_captured": beforeImage && afterImage,
            "tail_follows_when_already_at_bottom": tailOK, "selection_sha256": digest(selected),
            "selected_utf16_count": (selected as NSString).length,
            "actual_ns_text_view": true]
        #else
        return ["status": "NOT_APPLICABLE_BASELINE", "reason": "Baseline SwiftUI Text has no new native-document API"]
        #endif
    }
}

@MainActor
private final class ProbeApplication: NSApplication {
    override func reportException(_ exception: NSException) {
        // QA-only fail-fast diagnostics. The controller retains this stream
        // privately, redacts its capability values, and exports bounded text.
        fputs("QA_OBJC_EXCEPTION \(exception.name.rawValue): \(exception.reason ?? "no reason")\n", stderr)
        fputs(exception.callStackSymbols.joined(separator: "\n") + "\n", stderr)
        fflush(stderr)
        exit(3)
    }
}

@main
@MainActor
private struct MacPerformanceMain {
    static func main() {
        let app = ProbeApplication.shared
        app.setActivationPolicy(.regular)
        fputs("QA application class: \(NSStringFromClass(type(of: app)))\n", stderr)
        do {
            let probe = try PerformanceProbe(arguments: CommandLine.arguments)
            Task { await probe.run() }
            app.run()
            withExtendedLifetime(probe) {}
        } catch {
            fputs("Native performance probe setup failed.\n", stderr)
            exit(2)
        }
    }
}
