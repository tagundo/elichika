// External optional diagnostic. It cannot establish game/MV or GUI-install PASS.
import Foundation
import AppKit
guard CommandLine.arguments.count == 4 else { exit(2) }
let alias=URL(fileURLWithPath:CommandLine.arguments[1],isDirectory:true)
let identifier=CommandLine.arguments[2]
let output=URL(fileURLWithPath:CommandLine.arguments[3])
guard !FileManager.default.fileExists(atPath:output.path),
      let info=NSDictionary(contentsOf:alias.appendingPathComponent("Info.plist")),
      info["CFBundleIdentifier"] as? String == identifier,
      let executableName=info["CFBundleExecutable"] as? String,
      !executableName.isEmpty, !executableName.contains("/"), !executableName.contains("\\"),
      NSRunningApplication.runningApplications(withBundleIdentifier:identifier).isEmpty else { exit(2) }
let expectedExecutable=alias.appendingPathComponent(executableName).resolvingSymlinksInPath().standardizedFileURL
guard FileManager.default.isExecutableFile(atPath:expectedExecutable.path) else {exit(2)}
var reply:[String:Any]=["schema":1,"alias":alias.path,"expectedBundleID":identifier,
    "expectedExecutable":expectedExecutable.path,"executableMatches":false,
    "defaultOpenConfiguration":true,"callbackTimeoutSeconds":20,
    "actualPlayCoverGUIInstall":false,"actualGameOrMVPass":false]
var done=false
var launched:NSRunningApplication?
func errorInfo(_ error:NSError,_ depth:Int=0)->[String:Any] {
    var value:[String:Any]=["domain":error.domain,"code":error.code,
        "description":String(error.localizedDescription.prefix(2048)),
        "userInfoKeys":Array(error.userInfo.keys).sorted().prefix(32).map{String($0)}]
    if depth<3,let nested=error.userInfo[NSUnderlyingErrorKey] as? NSError {value["underlying"]=errorInfo(nested,depth+1)}
    return value
}
NSWorkspace.shared.openApplication(at:alias,configuration:NSWorkspace.OpenConfiguration()) { app,error in
    DispatchQueue.main.async {
        if let error=error as NSError? {reply["status"]="PUBLIC_LAUNCH_ERROR";reply["error"]=errorInfo(error)}
        else if let app=app,app.bundleIdentifier==identifier {
            reply["pid"]=app.processIdentifier;reply["terminatedAtCompletion"]=app.isTerminated
            reply["reportedBundleURL"]=app.bundleURL?.path ?? ""
            let actual=app.executableURL?.resolvingSymlinksInPath().standardizedFileURL
            reply["reportedExecutable"]=actual?.path ?? ""
            let matches=actual==expectedExecutable
            reply["executableMatches"]=matches
            // A matching bundle ID can belong to another registered copy.
            // Only our exact returned executable may be observed/terminated.
            if matches {launched=app;reply["status"]="PUBLIC_LAUNCH_COMPLETION"}
            else {reply["status"]="UNEXPECTED_LAUNCH_EXECUTABLE"}
        } else {reply["status"]="UNEXPECTED_COMPLETION_IDENTITY"}
        done=true
    }
}
let deadline=Date().addingTimeInterval(20)
while !done && Date()<deadline {RunLoop.current.run(until:Date().addingTimeInterval(0.05))}
if !done {reply["status"]="PUBLIC_LAUNCH_CALLBACK_TIMEOUT"}
if let app=launched {
    let observed=Date().addingTimeInterval(3)
    while Date()<observed && !app.isTerminated {RunLoop.current.run(until:Date().addingTimeInterval(0.05))}
    reply["terminatedAfterThreeSeconds"]=app.isTerminated
    if !app.isTerminated {
        reply["normalTerminateRequested"]=app.terminate()
        let end=Date().addingTimeInterval(3)
        while !app.isTerminated && Date()<end {RunLoop.current.run(until:Date().addingTimeInterval(0.05))}
        if !app.isTerminated {
            reply["exactReturnedPIDForceTerminateRequested"]=app.forceTerminate()
            let forcedEnd=Date().addingTimeInterval(3)
            while !app.isTerminated && Date()<forcedEnd {RunLoop.current.run(until:Date().addingTimeInterval(0.05))}
        }
    }
    reply["launchedProcessTerminated"]=app.isTerminated
}
let raw=try JSONSerialization.data(withJSONObject:reply,options:[.prettyPrinted,.sortedKeys])
guard raw.count<=16384 else {exit(2)}
try raw.write(to:output)
print(reply["status"] as? String ?? "UNKNOWN")
