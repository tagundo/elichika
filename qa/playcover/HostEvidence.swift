import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

guard CommandLine.arguments.count == 2 else { exit(2) }
let wanted = CommandLine.arguments[1]
let apps = NSWorkspace.shared.runningApplications.filter { $0.bundleIdentifier == wanted }
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
