import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

guard [2, 3].contains(CommandLine.arguments.count) else { exit(2) }
let wanted = CommandLine.arguments[1]
let apps = NSWorkspace.shared.runningApplications.filter { $0.bundleIdentifier == wanted }
if CommandLine.arguments.count == 3 {
    guard CommandLine.arguments[2] == "--activate", apps.count == 1 else { exit(2) }
    apps[0].activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
    RunLoop.current.run(until: Date().addingTimeInterval(0.3))
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
    return ["pid": app.processIdentifier, "bundle_identifier": app.bundleIdentifier ?? "", "bundle_path": app.bundleURL?.path ?? "", "windows": windows]
}
let output: [String: Any] = ["AX_trusted": AXIsProcessTrusted(), "screen_capture_authorized": CGPreflightScreenCaptureAccess(), "applications": records]
let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
