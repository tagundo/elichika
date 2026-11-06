import AppKit
import CryptoKit
import Foundation
import WebKit
import Darwin

/// Runs only when the packaged executable receives an explicit --smoke-test path.
/// It uses the bundled neutral fixture and the same native bridge and editor as users.
@MainActor
final class NativeSmokeTest {
    private let model: AppModel
    private var report: [String: Any] = ["status": "RUNNING", "platform": "macOS", "scope": "Actual bundled runtime, native file bridge, WebKit WebGL and saved Unity geometry"]
    private let startedAt = ProcessInfo.processInfo.systemUptime
    private var stages: [[String: Any]] = []
    init(model: AppModel) { self.model = model }

    func run() async {
        guard let directory = model.smokeDirectory else { return }
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            model.smokeEvent = { [weak self] stage in try? self?.checkpoint(stage) }
            try checkpoint("payload-preparation")
            try await wait("payload preparation", timeout: 420) { self.model.toolsReady }
            guard let ready = model.connection, let process = model.process else { throw NativeError.runtimeUnavailable }
            report["python_pid"] = Int(process.processIdentifier)
            report["ready_ports"] = [ready.controlURL.port!, ready.adminURL.port!, ready.toolsURL.port!]
            try checkpoint("payload-prepared")
            try await checkUnauthorizedControl(ready.controlURL)
            let network = try JSONDecoder().decode(ServerNetworkConfig.self, from: await model.request("/v1/server/config"))
            _ = try await model.request("/v1/server/config", method: "POST", body: ["server_address": network.serverAddress, "cdn_server": network.cdnServer])
            report["native_network_configuration"] = true

            try checkpoint("first-server-start")
            _ = try await model.request("/v1/server/start", method: "POST")
            try await wait("the game server", timeout: 120) {
                await self.model.refresh()
                return self.model.snapshot.serverRunning && self.model.snapshot.server?.httpReady == true
            }
            guard let serverURL = model.goURL(path: "/webui/admin/") else { throw NativeError.invalidResponse }
            try await wait("the game server HTTP response", timeout: 150) {
                do {
                    var request = URLRequest(url: serverURL); request.timeoutInterval = 3
                    let (_, response) = try await URLSession.shared.data(for: request)
                    return (response as? HTTPURLResponse)?.statusCode == 200
                } catch { return false }
            }
            report["server_started"] = true
            report["go_pid"] = model.snapshot.server?.pid
            try checkpoint("first-server-http-ready")
            _ = try await model.request("/v1/server/stop", method: "POST")
            try await wait("the stopped game server", timeout: 15) {
                await self.model.refresh(); return !self.model.snapshot.serverRunning
            }
            report["server_stopped"] = true

            try checkpoint("shared-webui-loading")
            try await wait("the native asset WebView", timeout: 30) { self.model.assetWebView != nil }
            guard let webView = model.assetWebView else { throw NativeError.runtimeUnavailable }
            try await waitJS(webView, "the shared desktop editing UI", timeout: 45, expression:
                "!!window.ElichikaPlatform&&!!window.ModelViewer&&typeof ModelViewer.getAuthoringState==='function'&&!!document.getElementById('viewer-editor-mesh-tab')")
            let helperURL = model.resourceDirectory.appendingPathComponent("qa/viewer_rig_qa.js")
            let helper = try String(contentsOf: helperURL, encoding: .utf8)
            _ = try await js(webView, helper + ";return true;")
            let source = model.resourceDirectory.appendingPathComponent("qa/viewer_persistence.unity")
            let original = try Data(contentsOf: source)
            let originalHash = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
            try require(originalHash == "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1", "The bundled neutral fixture changed.")
            let zipSource = directory.appendingPathComponent("분수 의상.zip")
            let originalZIP = try Data(contentsOf: zipSource)
            let zipHash = SHA256.hash(data: originalZIP).map { String(format: "%02x", $0) }.joined()
            report["fixture_sha256"] = originalHash
            report["source_zip_sha256"] = zipHash
            try checkpoint("native-open-model")
            _ = try await js(webView, "return await ElichikaPlatform.perform('openModel');")
            try await loaded(webView)
            report["native_file_bridge_and_authorization"] = true
            try checkpoint("model-rendered")
            let baseline = try await vertices(webView)
            _ = try await js(webView, "document.getElementById('viewer-adjustments').open=true;document.getElementById('viewer-node-editor').open=true;document.getElementById('viewer-editor-mesh-tab').click();ViewerRigQa.boneInput('LeftUpLeg','scale','X',1.17);ViewerRigQa.boneInput('LeftUpLeg','scale','Y',1.234567);ViewerRigQa.boneInput('LeftUpLeg','scale','Z',1.17);ViewerRigQa.input('viewer-save-method','mesh','change');document.getElementById('viewer-editor-node-tab').click();ViewerRigQa.boneInput('BreastSize','scale','Z',1.17);ViewerRigQa.input('viewer-save-method','node','change');document.getElementById('viewer-editor-mesh-tab').click();ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('LeftUpLeg'),'change');return true;")
            let fractionalControls = try await object(webView, """
                var inputs=Array.from(document.querySelectorAll('#viewer-node-fields input'));
                function field(kind,axis){return inputs.find(function(input){return input.dataset.viewerNodeKind===kind&&input.dataset.axis===axis;});}
                var authored=ModelViewer.getAuthoringState(),s=ModelViewer.getState();
                var expectedFilename='분수 의상.zip',expectedNode=String(ViewerRigQa.nodeId('LeftUpLeg'));
                var loadedPaths=s.loadedPaths.slice(),filenames=loadedPaths.map(function(path){return String(path).split('/').pop();});
                var normalizedFilenames=filenames.map(function(name){return name.normalize('NFC');});
                var selected=document.getElementById('viewer-node');
                return JSON.stringify({offGridInputs:inputs.filter(function(input){return input.validity.stepMismatch;}).map(function(input){return {kind:input.dataset.viewerNodeKind,axis:input.dataset.axis,value:input.value,step:input.step};}),
                  saveEnabled:!document.getElementById('viewer-save').disabled,unsupported:authored.unsupported,
                  selectedLeftUpLeg:String(s.rig.selectedNode)===expectedNode,
                  expectedLeftUpLegNode:expectedNode,actualSelectedNode:String(s.rig.selectedNode),selectedDOMValue:selected.value,
                  selectedDOMLabel:selected.options[selected.selectedIndex] ? selected.options[selected.selectedIndex].text : '',
                  spinnerStepsPreserved:field('scale','Y').step==='0.001'&&field('position','Y').step==='0.001'&&field('rotation','X').step==='1',
                  originalPositionY:Number(field('position','Y').value),originalRotationX:Number(field('rotation','X').value),
                  loadedPaths:loadedPaths,loadedFilenames:filenames,normalizedLoadedFilenames:normalizedFilenames,expectedZIPFilename:expectedFilename,
                  filenameCodepoints:filenames.map(function(name){return Array.from(name).map(function(character){return character.codePointAt(0).toString(16);});}),
                  selectedZIP:normalizedFilenames.length===1&&normalizedFilenames[0]===expectedFilename.normalize('NFC')});
                """)
            report["fractional_zip_save_validation"] = fractionalControls
            try checkpoint("fractional-zip-controls-observed")
            let offGrid = fractionalControls["offGridInputs"] as? [[String: Any]] ?? []
            try require(fractionalControls["selectedZIP"] as? Bool == true,
                        "The native file chooser must open the actual ZIP (Unicode-normalized filename).")
            try require(fractionalControls["selectedLeftUpLeg"] as? Bool == true,
                        "The real editing controls must select the LeftUpLeg metadata node.")
            try require(offGrid.contains { $0["kind"] as? String == "position" } && offGrid.contains { $0["kind"] as? String == "rotation" },
                        "The original fractional position and rotation must remain visibly off the spinner grid.")
            try require(offGrid.contains { $0["kind"] as? String == "scale" && $0["value"] as? String == "1.234567" },
                        "An explicit precise scale must remain finer than the spinner increment.")
            try require(fractionalControls["spinnerStepsPreserved"] as? Bool == true && fractionalControls["saveEnabled"] as? Bool == true &&
                        (fractionalControls["unsupported"] as? [String]) == [],
                        "Finite fractional ZIP edits must enable Save without changing the existing spinner increments.")
            try require(abs((fractionalControls["originalPositionY"] as? Double ?? 0) - 0.1234567) < 0.000001 &&
                        abs(abs(fractionalControls["originalRotationX"] as? Double ?? 0) - 12.34567) < 0.0001,
                        "Untouched original fractional TRS values must remain visible without rounding.")
            try checkpoint("fractional-zip-save-enabled")
            let edits = try await object(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            let authored = edits["edits"] as? [[String: Any]] ?? []
            try require(authored.count == 2 && Set(authored.compactMap { $0["method"] as? String }) == Set(["node", "mesh"]), "Both editing backends must receive real edits.")
            let intended = try await vertices(webView)
            try require(try difference(baseline, intended) > 0.01, "The actual skin must change after editing.")
            model.perform("saveModel")
            try checkpoint("first-export")
            let first = try await saved(webView, previousJob: "")
            try checkFiles(first)
            try checkpoint("first-export-saved")
            _ = try await js(webView, "document.getElementById('viewer-open-saved').click();return true;")
            try await loaded(webView, reviewing: true)
            let reloaded = try await vertices(webView)
            let saveError = try difference(intended, reloaded)
            try require(saveError < 0.00002, "The saved Unity geometry differs from the edited target.")
            try checkpoint("first-export-reloaded")
            _ = try await js(webView, "document.getElementById('viewer-reedit-original').click();return true;")
            try await waitJS(webView, "restored edits from the preserved original", timeout: 90, expression:
                "ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&!ModelViewer.getState().persistence.busy&&ModelViewer.getAuthoringState().edits.length===2&&!ModelViewer.getState().persistence.reviewingSaved")
            model.perform("saveModel")
            try checkpoint("second-export")
            let second = try await saved(webView, previousJob: first["jobId"] as? String ?? "")
            try checkFiles(second)
            try require((first["previewPaths"] as? [String]) != (second["previewPaths"] as? [String]), "Every save must publish a distinct output folder.")
            try checkpoint("second-export-saved")
            _ = try await js(webView, "document.getElementById('viewer-open-saved').click();return true;")
            try await loaded(webView, reviewing: true)
            let rebuilt = try await vertices(webView)
            let rebuildError = try difference(reloaded, rebuilt)
            try require(rebuildError < 0.00002, "Rebuilding must not accumulate mesh deformation.")
            try require(try Data(contentsOf: source) == original, "Source bundle bytes must remain unchanged.")
            try require(try Data(contentsOf: zipSource) == originalZIP, "Source ZIP bytes must remain unchanged.")
            _ = try await js(webView, "document.getElementById('viewer-fit').click();return true;")
            try await Task.sleep(nanoseconds: 250_000_000)
            let probe = try await object(webView, "return JSON.stringify(ModelViewer.renderProbe(33));")
            try require((probe["glError"] as? Int) == 0 && (probe["nonBackgroundSamples"] as? Int ?? 0) >= 3, "Native WebKit must render the saved geometry.")
            try await snapshot(webView, directory.appendingPathComponent("saved-model.png"))
            report["fixture_sha256"] = originalHash
            report["node_and_mesh_backends"] = true
            report["source_preserved"] = true
            report["source_zip_preserved"] = true
            report["reedit_from_original"] = true
            report["saved_geometry_max_error"] = saveError
            report["rebuilt_geometry_max_error"] = rebuildError
            report["framebuffer"] = probe
            report["first_export"] = first
            report["second_export"] = second
            try checkpoint("saved-model-snapshot")
            _ = try await model.request("/v1/server/start", method: "POST")
            try checkpoint("quit-server-start-requested")
            try await wait("the game server before quitting", timeout: 120) {
                await self.model.refresh(); return self.model.snapshot.serverRunning && self.model.snapshot.server?.httpReady == true
            }
            report["go_pid_at_quit"] = model.snapshot.server?.pid
            report["server_running_when_quit_requested"] = true
            try checkpoint("quit-server-http-ready")
            try await wait("the running server HTTP endpoint before quitting", timeout: 120) {
                do {
                    var request = URLRequest(url: serverURL); request.timeoutInterval = 3
                    let (_, response) = try await URLSession.shared.data(for: request)
                    return (response as? HTTPURLResponse)?.statusCode == 200
                } catch { return false }
            }
            let runtimePID = process.processIdentifier
            try checkpoint("ordinary-native-quit-requested")
            model.smokeQuitObserver = {
                try? self.checkpoint("ordinary-native-quit-runtime-stopped")
                let deadline = Date().addingTimeInterval(2)
                while Darwin.kill(-runtimePID, 0) == 0 && Date() < deadline { try? await Task.sleep(nanoseconds: 50_000_000) }
                let terminated = Darwin.kill(-runtimePID, 0) != 0 && self.model.process?.isRunning != true
                self.report["runtime_terminated"] = terminated
                self.report["normal_app_quit_with_running_server"] = terminated
                self.report["status"] = terminated ? "PASS" : "FAIL"
                do { try self.checkpoint(terminated ? "passed" : "runtime-termination-failed") } catch { Darwin.exit(1) }
                if !terminated { Darwin.exit(1) }
            }
            // Match the normal AppKit menu event and let this actor job return
            // before starting the application's termination handshake.
            DispatchQueue.main.async { NSApplication.shared.terminate(nil) }
        } catch {
            report["status"] = "FAIL"
            report["error"] = error.localizedDescription
            report["console_tail"] = Array(model.console.suffix(100))
            await model.stopRuntime()
            report["runtime_terminated"] = model.process?.isRunning != true
            try? checkpoint("failed")
            Darwin.exit(1)
        }
    }

    private func checkpoint(_ stage: String) throws {
        guard let directory = model.smokeDirectory else { return }
        let elapsed = ProcessInfo.processInfo.systemUptime - startedAt
        stages.append(["stage": stage, "elapsed_seconds": elapsed])
        report["stage"] = stage
        report["elapsed_seconds"] = elapsed
        report["stages"] = stages
        report["console_tail"] = Array(model.console.suffix(100))
        report["runtime_process_running"] = model.process?.isRunning == true
        report["server_running"] = model.snapshot.serverRunning
        if let pid = model.process?.processIdentifier { report["python_pid"] = Int(pid) }
        if let pid = model.snapshot.server?.pid { report["current_go_pid"] = pid }
        try writeReport(directory)
        // FileHandle writes immediately even when CI redirects stdout to a file.
        FileHandle.standardOutput.write(Data(String(format: "ELICHIKA_SMOKE %.3fs %@\n", elapsed, stage).utf8))
    }

    private func writeReport(_ directory: URL) throws {
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: directory.appendingPathComponent("native-smoke.json"), options: .atomic)
    }

    private func checkUnauthorizedControl(_ url: URL) async throws {
        let endpoint = URL(string: "/v1/state", relativeTo: url)!.absoluteURL
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieAcceptPolicy = .never; config.httpShouldSetCookies = false
        let (_, response) = try await URLSession(configuration: config).data(from: endpoint)
        try require([401, 403].contains((response as? HTTPURLResponse)?.statusCode ?? 0), "Control API must refuse unauthenticated requests.")
        report["unauthenticated_control_refused"] = true
    }

    private func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
        guard try condition() else { throw NativeError.service(message) }
    }

    private func wait(_ stage: String, timeout: TimeInterval, condition: () async throws -> Bool) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if try await condition() { return }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        throw NativeError.timeout(stage)
    }

    private func js(_ webView: WKWebView, _ source: String) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            webView.callAsyncJavaScript(source, arguments: [:], in: nil, in: .page) { continuation.resume(with: $0) }
        }
    }

    private func object(_ webView: WKWebView, _ source: String) async throws -> [String: Any] {
        let value = try await js(webView, source)
        guard let string = value as? String,
              let decoded = try JSONSerialization.jsonObject(with: Data(string.utf8)) as? [String: Any] else { throw NativeError.invalidResponse }
        return decoded
    }

    private func waitJS(_ webView: WKWebView, _ stage: String, timeout: TimeInterval, expression: String) async throws {
        try await wait(stage, timeout: timeout) {
            do { return (try await self.js(webView, "return !!(" + expression + ");")) as? Bool == true }
            catch { return false }
        }
    }

    private func loaded(_ webView: WKWebView, reviewing: Bool = false) async throws {
        let review = reviewing ? "&&s.persistence.reviewingSaved" : ""
        try await waitJS(webView, "the actual Unity skin and native framebuffer", timeout: 120, expression:
            "(function(){var s=ModelViewer.getState(),p=s.loaded?ModelViewer.renderProbe(33):{ready:false};return s.loaded&&!s.loading&&!s.contextLost&&s.rig&&s.rig.available&&s.stats.meshes===1&&s.stats.vertices===6&&s.stats.triangles===4&&p.ready&&p.glError===0&&p.nonBackgroundSamples>=3&&document.getElementById('viewer-busy').hidden" + review + ";})()")
    }

    private func saved(_ webView: WKWebView, previousJob: String) async throws -> [String: Any] {
        let quotedJob = String(decoding: try JSONSerialization.data(withJSONObject: [previousJob]), as: UTF8.self) + "[0]"
        try await waitJS(webView, "real Python export and completed SSE", timeout: 120, expression:
            "(function(){var p=ModelViewer.getState().persistence;return p&&!p.busy&&!p.error&&p.jobId&&p.jobId!==" + quotedJob + "&&p.outputs.length>=2&&p.previewPaths.length===1&&!!p.recipePath;})()")
        return try await object(webView, "return JSON.stringify(ModelViewer.getState().persistence);")
    }

    private func checkFiles(_ result: [String: Any]) throws {
        guard let outputs = result["outputs"] as? [String], outputs.count >= 2,
              let recipe = result["recipePath"] as? String, outputs.contains(recipe) else { throw NativeError.invalidResponse }
        for path in outputs {
            try require(path.hasPrefix(model.libraryDirectory + "/"), "Saved output escaped the chosen library.")
            let size = try FileManager.default.attributesOfItem(atPath: path)[.size] as? NSNumber
            try require((size?.intValue ?? 0) > 0, "The export contains an empty or missing output.")
        }
    }

    private func vertices(_ webView: WKWebView) async throws -> [[Double]] {
        let result = try await object(webView, "return JSON.stringify(ViewerRigQa.deformedVertices());")
        guard let values = result["vertices"] as? [[Double]], values.count == 6 else { throw NativeError.invalidResponse }
        return values
    }

    private func difference(_ left: [[Double]], _ right: [[Double]]) throws -> Double {
        try require(left.count == right.count && left.allSatisfy { $0.count == 3 } && right.allSatisfy { $0.count == 3 }, "Skin vertex topology changed.")
        return zip(left, right).flatMap { zip($0.0, $0.1).map { abs($0.0 - $0.1) } }.max() ?? 0
    }

    private func snapshot(_ webView: WKWebView, _ destination: URL) async throws {
        let configuration = WKSnapshotConfiguration()
        configuration.afterScreenUpdates = true
        let image: NSImage = try await withCheckedThrowingContinuation { continuation in
            webView.takeSnapshot(with: configuration) { image, error in
                if let error { continuation.resume(throwing: error) }
                else if let image { continuation.resume(returning: image) }
                else { continuation.resume(throwing: NativeError.invalidResponse) }
            }
        }
        guard let bytes = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: bytes),
              let png = bitmap.representation(using: .png, properties: [:]) else { throw NativeError.invalidResponse }
        try png.write(to: destination)
    }
}
