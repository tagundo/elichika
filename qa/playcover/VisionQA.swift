import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit
import Foundation
import ImageIO
import Vision

enum QAError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String { if case .invalid(let message) = self { return message }; return "QA error" }
}
func require(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw QAError.invalid(message) }
}
func normalized(_ value: String) -> String {
    value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
}
struct Window: Codable {
    let pid: Int32
    let id: UInt32
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}
struct Text: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}
struct Observation: Codable {
    let capturedUTC: String
    let capturedUptime: Double
    let window: Window
    let imageWidth: Int
    let imageHeight: Int
    let screenshot: String
    let screenshotSHA256: String
    let text: [Text]
}
func foreground(_ pid: Int32) throws {
    try require(AXIsProcessTrusted(), "Accessibility permission is unavailable; no request or system change was made")
    try require(CGPreflightScreenCaptureAccess(), "Screen capture permission is unavailable; no request or system change was made")
    try require(NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
                "The exact target PID must already be the foreground app")
    guard let app = NSRunningApplication(processIdentifier: pid) else { throw QAError.invalid("Target PID is absent") }
    try require(!app.isTerminated && app.isActive, "Target app must be active and running")
}
func window(_ pid: Int32, _ requested: UInt32?) throws -> Window {
    try foreground(pid)
    guard let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        throw QAError.invalid("Window-server list is unavailable")
    }
    var result: [Window] = []
    for row in rows {
        guard (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid,
              (row[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
              ((row[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 0) > 0,
              let id = (row[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
              let bounds = row[kCGWindowBounds as String] as? [String: Any],
              let rect = CGRect(dictionaryRepresentation: bounds as CFDictionary),
              rect.width > 50, rect.height > 50 else { continue }
        if let requested = requested, id != requested { continue }
        result.append(Window(pid: pid, id: id, x: rect.origin.x, y: rect.origin.y,
                             width: rect.width, height: rect.height))
    }
    guard let selected = result.max(by: { $0.width * $0.height < $1.width * $1.height }) else {
        throw QAError.invalid("No visible layer-zero window belongs to the exact foreground PID")
    }
    return selected
}
func observe(_ pid: Int32, _ requested: UInt32?, _ directory: URL, _ name: String) throws -> Observation {
    let target = try window(pid, requested)
    let screenshot = directory.appendingPathComponent(name + ".png")
    let timestamp = ProcessInfo.processInfo.systemUptime
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    process.arguments = ["-x", "-o", "-l", String(target.id), screenshot.path]
    let diagnostics = Pipe()
    process.standardOutput = diagnostics
    process.standardError = diagnostics
    try process.run()
    let captureDeadline = Date().addingTimeInterval(15)
    while process.isRunning && Date() < captureDeadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    if process.isRunning { process.terminate(); throw QAError.invalid("OS screenshot command timed out") }
    process.waitUntilExit()
    try require(process.terminationStatus == 0, "OS screenshot command failed")
    try foreground(pid)
    let after = try window(pid, target.id)
    try require(after.id == target.id && abs(after.x-target.x) < 0.5 && abs(after.y-target.y) < 0.5
                && abs(after.width-target.width) < 0.5 && abs(after.height-target.height) < 0.5,
                "Target window moved during the screenshot")
    guard let source = CGImageSourceCreateWithURL(screenshot as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw QAError.invalid("OS capture did not produce an image")
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.recognitionLanguages = ["en-US", "ja-JP"]
    request.automaticallyDetectsLanguage = true
    request.minimumTextHeight = 0.008
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    let text: [Text] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return Text(text: candidate.string, confidence: candidate.confidence,
                    x: box.origin.x, y: box.origin.y, width: box.width, height: box.height)
    }
    let bytes = try Data(contentsOf: screenshot)
    let record = Observation(capturedUTC: ISO8601DateFormatter().string(from: Date()), capturedUptime: timestamp,
                             window: target, imageWidth: image.width, imageHeight: image.height,
                             screenshot: screenshot.lastPathComponent,
                             screenshotSHA256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), text: text)
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try encoder.encode(record).write(to: directory.appendingPathComponent(name + ".json"), options: .withoutOverwriting)
    return record
}
func unique(_ record: Observation, exact: String?, regex: NSRegularExpression?) throws -> Text {
    let candidates = record.text.filter { item in
        guard item.confidence >= 0.75 else { return false }
        let text = normalized(item.text)
        if let exact = exact { return text == normalized(exact) }
        if let regex = regex {
            let range = NSRange(text.startIndex..<text.endIndex, in: text)
            return regex.firstMatch(in: text, range: range)?.range == range
        }
        return false
    }
    try require(candidates.count == 1, "Refuse OCR action: expected exactly one complete caption with confidence >=0.75; found \(candidates.count)")
    return candidates[0]
}
func click(_ record: Observation, _ target: Text) throws -> [String: Double] {
    try foreground(record.window.pid)
    let current = try window(record.window.pid, record.window.id)
    try require(ProcessInfo.processInfo.systemUptime-record.capturedUptime < 5,
                "OCR capture is stale; no event was sent")
    try require(abs(current.x-record.window.x) < 0.5 && abs(current.y-record.window.y) < 0.5
                && abs(current.width-record.window.width) < 0.5 && abs(current.height-record.window.height) < 0.5,
                "Window changed after OCR; no event was sent")
    let scaleX = Double(record.imageWidth)/current.width
    let scaleY = Double(record.imageHeight)/current.height
    try require(scaleX > 0 && abs(scaleX/scaleY-1) < 0.015,
                "Screenshot/window aspect ratio differs; no coordinate guess was made")
    let point = CGPoint(x: current.x + (target.x+target.width/2)*current.width,
                        y: current.y + (1-target.y-target.height/2)*current.height)
    try require(point.x.isFinite && point.y.isFinite && target.width > 0 && target.height > 0
                && point.x > current.x && point.x < current.x+current.width
                && point.y > current.y && point.y < current.y+current.height,
                "OCR center lies outside the target window")
    var displayCount: UInt32 = 0
    try require(CGGetActiveDisplayList(0, nil, &displayCount) == .success && displayCount > 0 && displayCount <= 16,
                "Physical display list is unavailable; no click was sent")
    var displays = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
    let displayResult = displays.withUnsafeMutableBufferPointer {
        CGGetActiveDisplayList(displayCount, $0.baseAddress, &displayCount)
    }
    try require(displayResult == .success && displays.prefix(Int(displayCount)).contains(where: { CGDisplayBounds($0).contains(point) }),
                "OCR target lies outside every active physical display; offscreen window pixels cannot authorize input")
    let eventSource = CGEventSource(stateID: .combinedSessionState)
    guard let move = CGEvent(mouseEventSource: eventSource, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left),
          let down = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
          let up = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
        throw QAError.invalid("OS mouse event creation failed")
    }
    move.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.03)
    try foreground(record.window.pid)
    down.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.12)
    up.post(tap: .cghidEventTap)
    return ["x":point.x, "y":point.y]
}
func type(_ pid: Int32, _ value: String) throws {
    try foreground(pid)
    try require(!value.isEmpty && value.utf16.count <= 256
                && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
                "Synthetic typing must be bounded text with no control keys/newlines")
    let units = Array(value.utf16)
    let source = CGEventSource(stateID: .combinedSessionState)
    guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else {
        throw QAError.invalid("OS keyboard event creation failed")
    }
    units.withUnsafeBufferPointer { buffer in
        down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
        up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
    }
    down.flags = []; up.flags = []
    down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
}
do {
    let args = Array(CommandLine.arguments.dropFirst())
    try require(!args.isEmpty && ["snapshot", "click", "type"].contains(args[0]), "Use snapshot|click|type with --pid and a fresh --proof-dir")
    let action = args[0]
    var values: [String: String] = [:]
    var index = 1
    while index < args.count {
        try require(index+1 < args.count && args[index].hasPrefix("--") && values[args[index]] == nil, "Invalid or repeated argument")
        values[args[index]] = args[index+1]; index += 2
    }
    try require(Set(values.keys).isSubset(of: ["--pid", "--window-id", "--proof-dir", "--exact", "--regex", "--text", "--synthetic"]), "Unknown option")
    guard let pid = Int32(values["--pid"] ?? ""), pid > 0, let directory = values["--proof-dir"] else { throw QAError.invalid("Positive exact PID and fresh proof directory required") }
    let proof = URL(fileURLWithPath: directory, isDirectory: true)
    try require(!FileManager.default.fileExists(atPath: proof.path), "Proof directory already exists")
    try FileManager.default.createDirectory(at: proof, withIntermediateDirectories: true)
    let requested = values["--window-id"].flatMap(UInt32.init)
    try require(values["--window-id"] == nil || requested != nil, "Invalid window ID")
    let initial = try observe(pid, requested, proof, "initial")
    var result: [String: Any] = ["status":"CAPTURED_REAL_PID_WINDOW_OCR", "action":action, "pid":pid, "windowID":initial.window.id]
    if action == "click" {
        try require((values["--exact"] != nil) != (values["--regex"] != nil), "Click requires exactly one --exact or --regex complete-caption selector")
        let regex = try values["--regex"].map { try NSRegularExpression(pattern: $0) }
        let first = try unique(initial, exact: values["--exact"], regex: regex)
        let fresh = try observe(pid, initial.window.id, proof, "pre-click")
        let second = try unique(fresh, exact: values["--exact"], regex: regex)
        try require(normalized(first.text) == normalized(second.text)
                    && abs(first.x-second.x) < 0.02 && abs(first.y-second.y) < 0.02
                    && abs(first.width-second.width) < 0.02 && abs(first.height-second.height) < 0.02,
                    "Caption changed between fresh captures; no click was sent")
        result["osMouseClick"] = try click(fresh, second)
        result["caption"] = second.text
        result["mouseHoldSeconds"] = 0.12
        result["status"] = "OS_MOUSE_EVENT_SENT_TO_FRESH_UNIQUE_OCR_CAPTION"
    } else if action == "type" {
        try require(values["--synthetic"] == "yes", "Typing is restricted to the explicitly authorized disposable synthetic QA account")
        guard let value = values["--text"] else { throw QAError.invalid("--text required") }
        // The caller must first focus the real input through AX or real OS clicks.
        // This sends text only, without Return, shortcuts, setters or submission.
        let fresh = try observe(pid, initial.window.id, proof, "pre-type")
        try require(ProcessInfo.processInfo.systemUptime-fresh.capturedUptime < 5,
                    "Pre-typing screenshot is stale; no text event was sent")
        _ = try window(pid, fresh.window.id)
        try type(pid, value)
        result["typedUTF16Characters"] = value.utf16.count
        result["status"] = "OS_TEXT_EVENT_SENT_TO_FOREGROUND_SYNTHETIC_APP"
    }
    try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: proof.appendingPathComponent("result.json"), options: .withoutOverwriting)
    print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
} catch {
    fputs("VisionQA failed: \(error)\n", stderr)
    exit(1)
}
