// External, diagnostic-only OS input. Never ship or inject this helper into Elichika.
import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit
import Foundation

enum DiagnosticError: Error, CustomStringConvertible {
    case failed(String)
    var description: String { if case .failed(let text) = self { return text }; return "Diagnostic error" }
}
func require(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw DiagnosticError.failed(message) }
}
func normalized(_ value: String) -> String { value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ") }
func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success else { return nil }
    return result
}
func rectangle(_ element: AXUIElement) -> CGRect? {
    guard let p = attribute(element, kAXPositionAttribute), CFGetTypeID(p) == AXValueGetTypeID(),
          let s = attribute(element, kAXSizeAttribute), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero; var size = CGSize.zero
    guard AXValueGetValue(unsafeBitCast(p, to: AXValue.self), .cgPoint, &point),
          AXValueGetValue(unsafeBitCast(s, to: AXValue.self), .cgSize, &size),
          point.x.isFinite, point.y.isFinite, size.width.isFinite, size.height.isFinite,
          size.width > 0, size.height > 0 else { return nil }
    return CGRect(origin: point, size: size)
}
func rectJSON(_ rect: CGRect) -> [String: Double] {
    ["x": Double(rect.minX), "y": Double(rect.minY), "width": Double(rect.width), "height": Double(rect.height)]
}
func write(_ value: Any, _ path: URL) throws {
    try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]).write(to: path, options: .withoutOverwriting)
}
func pump(_ seconds: Double) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }

struct Node {
    let element: AXUIElement
    let index: Int
    let role: String
    let identifier: String
    let labels: [String]
    let value: String
    let enabled: Bool
    let focused: Bool
    let web: Bool
    let nativeSheet: Bool
    let rect: CGRect?
    var json: [String: Any] {
        var result: [String: Any] = ["index": index, "role": role, "identifier": identifier,
            "labels": labels, "value": value, "enabled": enabled, "focused": focused,
            "withinWebArea": web, "withinNativeSheet": nativeSheet]
        if let rect { result["rect"] = rectJSON(rect) }; return result
    }
}

final class Diagnostic {
    let appURL: URL
    let root: URL
    let proof: URL
    var app: NSRunningApplication?
    var stage = "preflight"
    var sequence = 0
    var actions: [[String: Any]] = []
    var dialogs: [[String: Any]] = []
    var cases: [[String: Any]] = []
    var lastCaptureUptime: Double?
    var lastCaptureWindow: (UInt32, CGRect)?
    let identifier = "com.tagundo.elichika.macos"
    init(_ app: URL, _ root: URL, _ proof: URL) { self.appURL = app; self.root = root; self.proof = proof }
    func foreground() throws -> pid_t {
        try require(AXIsProcessTrusted(), "Accessibility is unavailable; no TCC or permission change was requested")
        try require(CGPreflightScreenCaptureAccess(), "Screen capture is unavailable; no permission change was requested")
        guard let app else { throw DiagnosticError.failed("No task-owned application") }
        try require(!app.isTerminated && app.bundleIdentifier == identifier && app.bundleURL?.standardizedFileURL == appURL.standardizedFileURL,
                    "Exact unmodified task app is not running")
        try require(app.isActive && NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier,
                    "Exact task app is not foreground; no input was sent")
        return app.processIdentifier
    }
    func window() throws -> (UInt32, CGRect) {
        let pid = try foreground()
        let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        let windows: [(UInt32, CGRect)] = rows.compactMap { row in
            guard (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid,
                  (row[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
                  ((row[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 0) > 0,
                  let id = (row[kCGWindowNumber as String] as? NSNumber)?.uint32Value,
                  let raw = row[kCGWindowBounds as String] as? [String: Any],
                  let rect = CGRect(dictionaryRepresentation: raw as CFDictionary), rect.width > 50, rect.height > 50 else { return nil }
            return (id, rect)
        }
        guard let target = windows.max(by: { $0.1.width * $0.1.height < $1.1.width * $1.1.height }) else {
            throw DiagnosticError.failed("No visible owned layer-zero app window")
        }
        return target
    }
    func tree() throws -> [Node] {
        let pid = try foreground(); let began = ProcessInfo.processInfo.systemUptime
        let application = AXUIElementCreateApplication(pid); AXUIElementSetMessagingTimeout(application, 0.7)
        var result: [Node] = []; var limited = false
        func visit(_ element: AXUIElement, _ depth: Int, _ web: Bool, _ sheet: Bool) {
            guard depth < 42, result.count < 12000, ProcessInfo.processInfo.systemUptime - began < 8 else { limited = true; return }
            let role = attribute(element, kAXRoleAttribute) as? String ?? ""
            let isWeb = web || role == "AXWebArea"
            let isSheet = sheet || role == kAXSheetRole || role == "AXDialog"
            let names = [kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute].compactMap { attribute(element, $0) as? String }.map(normalized)
            let value = attribute(element, kAXValueAttribute) as? String ?? ""
            result.append(Node(element: element, index: result.count, role: role,
                identifier: attribute(element, kAXIdentifierAttribute) as? String ?? "", labels: names,
                value: value, enabled: attribute(element, kAXEnabledAttribute) as? Bool == true,
                focused: attribute(element, kAXFocusedAttribute) as? Bool == true,
                web: isWeb, nativeSheet: isSheet, rect: rectangle(element)))
            for child in attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? [] { visit(child, depth + 1, isWeb, isSheet) }
        }
        visit(application, 0, false, false); _ = try foreground()
        try require(!limited, "AX enumeration limit reached; uniqueness was not established")
        return result
    }
    func observe(_ label: String) throws -> [Node] {
        sequence += 1; let name = String(format: "%03d-", sequence) + label
        let nodes = try tree(); let target = try window(); let began = ProcessInfo.processInfo.systemUptime
        let image = proof.appendingPathComponent(name + ".png")
        let command = Process(); command.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        command.arguments = ["-x", "-o", "-l", String(target.0), image.path]; try command.run()
        let deadline = Date().addingTimeInterval(12)
        while command.isRunning && Date() < deadline { pump(0.05) }
        if command.isRunning { command.terminate(); throw DiagnosticError.failed("OS capture timed out") }
        try require(command.terminationStatus == 0 && FileManager.default.fileExists(atPath: image.path), "OS capture failed")
        let after = try window()
        try require(after.0 == target.0 && after.1 == target.1, "Owned window moved during capture")
        let data = try Data(contentsOf: image)
        lastCaptureUptime = began; lastCaptureWindow = target
        try write(["capturedUTC": ISO8601DateFormatter().string(from: Date()), "uptime": began,
                   "pid": try foreground(), "bundleIdentifier": identifier, "windowID": target.0,
                   "windowRect": rectJSON(target.1), "screenshot": image.lastPathComponent,
                   "screenshotSHA256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(),
                   "AX": nodes.map { $0.json }], proof.appendingPathComponent(name + ".json"))
        return nodes
    }
    func wait(_ description: String, seconds: Double = 20, condition: ([Node]) -> Bool) throws -> [Node] {
        let deadline = Date().addingTimeInterval(seconds); var last: [Node] = []
        while Date() < deadline { last = try tree(); if condition(last) { return last }; pump(0.25) }
        _ = try? observe("timeout-" + stage)
        throw DiagnosticError.failed("Timed out waiting for " + description)
    }
    func unique(_ nodes: [Node], _ description: String, _ predicate: (Node) -> Bool) throws -> Node {
        let found = nodes.filter(predicate)
        try require(found.count == 1, "Require one " + description + "; found \(found.count)")
        return found[0]
    }
    func caption(_ node: Node, _ text: String) -> Bool { node.labels.contains(normalized(text)) || normalized(node.value) == normalized(text) }
    func click(_ node: Node, _ label: String) throws {
        guard var rect = rectangle(node.element) else { throw DiagnosticError.failed("AX target has no rectangle: " + label) }
        let initialWindow = try window()
        if !initialWindow.1.contains(CGPoint(x: rect.midX, y: rect.midY)) {
            // Visibility only; activation is always a real OS mouse event below.
            let scrolled = AXUIElementPerformAction(node.element, "AXScrollToVisible" as CFString)
            try require(scrolled == .success, "Target is offscreen and cannot be revealed: " + label)
            pump(0.15)
            guard let fresh = rectangle(node.element) else { throw DiagnosticError.failed("Target vanished after native scroll") }; rect = fresh
        }
        _ = try observe("before-" + label)
        let target = try window(); let fresh = rectangle(node.element)
        let freshLabels = [kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute].compactMap { attribute(node.element, $0) as? String }.map(normalized)
        try require(freshLabels == node.labels && attribute(node.element, kAXRoleAttribute) as? String == node.role
                    && (attribute(node.element, kAXIdentifierAttribute) as? String ?? "") == node.identifier
                    && (attribute(node.element, kAXValueAttribute) as? String ?? "") == node.value,
                    "Complete native AX caption/role/identity changed before click: " + label)
        guard let captured = lastCaptureUptime, let capturedWindow = lastCaptureWindow else { throw DiagnosticError.failed("Missing physical preinput screenshot") }
        try require(ProcessInfo.processInfo.systemUptime - captured < 5 && capturedWindow.0 == target.0 && capturedWindow.1 == target.1,
                    "Physical screenshot or owned-window observation is stale; no input was sent")
        try require(fresh == rect && attribute(node.element, kAXEnabledAttribute) as? Bool == true,
                    "Native caption/bounds/enabled state changed before click: " + label)
        let point = CGPoint(x: rect.midX, y: rect.midY)
        try require(target.1.contains(point) && CGDisplayBounds(CGMainDisplayID()).contains(point), "Target center outside owned visible window/display")
        let source = CGEventSource(stateID: .combinedSessionState)
        guard let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left),
              let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left),
              let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left) else { throw DiagnosticError.failed("OS event creation failed") }
        _ = try foreground(); move.post(tap: .cghidEventTap); down.post(tap: .cghidEventTap); pump(0.08); up.post(tap: .cghidEventTap)
        actions.append(["stage": stage, "input": "real OS mouse click", "target": node.json, "rectAtInput": rectJSON(rect),
                        "x": point.x, "y": point.y, "pid": try foreground(), "windowID": target.0])
        pump(0.25)
    }
    func webClick(_ text: String, roles: Set<String> = [kAXButtonRole, kAXDisclosureTriangleRole]) throws {
        let nodes = try wait("web caption " + text) { $0.contains { $0.web && $0.enabled && roles.contains($0.role) && self.caption($0, text) } }
        try click(unique(nodes, "enabled web control " + text) { $0.web && $0.enabled && roles.contains($0.role) && self.caption($0, text) }, text.replacingOccurrences(of: " ", with: "-"))
    }
    func key(_ code: CGKeyCode, _ flags: CGEventFlags = []) throws {
        _ = try foreground(); let source = CGEventSource(stateID: .combinedSessionState)
        guard let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else { throw DiagnosticError.failed("OS key creation failed") }
        down.flags = flags; up.flags = flags; down.post(tap: .cghidEventTap); pump(0.05); up.post(tap: .cghidEventTap); pump(0.2)
        actions.append(["stage": stage, "input": "real OS keyboard", "keyCode": code, "flags": flags.rawValue, "pid": try foreground()])
    }
    func type(_ value: String) throws {
        try require(value.utf16.count < 1024 && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }), "Refuse unbounded/control-character input")
        _ = try foreground(); let units = Array(value.utf16); let source = CGEventSource(stateID: .combinedSessionState)
        var start = 0
        while start < units.count {
            var end = min(start + 16, units.count)
            if end < units.count && (0xd800...0xdbff).contains(Int(units[end - 1])) { end -= 1 }
            let chunk = Array(units[start..<end])
            guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else { throw DiagnosticError.failed("OS text event creation failed") }
            // Plain text must not inherit Command from the preceding Cmd+A.
            down.flags = []; up.flags = []
            down.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk); up.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
            _ = try foreground(); down.post(tap: .cghidEventTap); pump(0.03); up.post(tap: .cghidEventTap); pump(0.03); start = end
        }
        pump(0.2)
        actions.append(["stage": stage, "input": "real OS Unicode keyboard", "ownedText": value, "pid": try foreground()])
    }
    func nativeDialog(_ title: String?, _ action: String) throws {
        let nodes = try wait("native " + action + " panel") { nodes in
            // An Open button is ordinarily disabled before a file is selected.
            // Presence observes the panel; nativePress still requires enabled.
            let hasButton = nodes.contains { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && self.caption($0, action) }
            let hasCancel = nodes.contains { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && $0.enabled && self.caption($0, "Cancel") }
            return hasButton && hasCancel
        }
        let button = try unique(nodes, "native sheet action " + action) { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && self.caption($0, action) }
        let titleObserved = title.map { title in nodes.contains { !$0.web && self.caption($0, title) } }
        dialogs.append(["stage": stage, "expectedTitle": title.map { $0 as Any } ?? NSNull(),
                        "expectedTitleActuallyExposedByAX": titleObserved.map { $0 as Any } ?? NSNull(),
                        "action": action, "actualNativeAction": button.json])
        _ = try observe("native-" + action + "-panel")
    }
    func goTo(_ path: URL) throws {
        try require(path.standardizedFileURL.path.hasPrefix(root.standardizedFileURL.path + "/"), "Native chooser destination must be task-owned")
        try key(5, [.maskCommand, .maskShift]) // ordinary Go to Folder, never clipboard/AppleScript injection
        let nodes = try wait("focused native Go to Folder PathTextField") { $0.contains { !$0.web && $0.nativeSheet && $0.focused && $0.role == kAXTextFieldRole && $0.identifier == "PathTextField" } }
        let field = try unique(nodes, "focused native Go to Folder PathTextField") { !$0.web && $0.nativeSheet && $0.focused && $0.role == kAXTextFieldRole && $0.identifier == "PathTextField" }
        _ = try observe("native-go-to-folder"); try require(field.rect != nil, "Focused native path field has no rectangle")
        try key(0, .maskCommand); try type(path.path)
        _ = try wait("exact owned path text before Go", seconds: 5) { $0.contains { !$0.web && $0.nativeSheet && $0.focused && $0.identifier == "PathTextField" && $0.value == path.path } }
        _ = try observe("native-exact-owned-path-before-Go")
        try key(36)
        _ = try wait("Go to Folder dismissal") { !$0.contains { !$0.web && $0.identifier == "GoToWindow" } }
    }
    func nativePress(_ title: String) throws {
        let nodes = try wait("enabled native panel " + title) { $0.contains { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && $0.enabled && self.caption($0, title) } }
        try click(unique(nodes, "enabled native panel " + title) { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && $0.enabled && self.caption($0, title) }, "native-" + title)
    }
    func openFile(_ caption: String, _ title: String, _ file: URL) throws {
        stage = caption; try webClick("File"); try webClick(caption); try nativeDialog(title, "Open")
        try goTo(file); try nativePress("Open")
        _ = try wait("native panel dismissal after " + caption) { !$0.contains { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && self.caption($0, "Open") } }
        pump(1); _ = try observe("after-" + caption.replacingOccurrences(of: " ", with: "-"))
    }
    func saveFile(_ caption: String, _ file: URL) throws {
        stage = caption; try webClick("File"); try webClick(caption); try nativeDialog(nil, "Save")
        try goTo(file.deletingLastPathComponent())
        let nodes = try wait("native Save As name field") { $0.contains { !$0.web && $0.nativeSheet && $0.role == kAXTextFieldRole && $0.enabled && $0.identifier == "saveAsNameTextField" } }
        let field = try unique(nodes, "native saveAsNameTextField") {
            !$0.web && $0.nativeSheet && $0.role == kAXTextFieldRole && $0.enabled && $0.identifier == "saveAsNameTextField"
        }
        try click(field, "native-save-name"); try key(0, .maskCommand); try type(file.deletingPathExtension().lastPathComponent)
        _ = try wait("owned filename before Save", seconds: 5) { $0.contains { !$0.web && $0.nativeSheet && $0.identifier == "saveAsNameTextField" && ($0.value == file.lastPathComponent || $0.value == file.deletingPathExtension().lastPathComponent) } }
        _ = try observe("native-owned-filename-before-Save"); try nativePress("Save")
        _ = try wait("native save dismissal") { !$0.contains { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && self.caption($0, "Save") } }
        let deadline = Date().addingTimeInterval(15)
        while !FileManager.default.fileExists(atPath: file.path) && Date() < deadline { pump(0.2) }
        try require(FileManager.default.fileExists(atPath: file.path), "Native Save panel dismissed but requested output was not written: " + file.lastPathComponent)
        _ = try observe("after-" + caption.replacingOccurrences(of: " ", with: "-"))
    }
    func openModel(_ prefix: String) throws {
        let previousPID = app?.processIdentifier
        let config = NSWorkspace.OpenConfiguration(); config.activates = true
        var finished = false; var launchError: Error?
        NSWorkspace.shared.open([root.appendingPathComponent("fixtures/" + prefix + "-model.unity")], withApplicationAt: appURL, configuration: config) { running, error in self.app = running; launchError = error; finished = true }
        let deadline = Date().addingTimeInterval(30)
        while !finished && Date() < deadline { pump(0.1) }
        try require(finished && launchError == nil && app != nil, "Ordinary NSWorkspace open-file launch failed: \(String(describing: launchError))")
        if let previousPID { try require(app?.processIdentifier == previousPID, "Second ordinary document open unexpectedly changed owned PID") }
        else {
            guard let owned = app, let launchDate = owned.launchDate else { throw DiagnosticError.failed("Owned app launch identity is unavailable") }
            try require(owned.bundleIdentifier == identifier && owned.bundleURL?.standardizedFileURL == appURL.standardizedFileURL, "Launched app path/identifier mismatch")
            try write(["pid": owned.processIdentifier, "app": appURL.path, "bundleIdentifier": identifier,
                       "launchDate": launchDate.timeIntervalSince1970, "source_commit": "b166b92f6a9e9c575c5cfd292f52b5e60603aa97"],
                      proof.appendingPathComponent("task-owned-app.json"))
        }
        stage = prefix + "-normal-model-open"
        _ = try wait("ordinary document name and viewer", seconds: 150) { nodes in
            nodes.contains { $0.web && ($0.labels + [$0.value]).contains { $0.contains(prefix + "-model.unity") } }
            && nodes.contains { $0.web && self.caption($0, "Texture and color tools") }
        }
        _ = try observe(prefix + "-normal-model-open")
        let current = try tree()
        if !current.contains(where: { $0.web && $0.enabled && [kAXButtonRole, kAXRadioButtonRole, "AXTab"].contains($0.role) && self.caption($0, "Paint") }) {
            try webClick("Texture and color tools")
        }
        let nodes = try wait("enabled texture popup") { $0.contains { $0.web && $0.enabled && $0.role == kAXPopUpButtonRole && ($0.identifier == "viewer-texture-select" || self.caption($0, "Texture") || self.caption($0, "Choose a texture")) } }
        let texture = try unique(nodes, "model texture popup") { $0.web && $0.enabled && $0.role == kAXPopUpButtonRole && ($0.identifier == "viewer-texture-select" || self.caption($0, "Texture") || self.caption($0, "Choose a texture")) }
        try click(texture, prefix + "-model-texture-popup"); try key(115); try key(125); try key(36); pump(1)
        let dimensions = prefix == "small" ? "16×16" : "1024×1024"
        _ = try wait("source model texture of the expected dimensions") { $0.contains { $0.web && $0.role == kAXPopUpButtonRole && $0.value.contains(dimensions) } }
        try webClick("Paint", roles: [kAXButtonRole, kAXRadioButtonRole, "AXTab"])
        _ = try observe(prefix + "-model-texture-paint-ready")
    }
    func phase(_ prefix: String) throws {
        try openModel(prefix)
        let rows: [(String, () throws -> Void)] = [
            ("PNG import", { try self.openFile("Import PNG", "Choose PNG image", self.root.appendingPathComponent("fixtures/" + prefix + "-import.png")) }),
            ("PNG export", { try self.saveFile("Export PNG", self.root.appendingPathComponent("outputs/" + prefix + "-roundtrip.png")) }),
            ("project open", { try self.openFile("Open layer project", "Choose texture project", self.root.appendingPathComponent("fixtures/" + prefix + "-layers.json")) }),
            ("project save", { try self.saveFile("Save layer project", self.root.appendingPathComponent("outputs/" + prefix + "-roundtrip.json")) })]
        for (name, action) in rows {
            do { try action(); cases.append(["phase": prefix, "case": name, "nativeFlow": "DELIVERED_PENDING_DATA_VERIFICATION"]) }
            catch {
                cases.append(["phase": prefix, "case": name, "nativeFlow": "FAILED", "error": String(describing: error), "stage": stage])
                _ = try? observe(prefix + "-case-failure")
                // Cancel only this exact app's single ordinary native panel, if one remains.
                let buttons = (try? tree())?.filter { !$0.web && $0.nativeSheet && $0.role == kAXButtonRole && $0.enabled && self.caption($0, "Cancel") } ?? []
                if buttons.count == 1 { try click(buttons[0], prefix + "-cancel-owned-failed-panel") }
            }
        }
    }
    func run() throws {
        let info = try PropertyListSerialization.propertyList(from: Data(contentsOf: appURL.appendingPathComponent("Contents/Info.plist")), options: [], format: nil) as? [String: Any]
        try require(info?["CFBundleIdentifier"] as? String == identifier, "Wrong application bundle")
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!.appendingPathComponent("Elichika")
        try require(!FileManager.default.fileExists(atPath: support.path), "Refuse existing Elichika support data; this diagnostic requires a fresh ephemeral CI user")
        try require(UserDefaults.standard.persistentDomain(forName: identifier) == nil, "Refuse existing Elichika preferences")
        try require(NSRunningApplication.runningApplications(withBundleIdentifier: identifier).isEmpty, "Refuse an existing Elichika process")
        try phase("small"); try phase("large")
        stage = "two-size-four-native-dialog-flows-observed"
        try require(cases.count == 8 && cases.allSatisfy { $0["nativeFlow"] as? String == "DELIVERED_PENDING_DATA_VERIFICATION" }, "One or more native file flows failed; preserve every individual observation")
    }
    func cleanup() -> [String: Any] {
        guard let app else { return ["ownedAppLaunched": false] }
        let pid = app.processIdentifier
        let requested = app.terminate(); let deadline = Date().addingTimeInterval(30)
        while !app.isTerminated && Date() < deadline { pump(0.1) }
        return ["ownedAppLaunched": true, "pid": pid, "ordinaryTerminateRequested": requested,
                "ordinaryTerminationObserved": app.isTerminated, "forceQuitUsed": false]
    }
}

var diagnostic: Diagnostic?
var outcome: [String: Any] = ["status": "NOT_STARTED", "diagnostic_only": true, "source_commit": "b166b92f6a9e9c575c5cfd292f52b5e60603aa97",
    "validated_release_artifact": false, "normal_C7_failure_waived": false, "product_source_modified": false,
    "no_TCC_or_OS_security_changes": true, "no_smoke_mode_or_JS_input_injection": true]
var exitCode: Int32 = 1
if CommandLine.arguments.dropFirst().first == "--cleanup-owned" {
    var result: [String: Any] = ["status": "REFUSED_OR_UNPROVEN", "ordinaryTerminationObserved": false, "forceQuitUsed": false]
    var destination: URL?
    do {
        let args = Array(CommandLine.arguments.dropFirst()); try require(args.count == 3, "Usage: --cleanup-owned OWNED_APP_RECORD FRESH_RESULT_FILE")
        let recordURL = URL(fileURLWithPath: args[1]); destination = URL(fileURLWithPath: args[2])
        let record = try JSONSerialization.jsonObject(with: Data(contentsOf: recordURL)) as? [String: Any]
        guard let record, let rawPID = record["pid"] as? NSNumber, let appPath = record["app"] as? String,
              let launchDate = record["launchDate"] as? Double else { throw DiagnosticError.failed("Missing original owned-process identity") }
        try require(record["bundleIdentifier"] as? String == "com.tagundo.elichika.macos"
                    && record["source_commit"] as? String == "b166b92f6a9e9c575c5cfd292f52b5e60603aa97", "Invalid task-owned record")
        let pid = rawPID.int32Value; try require(pid > 0, "Invalid owned PID")
        if let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated {
            try require(app.bundleIdentifier == record["bundleIdentifier"] as? String
                        && app.bundleURL?.standardizedFileURL == URL(fileURLWithPath: appPath).standardizedFileURL
                        && abs((app.launchDate?.timeIntervalSince1970 ?? 0) - launchDate) < 0.001,
                        "Owned PID/path/launch identity no longer matches; no termination was sent")
            result["ordinaryTerminateRequested"] = app.terminate(); let deadline = Date().addingTimeInterval(30)
            while !app.isTerminated && Date() < deadline { pump(0.1) }
            result["ordinaryTerminationObserved"] = app.isTerminated
            result["status"] = app.isTerminated ? "OWNED_APP_ORDINARY_TERMINATION_OBSERVED" : "OWNED_APP_ORDINARY_TERMINATION_NOT_COMPLETED"
        } else { result["status"] = "OWNED_APP_ALREADY_ABSENT"; result["ordinaryTerminationObserved"] = true }
        result["pid"] = pid
    } catch { result["error"] = String(describing: error) }
    if let destination { try? write(result, destination) }
    exit(result["ordinaryTerminationObserved"] as? Bool == true ? 0 : 1)
}
do {
    let args = Array(CommandLine.arguments.dropFirst()); try require(args.count == 3, "Usage: NativeFileMenuDiagnostic EXACT_APP OWNED_FIXTURE_ROOT FRESH_PROOF_DIR")
    let app = URL(fileURLWithPath: args[0], isDirectory: true), root = URL(fileURLWithPath: args[1], isDirectory: true), proof = URL(fileURLWithPath: args[2], isDirectory: true)
    try require(!FileManager.default.fileExists(atPath: proof.path), "Proof directory already exists")
    try FileManager.default.createDirectory(at: proof, withIntermediateDirectories: true)
    diagnostic = Diagnostic(app, root, proof); try diagnostic!.run()
    outcome["status"] = "FOUR_REAL_NATIVE_CHOOSER_FLOWS_COMPLETED_PENDING_PIXEL_AND_PROJECT_CHECKS"; exitCode = 0
} catch { outcome["status"] = "ACTUAL_MAC_FILE_MENU_DIAGNOSTIC_FAILED"; outcome["error"] = String(describing: error); _ = try? diagnostic?.observe("failure") }
if let diagnostic {
    outcome["stage"] = diagnostic.stage; outcome["actions"] = diagnostic.actions; outcome["nativeDialogs"] = diagnostic.dialogs; outcome["cases"] = diagnostic.cases
    outcome["cleanup"] = diagnostic.cleanup()
    try? write(outcome, diagnostic.proof.appendingPathComponent("native-dialog-observations.json"))
}
if let data = try? JSONSerialization.data(withJSONObject: outcome, options: [.prettyPrinted, .sortedKeys]) { FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data("\n".utf8)) }
exit(exitCode)
