// QA-only external PlayCover library double-click. Never ship inside an IPA.
// Observation/uniqueness/freshness derived unchanged from VisionQA SHA256 6f32d9b3fb34f57fd9a99646aed95823a41fe456a5a24fe6444e66503bc1c534
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
    try require(app.bundleIdentifier == "io.playcover.PlayCover", "Only the foreground standard PlayCover application may receive a library double-click")
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
func doubleClick(_ record: Observation, _ target: Text) throws -> [String: Double] {
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
    let eventSource = CGEventSource(stateID: .combinedSessionState)
    guard let move = CGEvent(mouseEventSource: eventSource, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left),
          let down = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
          let up = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
        throw QAError.invalid("OS mouse event creation failed")
    }
    down.setIntegerValueField(.mouseEventClickState, value: 1)
    up.setIntegerValueField(.mouseEventClickState, value: 1)
    move.post(tap: .cghidEventTap); down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.08)
    try foreground(record.window.pid)
    let beforeSecond = try window(record.window.pid, record.window.id)
    try require(ProcessInfo.processInfo.systemUptime-record.capturedUptime < 5
                && abs(beforeSecond.x-current.x) < 0.5 && abs(beforeSecond.y-current.y) < 0.5
                && abs(beforeSecond.width-current.width) < 0.5 && abs(beforeSecond.height-current.height) < 0.5,
                "PlayCover window changed before second click; no second event was sent")
    guard let secondDown = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
          let secondUp = CGEvent(mouseEventSource: eventSource, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
        throw QAError.invalid("Second OS mouse event creation failed")
    }
    secondDown.setIntegerValueField(.mouseEventClickState, value: 2)
    secondUp.setIntegerValueField(.mouseEventClickState, value: 2)
    secondDown.post(tap: .cghidEventTap); secondUp.post(tap: .cghidEventTap)
    return ["x":point.x, "y":point.y]
}
do {
    let args = Array(CommandLine.arguments.dropFirst())
    var values: [String: String] = [:]
    var index = 0
    while index < args.count {
        try require(index+1 < args.count && args[index].hasPrefix("--") && values[args[index]] == nil,
                    "Use --pid PLAYCOVER_PID --proof-dir FRESH_DIRECTORY --exact COMPLETE_GAME_CAPTION [--window-id ID]")
        values[args[index]] = args[index+1]; index += 2
    }
    try require(Set(values.keys).isSubset(of: ["--pid", "--window-id", "--proof-dir", "--exact"]), "Unknown option")
    guard let pid = Int32(values["--pid"] ?? ""), pid > 0, let directory = values["--proof-dir"],
          let caption = values["--exact"] else { throw QAError.invalid("Exact PlayCover PID, fresh proof directory and complete game caption are required") }
    try require(!caption.isEmpty && caption.utf16.count <= 160 && !caption.contains("…") && !caption.contains("...")
                && !caption.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
                "Require a complete bounded game caption; refuse truncated captions")
    let proof = URL(fileURLWithPath: directory, isDirectory: true)
    try require(!FileManager.default.fileExists(atPath: proof.path), "Proof directory already exists")
    try FileManager.default.createDirectory(at: proof, withIntermediateDirectories: true)
    let requested = values["--window-id"].flatMap(UInt32.init)
    try require(values["--window-id"] == nil || requested != nil, "Invalid window ID")
    let initial = try observe(pid, requested, proof, "initial")
    let first = try unique(initial, exact: caption, regex: nil)
    let fresh = try observe(pid, initial.window.id, proof, "pre-double-click")
    let second = try unique(fresh, exact: caption, regex: nil)
    try require(normalized(first.text) == normalized(second.text)
                && abs(first.x-second.x) < 0.02 && abs(first.y-second.y) < 0.02
                && abs(first.width-second.width) < 0.02 && abs(first.height-second.height) < 0.02,
                "Game caption changed between fresh captures; no events were sent")
    let point = try doubleClick(fresh, second)
    let result: [String: Any] = [
        "status": "REAL_OS_DOUBLE_CLICK_SENT_TO_UNIQUE_PLAYCOVER_LIBRARY_CAPTION",
        "action": "double-click-library-game", "pid": pid, "bundleIdentifier": "io.playcover.PlayCover",
        "windowID": fresh.window.id, "caption": second.text, "osMouseDoubleClick": point,
        "clickCounts": [1,2], "intervalMilliseconds": 80,
        "qualification": "Only OS input delivery is recorded. Observe the new game PID, UI and unchanged verified game bundle separately."
    ]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: proof.appendingPathComponent("result.json"), options: .withoutOverwriting)
    FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fputs("VisionPlayCoverLaunch failed: \(error)\n", stderr)
    exit(1)
}
