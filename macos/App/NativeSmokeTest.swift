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
    init(model: AppModel) { self.model = model }

    func run() async {
        guard let directory = model.smokeDirectory else { return }
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try await wait("payload preparation", timeout: 420) { self.model.toolsReady }
            guard let ready = model.connection, let process = model.process else { throw NativeError.runtimeUnavailable }
            report["python_pid"] = Int(process.processIdentifier)
            report["ready_ports"] = [ready.controlURL.port!, ready.adminURL.port!, ready.toolsURL.port!]
            try await checkUnauthorizedControl(ready.controlURL)

            _ = try await model.request("/v1/server/start", method: "POST")
            try await wait("the game server", timeout: 120) {
                await self.model.refresh()
                return self.model.snapshot.serverRunning
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
            _ = try await model.request("/v1/server/stop", method: "POST")
            try await wait("the stopped game server", timeout: 15) {
                await self.model.refresh(); return !self.model.snapshot.serverRunning
            }
            report["server_stopped"] = true

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
            _ = try await js(webView, "return await ElichikaPlatform.perform('openModel');")
            try await loaded(webView)
            report["native_file_bridge_and_authorization"] = true
            let baseline = try await vertices(webView)
            _ = try await js(webView, "document.getElementById('viewer-adjustments').open=true;document.getElementById('viewer-node-editor').open=true;document.getElementById('viewer-editor-mesh-tab').click();ViewerRigQa.boneInput('LeftUpLeg','scale','Y',1.2);ViewerRigQa.input('viewer-save-method','mesh','change');document.getElementById('viewer-editor-node-tab').click();ViewerRigQa.boneInput('BreastSize','scale','Z',1.15);ViewerRigQa.input('viewer-save-method','node','change');return true;")
            let edits = try await object(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
            let authored = edits["edits"] as? [[String: Any]] ?? []
            try require(authored.count == 2 && Set(authored.compactMap { $0["method"] as? String }) == Set(["node", "mesh"]), "Both editing backends must receive real edits.")
            let intended = try await vertices(webView)
            try require(try difference(baseline, intended) > 0.01, "The actual skin must change after editing.")
            model.perform("saveModel")
            let first = try await saved(webView)
            try checkFiles(first)
            _ = try await js(webView, "document.getElementById('viewer-open-saved').click();return true;")
            try await loaded(webView, reviewing: true)
            let reloaded = try await vertices(webView)
            let saveError = try difference(intended, reloaded)
            try require(saveError < 0.00002, "The saved Unity geometry differs from the edited target.")
            _ = try await js(webView, "document.getElementById('viewer-reedit-original').click();return true;")
            try await waitJS(webView, "restored edits from the preserved original", timeout: 90, expression:
                "ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&!ModelViewer.getState().persistence.busy&&ModelViewer.getAuthoringState().edits.length===2&&!ModelViewer.getState().persistence.reviewingSaved")
            model.perform("saveModel")
            let second = try await saved(webView)
            try checkFiles(second)
            try require((first["previewPaths"] as? [String]) != (second["previewPaths"] as? [String]), "Every save must publish a distinct output folder.")
            _ = try await js(webView, "document.getElementById('viewer-open-saved').click();return true;")
            try await loaded(webView, reviewing: true)
            let rebuilt = try await vertices(webView)
            let rebuildError = try difference(reloaded, rebuilt)
            try require(rebuildError < 0.00002, "Rebuilding must not accumulate mesh deformation.")
            try require(try Data(contentsOf: source) == original, "Source bundle bytes must remain unchanged.")
            _ = try await js(webView, "document.getElementById('viewer-fit').click();return true;")
            try await Task.sleep(nanoseconds: 250_000_000)
            let probe = try await object(webView, "return JSON.stringify(ModelViewer.renderProbe(33));")
            try require((probe["glError"] as? Int) == 0 && (probe["nonBackgroundSamples"] as? Int ?? 0) >= 3, "Native WebKit must render the saved geometry.")
            try await snapshot(webView, directory.appendingPathComponent("saved-model.png"))
            report["fixture_sha256"] = originalHash
            report["node_and_mesh_backends"] = true
            report["source_preserved"] = true
            report["reedit_from_original"] = true
            report["saved_geometry_max_error"] = saveError
            report["rebuilt_geometry_max_error"] = rebuildError
            report["framebuffer"] = probe
            report["first_export"] = first
            report["second_export"] = second
            report["status"] = "PASS"
            await model.stopRuntime()
            report["runtime_terminated"] = model.process?.isRunning != true
            try require(model.process?.isRunning != true, "The owned Python runtime did not stop.")
            try writeReport(directory)
            Darwin.exit(0)
        } catch {
            report["status"] = "FAIL"
            report["error"] = error.localizedDescription
            report["console_tail"] = Array(model.console.suffix(100))
            await model.stopRuntime()
            report["runtime_terminated"] = model.process?.isRunning != true
            try? writeReport(directory)
            Darwin.exit(1)
        }
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

    private func saved(_ webView: WKWebView) async throws -> [String: Any] {
        try await waitJS(webView, "real Python export and completed SSE", timeout: 120, expression:
            "(function(){var p=ModelViewer.getState().persistence;return p&&!p.busy&&!p.error&&p.outputs.length>=2&&p.previewPaths.length===1&&!!p.recipePath;})()")
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
