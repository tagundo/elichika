// External launch comparison only. Never include this helper in a game IPA.
// Mirrors PlayCover a7b1693d4fa4310367990cd35d4ebafb20e5c965
// PlayCover/Model/PlayApp.swift runAppExec(): unmodified OpenConfiguration.
import Foundation
import AppKit

let arguments = CommandLine.arguments
guard arguments.count == 4 else {
    FileHandle.standardError.write(Data("Usage: PlayCoverLaunch VERIFIED_ALIAS_APP EXPECTED_BUNDLE_ID PROOF_JSON\n".utf8))
    exit(2)
}
let alias = URL(fileURLWithPath: arguments[1], isDirectory: true).standardizedFileURL
let bundleID = arguments[2]
let proof = URL(fileURLWithPath: arguments[3]).standardizedFileURL
var observation: [String: Any] = [
    "schema": 1,
    "method": "NSWorkspace.shared.openApplication",
    "pinnedPlayCoverSource": "a7b1693d4fa4310367990cd35d4ebafb20e5c965",
    "unmodifiedOpenConfiguration": true,
    "customArguments": false,
    "customEnvironment": false,
    "stdoutStderrRedirection": false,
    "alias": alias.path,
    "expectedBundleIdentifier": bundleID,
    "startedUTC": ISO8601DateFormatter().string(from: Date()),
    "qualification": "Public OS launch request and completion identity only; verify child lifetime/UI/gameplay separately."
]

func finish(_ status: String, code: Int32) -> Never {
    observation["status"] = status
    observation["completedUTC"] = ISO8601DateFormatter().string(from: Date())
    do {
        guard !FileManager.default.fileExists(atPath: proof.path) else {
            throw NSError(domain: "PlayCoverLaunch.ExistingProof", code: 1)
        }
        try FileManager.default.createDirectory(at: proof.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: observation, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: proof, options: .atomic)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        FileHandle.standardError.write(Data("Could not write fresh bounded launch evidence\n".utf8))
        exit(3)
    }
    exit(code)
}

guard alias.pathExtension == "app", bundleID.range(of: #"^[A-Za-z0-9][A-Za-z0-9.-]{2,200}$"#, options: .regularExpression) != nil,
      let info = NSDictionary(contentsOf: alias.appendingPathComponent("Info.plist")),
      info["CFBundleIdentifier"] as? String == bundleID,
      let executable = info["CFBundleExecutable"] as? String,
      !executable.isEmpty, !executable.contains("/"), !executable.contains("\\"),
      FileManager.default.fileExists(atPath: alias.appendingPathComponent(executable).path) else {
    finish("FAIL_VERIFIED_ALIAS_IDENTITY", code: 2)
}
guard NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).isEmpty else {
    finish("FAIL_PREEXISTING_GAME_PROCESS", code: 2)
}

let metalKeys = [
    "METAL_DEVICE_WRAPPER_TYPE", "METAL_DEBUG_LAYER", "MTL_DEBUG_LAYER", "METAL_API_VALIDATION",
    "METAL_SHADER_VALIDATION", "METAL_SHADER_VALIDATION_OPTIONS", "METAL_CAPTURE_ENABLED",
    "METAL_CAPTURE_OUTPUT_FILE", "METAL_CAPTURE_TYPE", "METAL_FORCE_LAZY_COMPILATION",
    "METAL_FRAME_CAPTURE_ENABLED", "METAL_ERROR_MODE", "MTLCaptureEnabled"
]
let inheritedKeys = ProcessInfo.processInfo.environment.keys
var cleared: [String] = []
for key in inheritedKeys where key.hasPrefix("DYLD_") {
    unsetenv(key)
    cleared.append(key)
}
for key in metalKeys {
    unsetenv(key)
    cleared.append(key)
}
observation["clearedEnvironmentKeyNames"] = Array(Set(cleared)).sorted()
let configuration = NSWorkspace.OpenConfiguration()
var completed = false
var completionCode: Int32 = 1
var completionStatus = "FAIL_NO_COMPLETION"
NSWorkspace.shared.openApplication(at: alias, configuration: configuration) { running, error in
    // NSWorkspace's completion executes on a concurrent queue. Keep all report
    // state on main while its public run loop services the launch callback.
    DispatchQueue.main.async {
        if let error = error as NSError? {
            observation["errorDomain"] = error.domain
            observation["errorCode"] = error.code
            if let underlying = error.userInfo[NSUnderlyingErrorKey] as? NSError {
                observation["underlyingErrorDomain"] = underlying.domain
                observation["underlyingErrorCode"] = underlying.code
            }
            completionStatus = "FAIL_PUBLIC_LAUNCH_ERROR"
        } else if let running = running, running.bundleIdentifier == bundleID {
            observation["completionPID"] = running.processIdentifier
            observation["completionBundleIdentifier"] = running.bundleIdentifier
            observation["completionAlreadyTerminated"] = running.isTerminated
            completionStatus = "PUBLIC_LAUNCH_COMPLETION_OBSERVED"
            completionCode = 0
        } else {
            completionStatus = "FAIL_COMPLETION_APPLICATION_IDENTITY"
        }
        completed = true
    }
}
let deadline = Date().addingTimeInterval(25)
while !completed && Date() < deadline {
    RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
}
guard completed else { finish("FAIL_PUBLIC_LAUNCH_COMPLETION_TIMEOUT", code: 1) }
finish(completionStatus, code: completionCode)
