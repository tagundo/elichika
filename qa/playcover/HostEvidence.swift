import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

guard [2, 3].contains(CommandLine.arguments.count) else { exit(2) }
let wanted = CommandLine.arguments[1]
let apps = NSWorkspace.shared.runningApplications.filter { $0.bundleIdentifier == wanted }
var activation: [String: Any] = [:]
var activationFailed = false
if CommandLine.arguments.count == 3 {
    guard CommandLine.arguments[2] == "--activate", apps.count == 1 else { exit(2) }
    let accepted = apps[0].activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
    let began = ProcessInfo.processInfo.systemUptime
    var stableReads = 0
    while ProcessInfo.processInfo.systemUptime-began < 5 && stableReads < 3 {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == apps[0].processIdentifier
            && apps[0].isActive && !apps[0].isTerminated {
            stableReads += 1
        } else {
            stableReads = 0
        }
    }
    activationFailed = stableReads < 3
    activation = ["requested": true, "request_accepted": accepted,
        "exact_pid_active_and_frontmost_stable": !activationFailed,
        "stable_reads": stableReads,
        "elapsed_seconds": ProcessInfo.processInfo.systemUptime-began]
}
let records: [[String: Any]] = apps.map { app in
    let windows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []).filter {
        ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier
    }.map { item -> [String: Any] in
        var output: [String: Any] = [:]
        for key in [kCGWindowNumber, kCGWindowBounds, kCGWindowLayer, kCGWindowName] {
            if let value = item[key as String] { output[key as String] = value }
        }
        return output
    }
    return ["pid": app.processIdentifier, "bundle_identifier": app.bundleIdentifier ?? "", "bundle_path": app.bundleURL?.path ?? "", "active": app.isActive, "windows": windows]
}
let screens: [[String: Any]] = NSScreen.screens.map { screen in
    ["frame_cocoa_bottom_left": [screen.frame.origin.x, screen.frame.origin.y, screen.frame.width, screen.frame.height],
     "visible_frame_cocoa_bottom_left": [screen.visibleFrame.origin.x, screen.visibleFrame.origin.y, screen.visibleFrame.width, screen.visibleFrame.height],
     "backing_scale_factor": screen.backingScaleFactor]
}
let output: [String: Any] = ["AX_trusted": AXIsProcessTrusted(), "screen_capture_authorized": CGPreflightScreenCaptureAccess(), "applications": records,
    "frontmost_pid": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0,
    "activation": activation, "screens": screens]
let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
if activationFailed { exit(3) }
