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
func rectangle(_ element: AXUIElement) -> CGRect? {
    guard let p = attribute(element,kAXPositionAttribute), CFGetTypeID(p) == AXValueGetTypeID(),
          let s = attribute(element,kAXSizeAttribute), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero; var size = CGSize.zero
    guard AXValueGetValue(unsafeBitCast(p,to:AXValue.self),.cgPoint,&point),
          AXValueGetValue(unsafeBitCast(s,to:AXValue.self),.cgSize,&size),
          point.x.isFinite,point.y.isFinite,size.width.isFinite,size.height.isFinite,
          size.width>0,size.height>0 else { return nil }
    return CGRect(origin:point,size:size)
}
func numbers(_ rect: CGRect) -> [Double] {
    [Double(rect.origin.x),Double(rect.origin.y),Double(rect.width),Double(rect.height)]
}
func requireForeground() {
    guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid && app.isActive && !app.isTerminated else {
        fail("The exact observed target must remain active and foreground; no window/alert action was sent")
    }
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
if command == "dismiss-owned-crash" {
    guard args.count == 5, ["global","allstars"].contains(args[4]),
          app.bundleIdentifier == "com.apple.UserNotificationCenter" else { fail("Only an exact task game crash alert in UserNotificationCenter may be dismissed") }
    requireForeground()
    let caption = args[4]+" quit unexpectedly."
    let messages = records.filter { $0[kAXRoleAttribute] as? String == kAXStaticTextRole && $0[kAXValueAttribute] as? String == caption }
    let alerts = records.filter { $0[kAXRoleAttribute] as? String == kAXWindowRole && $0[kAXDescriptionAttribute] as? String == "alert" }
    let ignores = records.filter { $0[kAXRoleAttribute] as? String == kAXButtonRole && $0[kAXTitleAttribute] as? String == "Ignore" && $0["enabled"] as? Bool == true }
    guard messages.count == 1, alerts.count == 1, ignores.count == 1,
          let index = ignores[0]["index"] as? Int, let rect = rectangle(elements[index]),
          CGDisplayBounds(CGMainDisplayID()).contains(CGPoint(x:rect.midX,y:rect.midY)) else {
        fail("Require the unique exact task crash message, one alert, and one enabled visible Ignore button")
    }
    requireForeground()
    let result = AXUIElementPerformAction(elements[index],kAXPressAction as CFString)
    action = ["command":command,"caption":caption,"label":"Ignore","element_index":index,
        "AX_result":result.rawValue,"performed":result == .success,
        "qualification":"Normal task crash alert cleanup only. The original startup failure remains a failure."]
} else if command == "fit-game-window" {
    guard args.count == 4, ["com.klab.lovelive.allstars.global","com.klab.lovelive.allstars"].contains(app.bundleIdentifier ?? "") else {
        fail("Only an actual task game window may be fit to the observed display")
    }
    requireForeground()
    let windows = attribute(application,kAXWindowsAttribute) as? [AXUIElement] ?? []
    let screens = NSScreen.screens
    guard windows.count == 1, screens.count == 1, let before = rectangle(windows[0]) else {
        fail("Window fit requires exactly one real game AXWindow and one observed QA screen")
    }
    let display = CGDisplayBounds(CGMainDisplayID())
    let cocoa = screens[0].visibleFrame
    guard screens[0].frame.origin == .zero && display.origin == .zero
        && abs(screens[0].frame.width-display.width)<0.5 && abs(screens[0].frame.height-display.height)<0.5 else {
        fail("Observed screen and Quartz coordinates do not match; no guessed resize was sent")
    }
    let visible = CGRect(x:cocoa.origin.x,y:display.height-cocoa.maxY,width:cocoa.width,height:cocoa.height)
    let usable = visible.insetBy(dx:8,dy:8)
    requireForeground()
    if usable.contains(before) {
        action = ["command":command,"performed":false,"already_visible":true,"physical_display_visible":true,
            "before":numbers(before),"visible_frame_quartz":numbers(visible)]
    } else {
        var sizeSettable = DarwinBoolean(false); var positionSettable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(windows[0],kAXSizeAttribute as CFString,&sizeSettable) == .success && sizeSettable.boolValue,
              AXUIElementIsAttributeSettable(windows[0],kAXPositionAttribute as CFString,&positionSettable) == .success && positionSettable.boolValue else {
            fail("Game AX size/position are not settable; no hidden game callback or preference change was used")
        }
        let factor = min(1,min(usable.width/before.width,usable.height/before.height))
        var size = CGSize(width:floor(before.width*factor),height:floor(before.height*factor))
        var point = usable.origin
        guard size.width>=200 && size.height>=150,
              let sizeValue = AXValueCreate(.cgSize,&size), let positionValue = AXValueCreate(.cgPoint,&point) else {
            fail("Observed display cannot fit a usable game window")
        }
        requireForeground()
        let resized = AXUIElementSetAttributeValue(windows[0],kAXSizeAttribute as CFString,sizeValue)
        let moved = AXUIElementSetAttributeValue(windows[0],kAXPositionAttribute as CFString,positionValue)
        RunLoop.current.run(until:Date().addingTimeInterval(0.5))
        requireForeground()
        guard resized == .success, moved == .success, let after = rectangle(windows[0]), visible.contains(after) else {
            fail("Ordinary AX window resize did not leave the observed game window inside the actual visible display")
        }
        action = ["command":command,"performed":true,"physical_display_visible":true,
            "AX_size_settable":true,"AX_position_settable":true,"before":numbers(before),"after":numbers(after),
            "visible_frame_quartz":numbers(visible),"qualification":"Ordinary OS window geometry setup only; no game state or feature PASS inferred."]
    }
} else if command == "press" {
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
if command != "dump", action["performed"] as? Bool != true && action["already_visible"] as? Bool != true { exit(2) }
