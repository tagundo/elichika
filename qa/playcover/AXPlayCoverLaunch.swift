// External QA: native AX caption selects a PlayCover library tile. Never ship in an IPA.
// OCR is incidental screenshot evidence only; it never authorizes this native AX action.
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
    try require(app.bundleIdentifier == "io.playcover.PlayCover", "Only the exact foreground PlayCover application may receive this native AX library action")
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

struct NativeCaption: Codable {
    let caption: String
    let role: String
    let enabled: Bool
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    let queriedUptime: Double
    let visitedElements: Int
}
func axAttribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}
func nativeCaption(_ pid: Int32, _ caption: String) throws -> NativeCaption {
    try foreground(pid)
    let began = ProcessInfo.processInfo.systemUptime
    let application = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(application, 1)
    var matches: [NativeCaption] = []
    var visited = 0
    var limited = false
    func visit(_ element: AXUIElement, _ depth: Int) {
        guard depth < 24, visited < 2000 else { limited = true; return }
        visited += 1
        if axAttribute(element, kAXRoleAttribute) as? String == kAXStaticTextRole,
           axAttribute(element, kAXEnabledAttribute) as? Bool == true {
            let strings = [kAXValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute].compactMap { axAttribute(element, $0) as? String }
            if strings.contains(where: { normalized($0) == normalized(caption) }),
               let p = axAttribute(element, kAXPositionAttribute), CFGetTypeID(p) == AXValueGetTypeID(),
               let z = axAttribute(element, kAXSizeAttribute), CFGetTypeID(z) == AXValueGetTypeID() {
                var point = CGPoint.zero
                var size = CGSize.zero
                if AXValueGetValue(unsafeBitCast(p, to: AXValue.self), .cgPoint, &point),
                   AXValueGetValue(unsafeBitCast(z, to: AXValue.self), .cgSize, &size),
                   point.x.isFinite, point.y.isFinite, size.width > 0, size.height > 0 {
                    matches.append(NativeCaption(caption: caption, role: kAXStaticTextRole, enabled: true,
                        x: Double(point.x), y: Double(point.y), width: Double(size.width), height: Double(size.height),
                        queriedUptime: began, visitedElements: visited))
                }
            }
        }
        for child in axAttribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? [] { visit(child, depth+1) }
    }
    visit(application, 0)
    try foreground(pid)
    try require(ProcessInfo.processInfo.systemUptime-began < 5, "Native AX enumeration is stale; no event was sent")
    try require(!limited && visited < 2000, "Native AX enumeration limit reached; uniqueness is not established")
    try require(matches.count == 1, "Require exactly one enabled positive-rectangle native AXStaticText with the complete caption; found \(matches.count)")
    return matches[0]
}
func nativeDoubleClick(_ image: Observation, _ target: NativeCaption) throws -> [String: Double] {
    try foreground(image.window.pid)
    let current = try window(image.window.pid, image.window.id)
    let now = ProcessInfo.processInfo.systemUptime
    try require(now-image.capturedUptime < 5 && now-target.queriedUptime < 5,
                "Native AX/screenshot proof is stale; no event was sent")
    try require(abs(current.x-image.window.x)<0.5 && abs(current.y-image.window.y)<0.5
                && abs(current.width-image.window.width)<0.5 && abs(current.height-image.window.height)<0.5,
                "PlayCover window changed after native AX observation")
    let point = CGPoint(x: target.x+target.width/2, y: target.y+target.height/2)
    try require(point.x.isFinite && point.y.isFinite && target.width>0 && target.height>0
                && point.x>current.x && point.x<current.x+current.width
                && point.y>current.y && point.y<current.y+current.height,
                "Native AX caption center lies outside the verified visible PlayCover window")
    let source = CGEventSource(stateID: .combinedSessionState)
    guard let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left),
          let firstDown = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
          let firstUp = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
        throw QAError.invalid("First OS event creation failed")
    }
    firstDown.setIntegerValueField(.mouseEventClickState, value: 1)
    firstUp.setIntegerValueField(.mouseEventClickState, value: 1)
    move.post(tap: .cghidEventTap)
    firstDown.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.1)
    firstUp.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.08)
    try foreground(image.window.pid)
    let secondWindow = try window(image.window.pid, image.window.id)
    try require(ProcessInfo.processInfo.systemUptime-target.queriedUptime<5
                && abs(secondWindow.x-current.x)<0.5 && abs(secondWindow.y-current.y)<0.5
                && abs(secondWindow.width-current.width)<0.5 && abs(secondWindow.height-current.height)<0.5,
                "PlayCover changed before second native-AX-derived click; no second event was sent")
    guard let secondDown = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
          let secondUp = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else {
        throw QAError.invalid("Second OS event creation failed")
    }
    secondDown.setIntegerValueField(.mouseEventClickState, value: 2)
    secondUp.setIntegerValueField(.mouseEventClickState, value: 2)
    secondDown.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.1)
    secondUp.post(tap: .cghidEventTap)
    return ["x": point.x, "y": point.y]
}
do {
    let args = Array(CommandLine.arguments.dropFirst())
    var values: [String:String] = [:]
    var i = 0
    while i<args.count {
        try require(i+1<args.count && args[i].hasPrefix("--") && values[args[i]]==nil,
            "Use --pid PLAYCOVER_PID --proof-dir FRESH_DIRECTORY --exact COMPLETE_GAME_CAPTION [--window-id ID]")
        values[args[i]]=args[i+1]; i+=2
    }
    try require(Set(values.keys).isSubset(of:["--pid","--proof-dir","--exact","--window-id"]), "Unknown option")
    guard let pid=Int32(values["--pid"] ?? ""), pid>0, let folder=values["--proof-dir"], let caption=values["--exact"] else {
        throw QAError.invalid("Exact foreground PlayCover PID, fresh directory and native game caption required")
    }
    try require(!caption.isEmpty && caption.utf16.count<=160 && !caption.contains("…") && !caption.contains("...")
        && !caption.unicodeScalars.contains(where:{CharacterSet.controlCharacters.contains($0)}), "Refuse incomplete or unbounded game caption")
    let proof=URL(fileURLWithPath:folder,isDirectory:true)
    try require(!FileManager.default.fileExists(atPath:proof.path),"Proof directory already exists")
    try FileManager.default.createDirectory(at:proof,withIntermediateDirectories:true)
    let requested=values["--window-id"].flatMap(UInt32.init)
    try require(values["--window-id"]==nil || requested != nil,"Invalid window ID")
    let firstImage=try observe(pid,requested,proof,"initial")
    let first=try nativeCaption(pid,caption)
    let freshImage=try observe(pid,firstImage.window.id,proof,"pre-double-click")
    let second=try nativeCaption(pid,caption)
    try require(first.caption==second.caption && abs(first.x-second.x)<0.5 && abs(first.y-second.y)<0.5
        && abs(first.width-second.width)<0.5 && abs(first.height-second.height)<0.5,
        "Native AX caption rectangle changed between two fresh reads; no input sent")
    let encoder=JSONEncoder();encoder.outputFormatting=[.prettyPrinted,.sortedKeys]
    try encoder.encode(first).write(to:proof.appendingPathComponent("native-caption-initial.json"),options:.withoutOverwriting)
    try encoder.encode(second).write(to:proof.appendingPathComponent("native-caption-pre-click.json"),options:.withoutOverwriting)
    let point=try nativeDoubleClick(freshImage,second)
    let result:[String:Any]=["status":"REAL_OS_DOUBLE_CLICK_SENT_TO_UNIQUE_NATIVE_AX_PLAYCOVER_CAPTION",
        "selectionMethod":"native AXStaticText complete caption", "OCRConfidenceApplicable":false,
        "incidentalOCRNeverAuthorizesInput":true,"pid":pid,"bundleIdentifier":"io.playcover.PlayCover",
        "windowID":freshImage.window.id,"caption":caption,"osMouseDoubleClick":point,"clickCounts":[1,2],"mouseHoldSeconds":0.1,
        "qualification":"Only real OS input delivery recorded. Separately observe new game PID, UI, crash reason and strict postlaunch bundle verification."]
    let data=try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys])
    try data.write(to:proof.appendingPathComponent("result.json"),options:.withoutOverwriting)
    FileHandle.standardOutput.write(data);FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fputs("AXPlayCoverLaunch failed: \(error)\n",stderr);exit(1)
}
