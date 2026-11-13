// External QA helper. Never include this file or its binary in a client IPA.
import Foundation
import AppKit
import ApplicationServices
import CoreGraphics

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}
let args = CommandLine.arguments
guard args.count >= 4, let pid = pid_t(args[2]) else {
    fail("Usage: PlayCoverAX dump|press|set-text PID PROOF_DIRECTORY [LABEL|FIELD_INDEX] [VALUE]")
}
let command = args[1]
let proof = URL(fileURLWithPath: args[3], isDirectory: true)
try FileManager.default.createDirectory(at: proof, withIntermediateDirectories: true)
guard AXIsProcessTrusted() else {
    fail("Accessibility access is absent. No permission or TCC settings were changed.")
}
guard let app = NSRunningApplication(processIdentifier: pid) else { fail("Target PID is not a running application") }
let application = AXUIElementCreateApplication(pid)
AXUIElementSetMessagingTimeout(application, 5)

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var result: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success else { return nil }
    return result
}
func text(_ element: AXUIElement, _ name: String) -> String? {
    return attribute(element, name) as? String
}
func children(_ element: AXUIElement) -> [AXUIElement] {
    return attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}
var elements: [AXUIElement] = []
var records: [[String: Any]] = []
func visit(_ element: AXUIElement, _ depth: Int) {
    guard depth < 24, records.count < 2000 else { return }
    let index = elements.count
    elements.append(element)
    var item: [String: Any] = ["index": index, "depth": depth]
    for key in [kAXRoleAttribute, kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute, kAXValueAttribute, kAXPlaceholderValueAttribute, kAXIdentifierAttribute] {
        if let value = text(element, key) { item[key] = value }
    }
    if let enabled = attribute(element, kAXEnabledAttribute) as? Bool { item["enabled"] = enabled }
    if let raw = attribute(element, kAXPositionAttribute), CFGetTypeID(raw) == AXValueGetTypeID() {
        var value = CGPoint.zero
        if AXValueGetValue(unsafeBitCast(raw, to: AXValue.self), .cgPoint, &value) { item["position"] = [value.x, value.y] }
    }
    if let raw = attribute(element, kAXSizeAttribute), CFGetTypeID(raw) == AXValueGetTypeID() {
        var value = CGSize.zero
        if AXValueGetValue(unsafeBitCast(raw, to: AXValue.self), .cgSize, &value) { item["size"] = [value.width, value.height] }
    }
    records.append(item)
    for child in children(element) { visit(child, depth + 1) }
}
visit(application, 0)

var action: [String: Any] = ["command": command, "performed": false]
if command == "press" {
    guard args.count == 5 else { fail("press requires an exact label") }
    let label = args[4]
    let matches = records.filter { item in
        item[kAXRoleAttribute] as? String == kAXButtonRole &&
        item["enabled"] as? Bool != false &&
        [kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute, kAXIdentifierAttribute].contains { item[$0] as? String == label }
    }
    guard matches.count == 1, let index = matches.first?["index"] as? Int else {
        fail("Expected one enabled button with the exact label; found \(matches.count)")
    }
    let result = AXUIElementPerformAction(elements[index], kAXPressAction as CFString)
    action = ["command": command, "label": label, "element_index": index, "AX_result": result.rawValue, "performed": result == .success]
} else if command == "set-text" {
    guard args.count == 6, let fieldIndex = Int(args[4]), fieldIndex >= 0 else { fail("set-text requires FIELD_INDEX VALUE") }
    let fields = records.filter { $0[kAXRoleAttribute] as? String == kAXTextFieldRole }
    guard fields.count == 2, fieldIndex < fields.count, let index = fields[fieldIndex]["index"] as? Int else {
        fail("Expected exactly two camera text fields in current AX tree")
    }
    // Only bounded finite camera numbers can be entered by this helper.
    guard let value = Double(args[5]), value.isFinite, value >= 0.5, value <= 2 else { fail("Camera value must be 0.5...2.0") }
    let result = AXUIElementSetAttributeValue(elements[index], kAXValueAttribute as CFString, args[5] as CFString)
    action = ["command": command, "field_index": fieldIndex, "value": value, "AX_result": result.rawValue, "performed": result == .success]
} else if command != "dump" { fail("Unknown action") }

let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? [])
    .filter { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid }
    .map { item -> [String: Any] in
        var value: [String: Any] = [:]
        for key in [kCGWindowNumber, kCGWindowBounds, kCGWindowLayer, kCGWindowName] {
            if let found = item[key as String] { value[key as String] = found }
        }
        return value
    }
let result: [String: Any] = [
    "pid": pid, "application": app.localizedName ?? "", "bundle_identifier": app.bundleIdentifier ?? "",
    "AX_trusted": true, "action": action, "elements": records, "windows": windows,
    "qualification": "AX input success records only the API result. Verify the resulting UI state and screenshot separately."
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
try data.write(to: proof.appendingPathComponent("accessibility.json"), options: .atomic)
FileHandle.standardOutput.write(("Wrote \(proof.path)/accessibility.json\n").data(using: .utf8)!)
if command != "dump", action["performed"] as? Bool != true { exit(2) }
