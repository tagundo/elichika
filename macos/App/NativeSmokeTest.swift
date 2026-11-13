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

            try await checkOfflineManagement(directory)

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

            try await checkConsoleActions(directory)

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
            try await checkPoseBodyStructure(webView)
            try await checkNativeEditorNavigation(webView)
            let originalPanelWindowFrame = try await prepareWidePanelViewport(webView)
            let panelPreferenceFile = directory.appendingPathComponent("viewer-panel-width-expected.txt")
            let expectedPanelWidth = (try? String(contentsOf: panelPreferenceFile, encoding: .utf8))
                .flatMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
            let panelBefore = try await object(webView, """
                var handle=document.getElementById('viewer-panel-resizer');
                return JSON.stringify({metadata:ElichikaPlatform.info().viewerPanelWidth,
                  actual:document.getElementById('viewer-control-panel').getBoundingClientRect().width,
                  enabled:!!handle&&!handle.hidden,min:Number(handle.getAttribute('aria-valuemin')),
                  max:Number(handle.getAttribute('aria-valuemax'))});
                """)
            report["viewer_panel_before"] = panelBefore
            try checkpoint("viewer-panel-preference-observed")
            try require(panelBefore["enabled"] as? Bool == true, "The desktop adjustment panel must be resizable.")
            if let expectedPanelWidth {
                try require(panelBefore["metadata"] as? Int == expectedPanelWidth &&
                            UserDefaults.standard.integer(forKey: "viewerPanelWidth") == expectedPanelWidth &&
                            abs((panelBefore["actual"] as? Double ?? 0) - Double(expectedPanelWidth)) < 1,
                            "The adjustment panel width must survive an ordinary quit and relocated relaunch.")
            }
            let currentPanelWidth = Int((panelBefore["actual"] as? Double ?? 0).rounded())
            let maximumPanelWidth = panelBefore["max"] as? Int ?? 0
            let direction = currentPanelWidth + 16 <= maximumPanelWidth ? "ArrowLeft" : "ArrowRight"
            let requestedPanelWidth = currentPanelWidth + (direction == "ArrowLeft" ? 16 : -16)
            _ = try await js(webView, "var handle=document.getElementById('viewer-panel-resizer');handle.focus();handle.dispatchEvent(new KeyboardEvent('keydown',{key:'\(direction)',bubbles:true,cancelable:true}));return true;")
            try await waitJS(webView, "the resized adjustment panel", timeout: 10, expression:
                "Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-\(requestedPanelWidth))<1")
            try await wait("the native panel width preference", timeout: 10) {
                UserDefaults.standard.integer(forKey: "viewerPanelWidth") == requestedPanelWidth
            }
            try String(requestedPanelWidth).write(to: panelPreferenceFile, atomically: true, encoding: .utf8)
            report["viewer_panel_width_persistence"] = ["previous_expected": expectedPanelWidth ?? 0,
                "restored_on_relaunch": expectedPanelWidth != nil, "committed": requestedPanelWidth,
                "native_stored": UserDefaults.standard.integer(forKey: "viewerPanelWidth")]
            try checkpoint("viewer-panel-width-persisted")
            try await checkWidePanelPersistence(webView, directory: directory,
                expected: expectedPanelWidth, preferenceFile: panelPreferenceFile)
            try await restorePanelViewport(webView, frame: originalPanelWindowFrame)
            let filesPreferenceFile = directory.appendingPathComponent("viewer-files-width-expected.txt")
            let expectedFilesWidth = (try? String(contentsOf: filesPreferenceFile, encoding: .utf8))
                .flatMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
            let filePanelBefore = try await object(webView, """
                var handle=document.getElementById('viewer-files-resizer');
                return JSON.stringify({metadata:ElichikaPlatform.info().viewerFilesWidth,
                  resizerVisible:!!handle&&!handle.hidden,viewportWidth:window.innerWidth});
                """)
            report["viewer_files_before"] = filePanelBefore
            try checkpoint("viewer-files-preference-observed")
            if let expectedFilesWidth {
                try require(filePanelBefore["metadata"] as? Int == expectedFilesWidth &&
                            UserDefaults.standard.integer(forKey: "viewerFilesWidth") == expectedFilesWidth,
                            "The file selection width must survive a fresh private WebView and app relocation.")
            }
            let requestedFilesWidth = expectedFilesWidth == 224 ? 240 : 224
            _ = try await js(webView, "await ElichikaPlatform.request('setViewerFilesWidth',{width:\(requestedFilesWidth)});return true;")
            try await wait("the native file panel width preference", timeout: 10) {
                UserDefaults.standard.integer(forKey: "viewerFilesWidth") == requestedFilesWidth
            }
            try String(requestedFilesWidth).write(to: filesPreferenceFile, atomically: true, encoding: .utf8)
            report["viewer_files_width_persistence"] = ["previous_expected": expectedFilesWidth ?? 0,
                "restored_on_relaunch": expectedFilesWidth != nil, "committed": requestedFilesWidth,
                "native_stored": UserDefaults.standard.integer(forKey: "viewerFilesWidth"),
                "scope": "Native preference bridge and relaunch; the file sidebar appears only in a wide viewport"]
            try checkpoint("viewer-files-width-persisted")
            try await checkDetailWorkflow(webView, directory: directory)
            _ = try await openSmokeSource(webView, source: zipSource)
            let baseline = try await vertices(webView)
            _ = try await js(webView, "document.getElementById('viewer-adjustments').open=true;document.getElementById('viewer-body-adjustments').open=true;for(var parent=document.getElementById('viewer-node-editor');parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}document.getElementById('viewer-editor-mesh-tab').click();ViewerRigQa.boneInput('LeftUpLeg','scale','X',1.17);ViewerRigQa.boneInput('LeftUpLeg','scale','Y',1.234567);ViewerRigQa.boneInput('LeftUpLeg','scale','Z',1.17);ViewerRigQa.input('viewer-save-method','mesh','change');document.getElementById('viewer-editor-node-tab').click();ViewerRigQa.boneInput('BreastSize','scale','Z',1.17);ViewerRigQa.input('viewer-save-method','node','change');document.getElementById('viewer-editor-mesh-tab').click();ViewerRigQa.input('viewer-node',ViewerRigQa.nodeId('LeftUpLeg'),'change');return true;")
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
            try await checkAssetNavigationPreservesDraft(webView)
            try await checkSeparatePoseBodyPanels(webView)
            try await checkInvalidBodyDraftMenuSave(webView)
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
            try await checkModPackage(webView, sourceZIP: zipSource, sourceZIPHash: zipHash, previousExport: second)
            try await checkThumbnailWorkflow(webView, directory: directory, sourceZIP: zipSource, sourceZIPHash: zipHash)
            let preservedSource = try Data(contentsOf: source), preservedZIP = try Data(contentsOf: zipSource)
            try require(preservedSource == original && preservedZIP == originalZIP,
                        "Saving the installer ZIP must preserve both original fixture files.")
            try await checkMinimizedViewer(webView)
            try await checkAccessoryUnclip(webView, directory: directory)
            try await checkGamePhysics(webView, directory: directory)
            try await checkNativePCM(webView, directory: directory)
            try await checkExtendedWorkflow(webView, directory: directory)
            try await checkPartSelectionWorkflow(webView, directory: directory)
            try await checkThumbnailUpdaterWorkflow(webView, directory: directory)
            if ProcessInfo.processInfo.environment["ELICHIKA_NATIVE_PCM_GAME_QA"] == "1" {
                try await checkNativePCMGame(webView, directory: directory)
            } else {
                report["native_pcm_game_audio"] = ["status": "NOT_REQUESTED", "enabled": false]
            }
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
            if let webView = model.assetWebView {
                report["native_part_failure_diagnostic"] = try? await object(webView, """
                    function describe(node){if(!node)return null;var r=node.getBoundingClientRect();return {tag:node.tagName,id:node.id||'',classes:String(node.className||''),rect:{left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};}
                    var s=ModelViewer.getState(),panel=document.getElementById('viewer-part-transplant'),d=window.__nativePartDiagnostic||null;
                    var pointer=window.__nativePartPointer||(d&&d.lastPointer)||null,point=pointer&&(pointer.point||(pointer.request&&pointer.request.point));
                    var canvases=panel?Array.from(panel.querySelectorAll('canvas')).map(describe):[];
                    return JSON.stringify({diagnostic:d,pointer:pointer,transplants:s.transplants,loaded:s.loaded,loading:s.loading,modelId:s.modelId,paths:s.paths,stats:s.stats,
                      activeElement:describe(document.activeElement),canvases:canvases,hit:point?describe(document.elementFromPoint(point.x,point.y)):null,
                      status:panel?Array.from(panel.querySelectorAll('[role=status]')).map(function(node){return node.textContent;}):[],
                      log:panel&&panel.querySelector('.viewer-transplant-log')?panel.querySelector('.viewer-transplant-log').textContent:'',
                      viewport:{width:innerWidth,height:innerHeight,visualWidth:window.visualViewport&&visualViewport.width,visualHeight:window.visualViewport&&visualViewport.height}});
                    """)
                report["native_part_failure_window"] = nativePointerEnvironment(webView)
                try? await snapshot(webView, directory.appendingPathComponent("failure.png"))
                report["accessory_failure_diagnostic"] = try? await object(webView, """
                    var s=ModelViewer.getState(),m=ModelViewer.getEditingMetadata(),a=document.getElementById('viewer-accessory-enabled');
                    return JSON.stringify({step:window.__nativeAccessoryStep||'',loaded:s.loaded,loading:s.loading,
                      vertices:s.stats&&s.stats.vertices,editingAvailable:!!(m&&m.available),
                      authoringEnabled:!!(s.rig&&s.rig.authoringEnabled),persistenceBusy:!!(s.persistence&&s.persistence.busy),
                      reviewingSaved:!!(s.persistence&&s.persistence.reviewingSaved),
                      saveMethodDisabled:document.getElementById('viewer-save-method').disabled,
                      selectedNode:s.rig&&s.rig.selectedNode,accessoryDisabled:!!(a&&a.disabled),accessoryChecked:!!(a&&a.checked)});
                    """)
            }
            report["console_tail"] = Array(model.console.suffix(100))
            await model.stopRuntime()
            report["runtime_terminated"] = model.process?.isRunning != true
            try? checkpoint("failed")
            Darwin.exit(1)
        }
    }

    private func openSmokeSource(_ webView: WKWebView, source: URL) async throws -> String {
        let old = try await object(webView, "return JSON.stringify({id:ModelViewer.getState().modelId||''});")
        let oldID = String(decoding: try JSONSerialization.data(withJSONObject: [old["id"] as? String ?? ""]), as: UTF8.self) + "[0]"
        _ = try await js(webView, "var a=document.getElementById('viewer-auto-face');if(a&&a.checked)a.click();return true;")
        let paths = try await model.authorize([source])
        model.selectedSection = .viewer
        model.browser(.assets).perform("openModel", paths: paths)
        try await waitJS(webView, "the newly authorized native QA source", timeout: 120, expression:
            "ModelViewer.getState().modelId!==" + oldID + "&&ModelViewer.getState().loaded&&!ModelViewer.getState().loading")
        try await loaded(webView)
        return paths[0]
    }

    private func sendNativePointer(_ request: [String: Any], webView: WKWebView) async throws -> [String: Any] {
        guard let point = request["point"] as? [String: Double], let viewport = request["viewport"] as? [String: Double],
              let x = point["x"], let y = point["y"], let width = viewport["width"], let height = viewport["height"],
              let window = webView.window else { throw NativeError.invalidResponse }
        try require(width > 0 && height > 0 && x.isFinite && y.isFinite && x >= 0 && y >= 0 && x < width && y < height,
                    "Actual donor input must identify a finite visible CSS point.")
        NSApplication.shared.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(webView)
        @MainActor func focused() -> Bool {
            guard NSApplication.shared.isActive, window.isVisible, window.isKeyWindow,
                  NSApplication.shared.keyWindow === window else { return false }
            guard let responder = window.firstResponder as? NSView else { return false }
            return responder === webView || responder.isDescendant(of: webView)
        }
        try await wait("the active key window and WebKit first responder before native input", timeout: 10) {
            if NSApplication.shared.isActive && window.isKeyWindow { window.makeFirstResponder(webView) }
            return focused()
        }
        _ = try await js(webView, "await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});return true;")
        try require(focused(), "Native pointer input requires the active visible key window and actual WebKit first responder.")
        let readyWindow = nativePointerEnvironment(webView, request: request)
        try require(readyWindow["requestedHitInsideWebView"] as? Bool == true,
                    "Native pointer input must still hit the actual WebKit view after focus and event-loop readiness.")
        let encodedPoint = String(decoding: try JSONSerialization.data(withJSONObject: point), as: UTF8.self)
        let readyDOM = try await object(webView, """
            var p=\(encodedPoint),hit=document.elementFromPoint(p.x,p.y),v=window.visualViewport;
            function describe(n){if(!n)return null;var r=n.getBoundingClientRect();return {tag:n.tagName,id:n.id||'',classes:String(n.className||''),rect:{left:r.left,top:r.top,width:r.width,height:r.height}};}
            return JSON.stringify({hit:describe(hit),active:describe(document.activeElement),
                canvases:Array.from(document.querySelectorAll('#viewer-part-transplant canvas')).map(describe),
                viewport:{width:innerWidth,height:innerHeight,offsetLeft:v&&v.offsetLeft,offsetTop:v&&v.offsetTop,scale:v&&v.scale}});
            """)
        let bounds = webView.bounds
        let local = NSPoint(x: bounds.minX + CGFloat(x / width) * bounds.width,
                            y: webView.isFlipped ? bounds.minY + CGFloat(y / height) * bounds.height : bounds.maxY - CGFloat(y / height) * bounds.height)
        let location = webView.convert(local, to: nil)
        let number = request["id"] as? Int ?? 0
        guard let down = NSEvent.mouseEvent(with: .leftMouseDown, location: location, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber, context: nil,
                eventNumber: number * 2, clickCount: 1, pressure: 1),
              let up = NSEvent.mouseEvent(with: .leftMouseUp, location: location, modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime + 0.01, windowNumber: window.windowNumber, context: nil,
                eventNumber: number * 2 + 1, clickCount: 1, pressure: 0) else { throw NativeError.invalidResponse }
        NSApplication.shared.postEvent(down, atStart: false)
        NSApplication.shared.postEvent(up, atStart: false)
        try await Task.sleep(nanoseconds: 20_000_000)
        return ["id": number, "target": request["target"] ?? "", "css": point, "viewport": viewport,
                "webViewBounds": ["width": bounds.width, "height": bounds.height], "webViewFlipped": webView.isFlipped,
                "windowPoint": ["x": location.x, "y": location.y],
                "readyWindow": readyWindow,
                "readyDOM": readyDOM,
                "method": "NSApplication.postEvent NSEvent leftMouseDown/leftMouseUp FIFO; DOM isTrusted is independently required"]
    }

    private func prepareWidePanelViewport(_ webView: WKWebView) async throws -> NSRect {
        guard let window = webView.window else { throw NativeError.runtimeUnavailable }
        let original = window.frame
        report["viewer_panel_wide_window"] = ["originalWidth": original.width,
            "originalHeight": original.height, "screenWidth": window.screen?.visibleFrame.width ?? 0]
        // Resize the real AppKit window, rather than supplying a CSS width or a
        // synthetic DOM rectangle. Restore it before trusted native canvas input.
        var wide = original
        wide.size.width = max(original.width, 1600)
        window.setFrame(wide, display: true, animate: false)
        window.contentView?.layoutSubtreeIfNeeded()
        try await waitJS(webView, "a genuinely wide native adjustment viewport", timeout: 15, expression:
            "window.innerWidth>=1200&&!document.getElementById('viewer-panel-resizer').hidden&&" +
            "Number(document.getElementById('viewer-panel-resizer').getAttribute('aria-valuemax'))>=704")
        try require(window.frame.width >= 1600 && webView.bounds.width >= 1200,
                    "The width persistence probe must use the actual enlarged AppKit window and WebView.")
        try checkpoint("viewer-panel-native-wide-viewport")
        return original
    }

    private func checkWidePanelPersistence(_ webView: WKWebView, directory: URL,
                                          expected: Int?, preferenceFile: URL) async throws {
        let before = try await object(webView, """
            var handle=document.getElementById('viewer-panel-resizer'),panel=document.getElementById('viewer-control-panel');
            handle.scrollIntoView({block:'center'});
            var r=handle.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return JSON.stringify({viewportWidth:innerWidth,viewportHeight:innerHeight,actual:panel.getBoundingClientRect().width,
              min:Number(handle.getAttribute('aria-valuemin')),max:Number(handle.getAttribute('aria-valuemax')),
              enabled:!handle.hidden,visible:r.width>0&&r.height>0,hittable:hit===handle||!!(hit&&handle.contains(hit))});
            """)
        try require(before["enabled"] as? Bool == true && before["visible"] as? Bool == true &&
                    before["hittable"] as? Bool == true && (before["viewportWidth"] as? Double ?? 0) >= 1200,
                    "The actual wide native resize control must be visible and reachable.")
        let maximum = before["max"] as? Int ?? 0
        let current = Int((before["actual"] as? Double ?? 0).rounded())
        let goal = min(expected == nil ? 736 : 800, maximum)
        var steps = Int(ceil(Double(goal - current) / 16.0))
        if current + steps * 16 > maximum { steps -= 1 }
        let requested = current + steps * 16
        try require(requested > 640 && requested <= maximum && NativeRequest.viewerPanelWidthRange.contains(requested),
                    "The native width probe must genuinely exceed the former 640px limit within actual allowed bounds.")
        let direction = steps >= 0 ? "ArrowLeft" : "ArrowRight"
        _ = try await js(webView, """
            var handle=document.getElementById('viewer-panel-resizer');handle.focus();
            for(var index=0;index<\(abs(steps));index++){
              handle.dispatchEvent(new KeyboardEvent('keydown',{key:'\(direction)',bubbles:true,cancelable:true}));
              await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            }
            return true;
            """)
        try await waitJS(webView, "the actual adjustment panel above 640px", timeout: 15, expression:
            "Math.abs(document.getElementById('viewer-control-panel').getBoundingClientRect().width-\(requested))<1&&" +
            "localStorage.getItem('elichika.viewer.panel-width.v1')==='\(requested)'")
        try await wait("the native bridge must store the real width above 640px", timeout: 10) {
            UserDefaults.standard.integer(forKey: "viewerPanelWidth") == requested
        }
        let observed = try await object(webView, """
            var r=document.getElementById('viewer-control-panel').getBoundingClientRect();
            return JSON.stringify({viewportWidth:innerWidth,viewportHeight:innerHeight,actual:r.width,left:r.left,right:r.right,
              max:Number(document.getElementById('viewer-panel-resizer').getAttribute('aria-valuemax')),
              modelWidth:document.getElementById('viewer-stage').getBoundingClientRect().width,
              localStored:Number(localStorage.getItem('elichika.viewer.panel-width.v1'))});
            """)
        try require(abs((observed["actual"] as? Double ?? 0) - Double(requested)) < 1 &&
                    (observed["left"] as? Double ?? -1) >= 0 &&
                    (observed["right"] as? Double ?? .infinity) <= (observed["viewportWidth"] as? Double ?? 0) &&
                    (observed["modelWidth"] as? Double ?? 0) >= 319,
                    "The above-640 panel must occupy real viewport space and retain a usable model area.")
        report["viewer_panel_width_legacy_resize"] = report["viewer_panel_width_persistence"]
        try String(requested).write(to: preferenceFile, atomically: true, encoding: .utf8)
        report["viewer_panel_width_persistence"] = ["previous_expected": expected ?? 0,
            "restored_on_relaunch": expected != nil, "committed": requested,
            "native_stored": UserDefaults.standard.integer(forKey: "viewerPanelWidth"),
            "native_allowed_min": NativeRequest.viewerPanelWidthRange.lowerBound,
            "native_allowed_max": NativeRequest.viewerPanelWidthRange.upperBound,
            "ui_allowed_max": maximum, "wide_viewport": observed,
            "above_previous_limit": true, "scope": "Actual AppKit resize, production keyboard resizer/native bridge/store, then relocated metadata and width restoration"]
        try await snapshot(webView, directory.appendingPathComponent("wide-panel-controls.png"))
        try checkpoint("viewer-panel-above640-persisted")
    }

    private func restorePanelViewport(_ webView: WKWebView, frame: NSRect) async throws {
        guard let window = webView.window else { throw NativeError.runtimeUnavailable }
        window.setFrame(frame, display: true, animate: false)
        window.contentView?.layoutSubtreeIfNeeded()
        try await wait("the original native window before trusted canvas input", timeout: 10) {
            abs(window.frame.width - frame.width) < 1 && abs(window.frame.height - frame.height) < 1
        }
        try await waitJS(webView, "the restored native WebView layout", timeout: 10, expression:
            "document.getElementById('viewer-control-panel').getBoundingClientRect().right<=innerWidth+1")
        report["viewer_panel_native_window_restored"] = ["width": window.frame.width,
            "height": window.frame.height, "webViewWidth": webView.bounds.width,
            "native_stored": UserDefaults.standard.integer(forKey: "viewerPanelWidth")]
        try checkpoint("viewer-panel-native-window-restored")
    }

    private func nativePointerEnvironment(_ webView: WKWebView, request: [String: Any]? = nil) -> [String: Any] {
        func rect(_ value: NSRect) -> [String: CGFloat] {
            ["x": value.origin.x, "y": value.origin.y, "width": value.width, "height": value.height]
        }
        func describe(_ view: NSView?) -> [String: Any] {
            guard let view else { return ["class": "none"] }
            return ["class": String(describing: type(of: view)), "identifier": view.identifier?.rawValue ?? "",
                    "frame": rect(view.frame), "bounds": rect(view.bounds), "hidden": view.isHidden]
        }
        let mouse = NSEvent.mouseLocation
        var value: [String: Any] = ["mouseScreen": ["x": mouse.x, "y": mouse.y], "appActive": NSApplication.shared.isActive,
            "keyWindow": NSApplication.shared.keyWindow?.windowNumber ?? -1,
            "modalWindow": NSApplication.shared.modalWindow?.windowNumber ?? -1,
            "webView": describe(webView), "webViewFlipped": webView.isFlipped]
        guard let window = webView.window else { return value }
        value["window"] = ["number": window.windowNumber, "key": window.isKeyWindow, "visible": window.isVisible,
                           "frame": rect(window.frame), "content": describe(window.contentView)]
        if let responder = window.firstResponder {
            value["firstResponderClass"] = String(describing: type(of: responder))
            if let view = responder as? NSView {
                value["firstResponder"] = describe(view)
                value["firstResponderInsideWebView"] = view === webView || view.isDescendant(of: webView)
            }
        }
        let mouseWindow = window.convertPoint(fromScreen: mouse)
        value["mouseWindow"] = ["x": mouseWindow.x, "y": mouseWindow.y]
        if let point = request?["point"] as? [String: Double], let viewport = request?["viewport"] as? [String: Double],
           let x = point["x"], let y = point["y"], let width = viewport["width"], let height = viewport["height"], width > 0, height > 0 {
            let bounds = webView.bounds
            let local = NSPoint(x: bounds.minX + CGFloat(x / width) * bounds.width,
                y: webView.isFlipped ? bounds.minY + CGFloat(y / height) * bounds.height : bounds.maxY - CGFloat(y / height) * bounds.height)
            let location = webView.convert(local, to: nil)
            value["requestedLocalPoint"] = ["x": local.x, "y": local.y]
            value["requestedWindowPoint"] = ["x": location.x, "y": location.y]
            if let content = window.contentView {
                let hit = content.hitTest(content.superview?.convert(location, from: nil) ?? location)
                value["requestedHitView"] = describe(hit)
                value["requestedHitInsideWebView"] = hit === webView || hit?.isDescendant(of: webView) == true
            }
        }
        return value
    }

    private func recordNativePartProgress(_ webView: WKWebView, phase: String, pointer: [String: Any]?,
                                          events: [[String: Any]], attempts: [[String: Any]], handled: Set<Int>) async {
        let diagnostic = try? await object(webView, "return JSON.stringify(window.__nativePartDiagnostic||{});")
        report["native_part_progress"] = ["phase": phase, "pointer": pointer ?? [:], "diagnostic": diagnostic ?? [:],
            "nativeEvents": events, "nativeAttempts": attempts, "handledIDs": handled.sorted(),
            "window": nativePointerEnvironment(webView, request: pointer)]
        try? checkpoint("native-part-progress-" + phase)
    }

    private func checkPartSelectionWorkflow(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-part-selection-source")
        let source = directory.appendingPathComponent("part-target.unity"), donor = directory.appendingPathComponent("part-donor.unity")
        let inputs: [(URL, String)] = [(source, "fe6f3c7749f116faad61152ee6f76978a4200e409dd5c0c577ce505a33f3a7f8"),
            (donor, "de4e0e267f9435f626b0a1e7d556375f6fe2d12a7da22227ce7dbd373fd42d89")]
        let originals = try inputs.map { try Data(contentsOf: $0.0) }
        for (index, input) in inputs.enumerated() {
            try require(originals[index].count == 81847 && SHA256.hash(data: originals[index]).map { String(format: "%02x", $0) }.joined() == input.1,
                        "Native partial graft must use the exact original neutral target and donor bytes.")
        }
        let paths = try await model.authorize([source, donor])
        _ = try await js(webView, "var a=document.getElementById('viewer-auto-face');if(a&&a.checked)a.click();return true;")
        model.selectedSection = .viewer
        model.browser(.assets).perform("openModel", paths: [paths[0]])
        try await loaded(webView, expectedVertices: 60, expectedTriangles: 20)
        let options = ["sourcePath": paths[0], "donorPath": paths[1]]
        let encoded = String(decoding: try JSONSerialization.data(withJSONObject: options), as: UTF8.self)
        let helper = try String(contentsOf: model.resourceDirectory.appendingPathComponent("qa/viewer_part_selection_qa.js"), encoding: .utf8)
        _ = try await js(webView, helper + ";window.__nativePartResult=null;window.__nativePartError='';" +
            "NativePartQa.run(" + encoded + ").then(function(value){window.__nativePartResult=value;},function(error){window.__nativePartError=[String(error&&error.message||error),String(error&&error.stack||'')].join('\\n');});return true;")
        var handled = Set<Int>(), events: [[String: Any]] = [], attempts: [[String: Any]] = []
        var lastProgress = "", progressCount = 0
        try await wait("actual native trusted donor model and UV input", timeout: 300) {
            let pending = try await self.object(webView, "return JSON.stringify({error:window.__nativePartError||'',done:!!window.__nativePartResult,pointer:window.__nativePartPointer||null,phase:window.__nativePartDiagnostic&&window.__nativePartDiagnostic.phase||'awaiting-helper'});")
            let phase = pending["phase"] as? String ?? "awaiting-helper"
            let pointer = pending["pointer"] as? [String: Any]
            let progress = phase + ":" + String(pointer?["id"] as? Int ?? 0)
            if progress != lastProgress && progressCount < 64 {
                lastProgress = progress; progressCount += 1
                await self.recordNativePartProgress(webView, phase: phase, pointer: pointer, events: events, attempts: attempts, handled: handled)
            }
            if let error = pending["error"] as? String, !error.isEmpty { throw NativeError.service(error) }
            if pending["done"] as? Bool == true { return true }
            if let request = pointer, request["pending"] as? Bool == true,
               let id = request["id"] as? Int, !handled.contains(id) {
                attempts.append(["id": id, "request": request, "before": self.nativePointerEnvironment(webView, request: request)])
                await self.recordNativePartProgress(webView, phase: "pointer-\(id)-before", pointer: request, events: events, attempts: attempts, handled: handled)
                events.append(try await self.sendNativePointer(request, webView: webView))
                handled.insert(id)
                await self.recordNativePartProgress(webView, phase: "pointer-\(id)-after", pointer: request, events: events, attempts: attempts, handled: handled)
            }
            return false
        }
        var observed = try await object(webView, "return JSON.stringify(window.__nativePartResult);")
        try require(observed["status"] as? String == "PASS" && events.count == 6,
                    "Actual native partial graft must pass all hierarchy, source face and trusted pointer assertions.")
        for (index, input) in inputs.enumerated() {
            try require(try Data(contentsOf: input.0) == originals[index], "Partial graft must preserve both original source files.")
        }
        observed["source_path"] = source.path
        observed["source_sha256"] = inputs[0].1
        observed["donor_path"] = donor.path
        observed["donor_sha256"] = inputs[1].1
        observed["sourcePreserved"] = true
        observed["nativeEvents"] = events
        report["native_part_selection"] = observed
        try await snapshot(webView, directory.appendingPathComponent("part-selection-controls.png"))
        try checkpoint("native-part-selection-passed")
    }

    private func checkThumbnailUpdaterWorkflow(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-thumbnail-updater-source")
        let root = URL(fileURLWithPath: model.libraryDirectory).appendingPathComponent("native-thumbnail-inputs")
        let source = root.appendingPathComponent("member6/viewer_thumbnail_member_6.zip")
        let other = root.appendingPathComponent("member201/viewer_thumbnail_member_201.zip")
        let inputs: [(URL, String, Int)] = [(source, "e60eb0fa3e6e1860bb956e70337c23908faab3f2a9c66192531b645b971538f7", 17405),
            (other, "473fb2c5a57c95b5259ada0c3bf88eaf7db4586f8c662d4f03cfeaceb48fa969", 17421)]
        let originals = try inputs.map { try Data(contentsOf: $0.0) }
        for (index, input) in inputs.enumerated() {
            try require(originals[index].count == input.2 && SHA256.hash(data: originals[index]).map { String(format: "%02x", $0) }.joined() == input.1,
                        "The updater must use the exact separate member6/member201 neutral installer ZIPs.")
        }
        let output = URL(fileURLWithPath: model.libraryDirectory).appendingPathComponent("native-thumbnail-updates")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let authorized = try await model.authorize([source, other, output])
        let options: [String: Any] = ["paths": Array(authorized.prefix(2)), "outDirectory": authorized[2], "expectedOwners": [6, 201]]
        let encoded = String(decoding: try JSONSerialization.data(withJSONObject: options), as: UTF8.self)
        model.selectedSection = .assets
        model.browser(.assets).setEditorSurface(.tools)
        try await waitJS(webView, "the native updater tools surface", timeout: 15, expression:
            "document.getElementById('tab-tools').classList.contains('active')")
        let helper = try String(contentsOf: model.resourceDirectory.appendingPathComponent("qa/viewer_thumbnail_updater_qa.js"), encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativeThumbnailUpdaterQa.run(" + encoded + "));")
        try require(observed["status"] as? String == "PASS", "Actual native shared multi-selection and thumbnail updater did not pass.")
        for (index, input) in inputs.enumerated() {
            try require(try Data(contentsOf: input.0) == originals[index], "The updater must preserve both original installer ZIPs.")
        }
        observed["source_sha256"] = inputs.map { $0.1 }
        observed["sourcePreserved"] = true
        report["native_thumbnail_updater"] = observed
        try await snapshot(webView, directory.appendingPathComponent("thumbnail-updater-controls.png"))
        try checkpoint("native-thumbnail-updater-passed")
    }

    private func checkDetailWorkflow(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-detail-source")
        let source = directory.appendingPathComponent("detail-source.unity")
        let original = try Data(contentsOf: source)
        let digest = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
        try require(digest == "0536f659457f2a6df0f3fb7451aa449b65720735c54e571b5204fd6d6602aee1",
                    "The detail controls must use the exact clean neutral source.")
        _ = try await openSmokeSource(webView, source: source)
        let helper = try String(contentsOf: model.resourceDirectory.appendingPathComponent("qa/viewer_detail_qa.js"), encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativeDetailQa.run());")
        try require(observed["status"] as? String == "PASS", "Actual WebKit detail controls did not pass.")
        try require(try Data(contentsOf: source) == original, "Outline/mesh detail inspection must preserve the source.")
        observed["source_path"] = source.path
        observed["source_sha256"] = digest
        observed["sourcePreserved"] = true
        report["native_detail"] = observed
        try await snapshot(webView, directory.appendingPathComponent("detail-controls.png"))
        try checkpoint("native-detail-passed")
    }

    private func checkExtendedWorkflow(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-extended-source")
        let source = directory.appendingPathComponent("gaze-source.unity")
        let motion = directory.appendingPathComponent("library-motion.unity")
        let otherBody = directory.appendingPathComponent("game-physics.unity")
        let inputs: [(URL, String)] = [(source, "4058786fad837b3292bf1fdba0b9181719b7c7e9e756a705c266af146d113129"),
            (motion, "b512951eaa10cc2cce1d53dca961ad3abbc5e731ce4c58a7b78ee9c4cc2ce7a9"),
            (otherBody, "d619ef6e956d3b8557660ebbd070e8c998c0c0c82dc2fb97a8755c2a4d74e66e")]
        let originals = try inputs.map { try Data(contentsOf: $0.0) }
        for (index, item) in inputs.enumerated() {
            let digest = SHA256.hash(data: originals[index]).map { String(format: "%02x", $0) }.joined()
            try require(digest == item.1, "An extended native QA source changed.")
        }
        let paths = try await model.authorize([source, motion, otherBody])
        _ = try await openSmokeSource(webView, source: source)
        let options = ["sourcePath": paths[0], "motionPath": paths[1], "otherBodyPath": paths[2]]
        let encoded = String(decoding: try JSONSerialization.data(withJSONObject: options), as: UTF8.self)
        let helper = try String(contentsOf: model.resourceDirectory.appendingPathComponent("qa/viewer_extended_qa.js"), encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativeExtendedQa.run(" + encoded + "));")
        try require(observed["status"] as? String == "PASS", "Actual WebKit extended viewer controls did not pass.")
        for (index, item) in inputs.enumerated() {
            try require(try Data(contentsOf: item.0) == originals[index], "Extended viewer controls must preserve every input.")
        }
        observed["source_path"] = source.path
        observed["source_sha256"] = inputs[0].1
        observed["motion_path"] = motion.path
        observed["motion_sha256"] = inputs[1].1
        observed["other_body_path"] = otherBody.path
        observed["other_body_sha256"] = inputs[2].1
        observed["sourcePreserved"] = true
        report["native_extended"] = observed
        try await snapshot(webView, directory.appendingPathComponent("extended-controls.png"))
        try checkpoint("native-extended-passed")
    }

    private func checkGamePhysics(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-game-physics-source")
        let source = directory.appendingPathComponent("game-physics.unity")
        let original = try Data(contentsOf: source)
        let digest = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
        try require(original.count == 78128 && digest == "d619ef6e956d3b8557660ebbd070e8c998c0c0c82dc2fb97a8755c2a4d74e66e",
                    "The original neutral game-physics fixture must match its audited input.")
        let old = try await object(webView, "return JSON.stringify({id:ModelViewer.getState().modelId||''});")
        let oldID = String(decoding: try JSONSerialization.data(withJSONObject: [old["id"] as? String ?? ""]), as: UTF8.self) + "[0]"
        let paths = try await model.authorize([source])
        model.selectedSection = .viewer
        model.browser(.assets).perform("openModel", paths: paths)
        try await waitJS(webView, "the actual game-physics source", timeout: 120, expression:
            "ModelViewer.getState().modelId!==" + oldID + "&&ModelViewer.getState().loaded&&!ModelViewer.getState().loading")
        try await loaded(webView)
        let helperURL = model.resourceDirectory.appendingPathComponent("qa/native_game_physics_qa.js")
        let helper = try String(contentsOf: helperURL, encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativeGamePhysicsQa.run());")
        try require(observed["status"] as? String == "PASS", "The actual WebKit game-physics probe failed.")
        try require(try Data(contentsOf: source) == original, "Game-physics preview must preserve its original source bytes.")
        observed["source_path"] = source.path
        observed["source_sha256"] = digest
        observed["source_preserved"] = true
        observed["sourcePreserved"] = true
        observed["fixture"] = "viewer_game_physics.unity"
        report["native_game_physics"] = observed
        try await snapshot(webView, directory.appendingPathComponent("game-physics.png"))
        try checkpoint("native-game-physics-passed")
    }

    private func checkNativePCM(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-pcm-audio-started")
        let source = directory.appendingPathComponent("game-physics.unity")
        let original = try Data(contentsOf: source)
        let digest = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
        try require(digest == "d619ef6e956d3b8557660ebbd070e8c998c0c0c82dc2fb97a8755c2a4d74e66e",
                    "The PCM transport must use the existing original neutral model.")
        let helperURL = model.resourceDirectory.appendingPathComponent("qa/native_pcm_qa.js")
        let helper = try String(contentsOf: helperURL, encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativePCMQa.run());")
        try require(observed["status"] as? String == "PASS", "The actual native PCM transport checks failed.")
        try require(try Data(contentsOf: source) == original, "Audio transport must preserve original model bytes.")
        var sources: [String: String] = [:]
        for name in ["viewer-native-pcm-player.js", "viewer-motion-audio.js"] {
            let bytes = try Data(contentsOf: model.resourceDirectory.appendingPathComponent("python-app/webtools/web/static/" + name))
            sources[name] = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        }
        let helperBytes = try Data(contentsOf: helperURL)
        observed["helper_sha256"] = SHA256.hash(data: helperBytes).map { String(format: "%02x", $0) }.joined()
        observed["product_source_sha256"] = sources
        observed["source_path"] = source.path
        observed["source_sha256"] = digest
        observed["source_preserved"] = true
        report["native_pcm_audio"] = observed
        try checkpoint("native-pcm-audio-passed")
    }

    private func checkNativePCMGame(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-official-pcm-game-started")
        var observed = try await object(webView, "return JSON.stringify(await NativePCMQa.runGame());")
        observed["enabled"] = true
        report["native_pcm_game_audio"] = observed
        try require(observed["status"] as? String == "PASS", "The actual official Eli/CHASE PCM workload failed; see its network/import/engine stage.")
        let loaded = observed["loaded"] as? [String: Any] ?? [:]
        let paths = loaded["paths"] as? [String] ?? []
        let library = URL(fileURLWithPath: model.libraryDirectory, isDirectory: true).standardizedFileURL
        try require(paths.count == 1, "The official workload must use one original Eli body input.")
        let source = URL(fileURLWithPath: paths[0]).standardizedFileURL
        try require(source.path.hasPrefix(library.path + "/extracted/game-models/") && source.lastPathComponent == "ch0002_suit400022007_primary.unity",
                    "The official Eli body must come from this smoke test's own normal game import.")
        let body = try Data(contentsOf: source)
        let bodyHash = SHA256.hash(data: body).map { String(format: "%02x", $0) }.joined()
        try require(bodyHash == "cbfae69d2f37e5b8b2240f905e59289580ce73836fca3f46c421e9bc5da5404c",
                    "The actual Eli workload must preserve the original audited body bytes.")
        let pcm = observed["originalPCM"] as? [String: Any] ?? [:]
        let pcmFormat = pcm["pcm"] as? [String: Any] ?? [:]
        guard let inputHash = pcm["sha256"] as? String, inputHash.count == 64,
              let inputBytes = pcmFormat["encodedBytes"] as? Int else {
            throw NativeError.invalidResponse
        }
        let audioDirectory = library.appendingPathComponent("extracted/game-motions/audio", isDirectory: true)
        var matches: [[String: Any]] = []
        for file in try FileManager.default.contentsOfDirectory(at: audioDirectory, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey], options: [.skipsHiddenFiles]) where file.pathExtension == "wav" {
            let values = try file.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
            guard values.isRegularFile == true, values.fileSize == inputBytes, inputBytes <= 32 * 1024 * 1024 else { continue }
            let bytes = try Data(contentsOf: file)
            let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
            if digest == inputHash { matches.append(["path": file.path, "sha256": digest, "bytes": bytes.count]) }
        }
        try require(!matches.isEmpty, "The observed real linked response must match this same job's original cached PCM WAV bytes.")
        observed["official_body"] = ["path": source.path, "bytes": body.count, "sha256": bodyHash, "preserved": true]
        observed["same_job_cached_pcm"] = matches
        let helper = try Data(contentsOf: model.resourceDirectory.appendingPathComponent("qa/native_pcm_qa.js"))
        observed["helper_sha256"] = SHA256.hash(data: helper).map { String(format: "%02x", $0) }.joined()
        var product: [String: String] = [:]
        for name in ["viewer-native-pcm-player.js", "viewer-motion-audio.js"] {
            let bytes = try Data(contentsOf: model.resourceDirectory.appendingPathComponent("python-app/webtools/web/static/" + name))
            product[name] = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        }
        observed["product_source_sha256"] = product
        report["native_pcm_game_audio"] = observed
        try checkpoint("native-official-pcm-game-passed")
    }

    private func checkAccessoryUnclip(_ webView: WKWebView, directory: URL) async throws {
        try checkpoint("native-accessory-source")
        let source = directory.appendingPathComponent("accessory-overlap.unity")
        let original = try Data(contentsOf: source)
        let digest = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
        try require(digest == "4d59e904442cd75bb70368e16a46c369ad977a3b73677cff581a6fc53d8e043e",
                    "The own-geometry accessory fixture must match the audited input.")
        let before = try await object(webView, "return JSON.stringify({id:ModelViewer.getState().modelId||''});")
        let oldID = String(decoding: try JSONSerialization.data(withJSONObject: [before["id"] as? String ?? ""]), as: UTF8.self) + "[0]"
        _ = try await js(webView, "var a=document.getElementById('viewer-auto-face');if(a&&a.checked)a.click();return true;")
        let paths = try await model.authorize([source])
        let authorizedPath = String(decoding: try JSONSerialization.data(withJSONObject: [paths[0]]), as: UTF8.self) + "[0]"
        model.selectedSection = .viewer
        model.browser(.assets).perform("openModel", paths: paths)
        try await waitJS(webView, "the newly authorized accessory source", timeout: 120, expression:
            "ModelViewer.getState().modelId!==" + oldID + "&&ModelViewer.getState().loaded&&!ModelViewer.getState().loading")
        try await loaded(webView, expectedVertices: 21, expectedTriangles: 7)
        try checkpoint("native-accessory-rendered")
        report["accessory_setup_readiness_before"] = try await object(webView, """
            var s=ModelViewer.getState(),m=ModelViewer.getEditingMetadata(),a=document.getElementById('viewer-accessory-enabled');
            return JSON.stringify({loaded:s.loaded,loading:s.loading,editingAvailable:!!(m&&m.available),
              authoringEnabled:!!(s.rig&&s.rig.authoringEnabled),persistenceBusy:!!(s.persistence&&s.persistence.busy),
              reviewingSaved:!!(s.persistence&&s.persistence.reviewingSaved),accessoryDisabled:!!(a&&a.disabled)});
            """)
        try await waitJS(webView, "the current source's writable editing session", timeout: 30, expression:
            "(function(){var s=ModelViewer.getState(),m=ModelViewer.getEditingMetadata(),p=s.persistence;return !!window.ViewerAccessories&&!!s.accessories&&s.loaded&&!s.loading&&s.loadedPaths.length===1&&s.loadedPaths[0]===" + authorizedPath + "&&m&&m.available&&m.token&&s.rig&&s.rig.available&&s.rig.authoringEnabled===true&&p&&!p.busy&&!p.reviewingSaved;})()")
        try checkpoint("native-accessory-metadata-ready")
        _ = try await js(webView, """
            window.__nativeAccessoryStep='open-body-editor';
            document.getElementById('viewer-body-adjustments').open=true;
            document.getElementById('viewer-node-editor').open=true;
            document.getElementById('viewer-editor-node-tab').click();return true;
            """)
        try await waitJS(webView, "the writable source's bone selector", timeout: 15, expression:
            "!document.getElementById('viewer-node').disabled")
        for axis in ["X", "Y", "Z"] {
            _ = try await js(webView, "window.__nativeAccessoryStep='bone-scale-\(axis)';ViewerRigQa.boneInput('BreastSize','scale','\(axis)',2);return true;")
        }
        try await waitJS(webView, "the selected BreastSize save method control", timeout: 15, expression:
            "String(ModelViewer.getState().rig.selectedNode)===String(ViewerRigQa.nodeId('BreastSize'))&&!document.getElementById('viewer-save-method').disabled")
        _ = try await js(webView, "window.__nativeAccessoryStep='save-method';ViewerRigQa.input('viewer-save-method','node','change');document.getElementById('viewer-accessory-card').open=true;return true;")
        try await waitJS(webView, "the current source's enabled accessory control", timeout: 15, expression:
            "!document.getElementById('viewer-accessory-enabled').disabled")
        _ = try await js(webView, "window.__nativeAccessoryStep='enable-accessory';var c=document.getElementById('viewer-accessory-enabled');if(!c.checked)c.click();return true;")
        try checkpoint("native-accessory-controls-changed")
        try await waitJS(webView, "the real accessory request and derived preview", timeout: 90, expression:
            "(function(){var a=ModelViewer.getState().accessories;return a&&a.enabled&&!a.pending&&!a.error&&a.status==='ready'&&a.changed===1;})()")
        let preview = try await object(webView, "return JSON.stringify(ModelViewer.getState().accessories);")
        let authored = try await object(webView, "return JSON.stringify(ModelViewer.getAuthoringState());")
        let edits = authored["edits"] as? [[String: Any]] ?? []
        let options = authored["accessoryUnclip"] as? [String: Any] ?? [:]
        try require(edits.count == 1 && edits[0]["method"] as? String == "node" && edits[0]["compensate"] as? Bool == false,
                    "Derived accessory movement must not become another body edit.")
        try require(options["strength"] as? Double == 1 && options["overlap"] as? Double == 0.15 && options["closeGaps"] as? Bool == false,
                    "The actual accessory UI must preserve its default source-bound settings.")
        let response = try await object(webView, """
            var state=ModelViewer.getAuthoringState();delete state.unsupported;
            var response=await fetch('/api/viewer/edit/accessories',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({token:ModelViewer.getEditingMetadata().token,state:state})});
            var value=await response.json();if(!response.ok||value.error)throw new Error(value.error||'Accessory endpoint failed');
            return JSON.stringify(value);
            """)
        let summary = response["summary"] as? [String: Any] ?? [:]
        let corrections = response["corrections"] as? [[String: Any]] ?? []
        try require(summary["status"] as? String == "applied" && summary["changed"] as? Int == 1 && corrections.count == 1,
                    "The real HTTP endpoint must derive exactly one accessory anchor.")
        guard let delta = corrections[0]["delta"] as? [Double] else { throw NativeError.invalidResponse }
        let anchor = try await object(webView, """
            var targets=ModelViewer.getEditingMetadata().nodes.filter(function(n){return n.name==='PartsA_Offset';});
            if(targets.length!==1)throw new Error('The source metadata must identify one accessory anchor');
            var target=targets[0],bones=ModelViewer.getState().rig.bones.filter(function(b){return String(b.node)===String(target.node);});
            if(bones.length!==1)throw new Error('The real rig must identify the source accessory node exactly once');
            return JSON.stringify({node:target.node,position:bones[0].position,path:bones[0].name});
            """)
        guard let position = anchor["position"] as? [Double], let anchorNode = anchor["node"] as? Int,
              let correctionNode = corrections[0]["node"] as? Int else { throw NativeError.invalidResponse }
        try require(anchorNode == correctionNode, "The HTTP correction must target the same stable source anchor as the real rig.")
        // Independent fixture centroid C; uniform2 requests (2-1)*C.
        try require(try difference([delta], [[-0.25166666666666665, 0.013333333333333334, 0.025]]) < 0.000002,
                    "The actual HTTP correction differs from the independent original centroid.")
        try require(try difference([position], [[-0.26166666666666666, 0.03333333333333333, 0.045]]) < 0.000002,
                    "The real WebGL rig must install the derived anchor exactly once.")
        let intended = try await vertices(webView, expectedCount: 21)
        let prior = try await object(webView, "return JSON.stringify(ModelViewer.getState().persistence);")
        model.perform("saveModel")
        try checkpoint("native-accessory-export")
        let result = try await saved(webView, previousJob: prior["jobId"] as? String ?? "")
        try checkFiles(result)
        guard let recipePath = result["recipePath"] as? String,
              let recipe = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: recipePath))) as? [String: Any],
              let state = recipe["state"] as? [String: Any] else { throw NativeError.invalidResponse }
        try require(state["accessoryUnclip"] as? [String: Any] != nil && (state["edits"] as? [[String: Any]])?.count == 1,
                    "The recipe must retain accessory settings without accumulating derived offsets.")
        _ = try await js(webView, "document.getElementById('viewer-open-saved').click();return true;")
        try await loaded(webView, reviewing: true, expectedVertices: 21, expectedTriangles: 7)
        let reloaded = try await vertices(webView, expectedCount: 21)
        let error = try difference(intended, reloaded)
        try require(error < 0.00002, "Saved accessory geometry must match all live skinned vertices without double application.")
        try require(try Data(contentsOf: source) == original, "Accessory editing must preserve its original source bytes.")
        try await snapshot(webView, directory.appendingPathComponent("accessory-saved-model.png"))
        report["native_accessory_unclip"] = ["status": "PASS", "source_path": source.path, "fixture_sha256": digest,
            "actual_http_response": response, "actual_preview": preview, "actual_anchor": position, "actual_anchor_node": anchorNode,
            "export": result, "source_preserved": true, "derived_offset_excluded_from_edits": true,
            "recipe_flag_preserved": true, "saved_geometry_max_error": error, "skinned_vertices_compared": 21]
        try checkpoint("native-accessory-reloaded")
    }

    private func checkMinimizedViewer(_ webView: WKWebView) async throws {
        let prefs = ["panel": UserDefaults.standard.integer(forKey: "viewerPanelWidth"),
                     "files": UserDefaults.standard.integer(forKey: "viewerFilesWidth")]
        let before = try await editingSnapshot(webView)
        let originalVertices = try await vertices(webView)
        let observe = """
            var state=ModelViewer.getState(),metadata=ModelViewer.getEditingMetadata();
            return JSON.stringify({minimized:state.layout.minimized,direction:state.layout.minimizeDirection,
              expanded:state.layout.expanded,fullscreen:state.layout.fullscreen,shortHeight:state.layout.shortHeight,
              token:metadata.token,selection:JSON.stringify(state.loadedPaths),
              folds:JSON.stringify(Array.from(document.querySelectorAll('#viewer-control-panel details')).map(function(element,index){return [element.id||String(index),element.open];})),
              editorWidth:document.getElementById('viewer-control-panel').getBoundingClientRect().width,
              modelWidth:document.querySelector('.viewer-model-panel').getBoundingClientRect().width,
              prepareRequests:performance.getEntriesByType('resource').filter(function(entry){return new URL(entry.name).pathname==='/api/viewer/prepare';}).length});
            """
        let initial = try await object(webView, observe)
        try require(initial["minimized"] as? Bool == false && initial["direction"] as? String == "width" &&
                    initial["expanded"] as? Bool == false && initial["fullscreen"] as? String == "none" && initial["shortHeight"] as? Bool == false,
                    "The native minimize test must use the ordinary unchanged Mac window.")
        guard let token = initial["token"] as? String, !token.isEmpty,
              let initialPrepares = initial["prepareRequests"] as? Int else { throw NativeError.invalidResponse }
        _ = try await js(webView, """
            var button=document.getElementById('viewer-minimize');button.scrollIntoView({block:'nearest'});
            await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var rect=button.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
            if(button.disabled||rect.width<32||rect.height<32||!(hit===button||button.contains(hit)))throw new Error('The real minimize control must be a visible native WebKit target');
            button.click();return true;
            """)
        try await waitJS(webView, "the minimized native model rail", timeout: 10, expression: "ModelViewer.getState().layout.minimized===true")
        _ = try await js(webView, "await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});return true;")
        let minimized = try await object(webView, observe)
        try require(minimized["direction"] as? String == "width" &&
                    (minimized["editorWidth"] as? Double ?? 0) > (initial["editorWidth"] as? Double ?? 0) + 100 &&
                    (minimized["modelWidth"] as? Double ?? 1000) <= 60,
                    "The ordinary Mac rail must release real width for editing.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        let restore = try await object(webView, """
            var button=document.getElementById('viewer-model-restore');button.scrollIntoView({block:'nearest'});
            await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var rect=button.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
            if(button.hidden||rect.width<44||rect.height<44||!(hit===button||button.contains(hit)))throw new Error('The actual model restore rail must expose a 44px target');
            var target={width:rect.width,height:rect.height,hittable:true};button.click();return JSON.stringify(target);
            """)
        try await waitJS(webView, "the restored retained native model", timeout: 10, expression:
            "!ModelViewer.getState().layout.minimized&&(function(){var p=ModelViewer.renderProbe(33);return p.ready&&p.glError===0&&p.nonBackgroundSamples>=3;})()")
        _ = try await js(webView, "await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});return true;")
        let restored = try await object(webView, observe)
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        for observation in [minimized, restored] {
            for key in ["token", "selection", "folds"] {
                guard let retained = initial[key] as? String, let actual = observation[key] as? String else { throw NativeError.invalidResponse }
                try require(actual == retained, "Minimize and restore must preserve the active source and manual folds: " + key)
            }
            guard let actualPrepares = observation["prepareRequests"] as? Int else { throw NativeError.invalidResponse }
            try require(actualPrepares == initialPrepares,
                        "Minimize must retain the existing model without another prepare request.")
        }
        try require(restored["minimized"] as? Bool == false &&
                    abs((restored["editorWidth"] as? Double ?? 0) - (initial["editorWidth"] as? Double ?? 0)) < 1 &&
                    prefs["panel"] == UserDefaults.standard.integer(forKey: "viewerPanelWidth") &&
                    prefs["files"] == UserDefaults.standard.integer(forKey: "viewerFilesWidth"),
                    "Restoring the model must recover the editor width and preserve native width preferences.")
        let restoredVertices = try await vertices(webView)
        try require(try difference(originalVertices, restoredVertices) < 0.00002, "Minimize must not change the actual skin geometry.")
        report["viewer_minimize_validation"] = ["status": "PASS", "direction": "width", "restore_target": restore,
            "editor_width_before": initial["editorWidth"] ?? 0, "editor_width_minimized": minimized["editorWidth"] ?? 0,
            "editor_width_restored": restored["editorWidth"] ?? 0, "rail_width": minimized["modelWidth"] ?? 0,
            "source_token_selection_folds_preserved": true, "model_camera_authoring_preserved": true,
            "native_preferences_preserved": true, "no_additional_prepare": true, "no_job_mutation": true,
            "restore_method": "Actual native WebKit restore button click; native keyboard Enter is not exercised"]
        try checkpoint("native-model-minimize-restored")
    }

    private func checkModPackage(_ webView: WKWebView, sourceZIP: URL, sourceZIPHash: String, previousExport: [String: Any]) async throws {
        _ = try await js(webView, "document.getElementById('viewer-reedit-original').click();return true;")
        try await waitJS(webView, "the preserved source and both body edits before Mod ZIP packaging", timeout: 90, expression:
            "ModelViewer.getState().loaded&&!ModelViewer.getState().loading&&!ModelViewer.getState().persistence.busy&&!ModelViewer.getState().persistence.reviewingSaved&&ModelViewer.getAuthoringState().edits.length===2")
        let expectedName = String(repeating: "맥의상", count: 40)
        let quotedName = String(decoding: try JSONSerialization.data(withJSONObject: [expectedName]), as: UTF8.self) + "[0]"
        let setup = try await object(webView, """
            function expose(element){for(var parent=element;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}element.scrollIntoView({block:'center'});}
            performance.clearResourceTimings();performance.setResourceTimingBufferSize(4096);
            var name=document.getElementById('viewer-mod-name'),owner=document.getElementById('viewer-mod-character');
            expose(name);var automatic=name.value,automaticLength=automatic.length;
            if(ModelViewer.getState().persistence.modNameManual||!automatic.normalize('NFC').includes('분수')||automaticLength<1||automaticLength>120||name.maxLength!==120)throw new Error('The actual edited costume must suggest a bounded Unicode name');
            name.value=\(quotedName);name.dispatchEvent(new Event('input',{bubbles:true}));
            document.getElementById('viewer-mod-name-auto').click();
            if(name.value!==automatic||ModelViewer.getState().persistence.modNameManual)throw new Error('Automatic name must restore the real edit-based suggestion');
            name.value=\(quotedName);name.dispatchEvent(new Event('input',{bubbles:true}));
            expose(owner);owner.value='6';owner.dispatchEvent(new Event('change',{bubbles:true}));
            var thumbnailMode=document.getElementById('viewer-mod-thumbnail-mode');expose(thumbnailMode);
            thumbnailMode.value='texture';thumbnailMode.dispatchEvent(new Event('change',{bubbles:true}));
            if(ModelViewer.getState().persistence.thumbnailMode!=='texture')throw new Error('Preserve the ordinary texture Mod ZIP gate before automatic 3D thumbnail QA');
            var button=document.getElementById('viewer-save-mod');expose(button);
            await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var rect=button.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
            if(button.disabled||rect.width<34||rect.height<34||!(hit===button||button.contains(hit))||name.value.length!==120||owner.value!=='6')throw new Error('The actual Save mod ZIP button and explicit owner must be usable');
            return JSON.stringify({automaticName:automatic,automaticLength:automaticLength,manualName:name.value,manualLength:name.value.length,characterId:Number(owner.value),
              oldJob:ModelViewer.getState().persistence.jobId,thumbnailMode:ModelViewer.getState().persistence.thumbnailMode,buttonTarget:{width:rect.width,height:rect.height,hittable:true},
              installRequests:performance.getEntriesByType('resource').filter(function(entry){return entry.name.includes('/api/viewer/edit/install');}).length});
            """)
        report["viewer_mod_package_controls"] = setup
        try checkpoint("mod-package-controls-ready")
        try require(setup["manualName"] as? String == expectedName && setup["manualLength"] as? Int == 120 && setup["characterId"] as? Int == 6,
                    "The new package form must retain the exact Unicode 120-character name and explicit owner.")
        let before = try await vertices(webView)
        _ = try await js(webView, "document.getElementById('viewer-save-mod').click();return true;")
        let packaged = try await saved(webView, previousJob: setup["oldJob"] as? String ?? "")
        try require((packaged["modPackage"] as? [String: Any])?["characterId"] as? Int == 6,
                    "Save mod ZIP must complete a fresh real package job.")
        let response = try await object(webView, """
            var state=ModelViewer.getState().persistence,response=await fetch('/api/viewer/edit/result/'+state.jobId);
            if(!response.ok)throw new Error('The completed package receipt was not available');
            var result=await response.json();result.installRequests=performance.getEntriesByType('resource').filter(function(entry){return entry.name.includes('/api/viewer/edit/install');}).length;
            return JSON.stringify(result);
            """)
        guard let receipt = response["mod_package"] as? [String: Any], let packagePath = receipt["package_path"] as? String,
              let digest = receipt["sha256"] as? String, let previews = response["preview_paths"] as? [String], previews.count == 1,
              let previous = previousExport["previewPaths"] as? [String], previous.count == 1,
              let beforeInstalls = setup["installRequests"] as? Int, let afterInstalls = response["installRequests"] as? Int else { throw NativeError.invalidResponse }
        try require(response["installed"] == nil && beforeInstalls == 0 && afterInstalls == 0 &&
                    receipt["display_name"] as? String == expectedName && receipt["character_id"] as? Int == 6 && receipt["installable"] as? Bool == true,
                    "Save mod ZIP must preserve its receipt and must not request installation.")
        try checkFiles(["outputs": response["output_paths"] ?? [], "recipePath": response["recipe_path"] ?? ""])
        let after = try await vertices(webView)
        try require(try difference(before, after) < 0.00002, "Creating a Mod ZIP must preserve the actual edited preview geometry.")
        let inspected = try await inspectModPackage(packagePath, edited: previews[0], previous: previous[0], source: sourceZIP,
                                                   sourceHash: sourceZIPHash, expectedName: expectedName, expectedHash: digest)
        report["viewer_mod_package_validation"] = ["status": "PASS", "automatic_name_checked": true, "fresh_job": true,
            "manual_name_characters": 120, "character_id": 6, "no_install_requested": true, "bundled_python": true,
            "receipt_sha256": digest, "package_path": packagePath, "inspection": inspected,
            "scope": "Actual native WebKit Save mod ZIP and bundled Python inspection; Add to game is not invoked"]
        try checkpoint("mod-package-inspected")
    }

    private func checkThumbnailWorkflow(_ webView: WKWebView, directory: URL, sourceZIP: URL, sourceZIPHash: String) async throws {
        try checkpoint("native-thumbnail-controls")
        let original = try Data(contentsOf: sourceZIP)
        let helper = try String(contentsOf: model.resourceDirectory.appendingPathComponent("qa/viewer_thumbnail_qa.js"), encoding: .utf8)
        _ = try await js(webView, helper + ";return true;")
        var observed = try await object(webView, "return JSON.stringify(await NativeThumbnailQa.run({characterId:6,reeditOriginal:true}));")
        try require(observed["status"] as? String == "PASS", "Actual WebKit automatic 3D thumbnail controls did not pass.")
        try require(try Data(contentsOf: sourceZIP) == original &&
                    SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined() == sourceZIPHash,
                    "Automatic thumbnail saving must preserve the actual source ZIP.")
        observed["source_path"] = sourceZIP.path
        observed["source_sha256"] = sourceZIPHash
        observed["sourcePreserved"] = true
        report["native_thumbnail"] = observed
        try await snapshot(webView, directory.appendingPathComponent("thumbnail-controls.png"))
        try checkpoint("native-thumbnail-saved")
    }

    private func inspectModPackage(_ path: String, edited: String, previous: String, source: URL, sourceHash: String,
                                   expectedName: String, expectedHash: String) async throws -> [String: Any] {
        let code = """
            import ast,base64,hashlib,io,json,pathlib,sys,unicodedata,zipfile
            package,edited,previous,source,source_hash,name_base64,package_hash,resources=sys.argv[1:]
            name=base64.b64decode(name_base64,validate=True).decode('utf-8')
            sha=lambda raw:hashlib.sha256(raw).hexdigest()
            runtime=pathlib.Path(resources)/'runtime/arm64/python'
            prefix=pathlib.Path(sys.prefix)
            def filesystem_identity(path):
                try:
                    info=path.stat();return {'device':info.st_dev,'inode':info.st_ino}
                except OSError as error:return {'error':str(error)}
            prefix_diagnostic={'actual_prefix':str(prefix),'expected_prefix':str(runtime),
                'actual_identity':filesystem_identity(prefix),'expected_identity':filesystem_identity(runtime)}
            try:private_prefix_samefile=prefix.samefile(runtime)
            except OSError as error:
                private_prefix_samefile=False;prefix_diagnostic['samefile_error']=str(error)
            assert private_prefix_samefile,prefix_diagnostic
            original=pathlib.Path(source).read_bytes();assert sha(original)==source_hash
            def only_model(path):
                raw=pathlib.Path(path).read_bytes()
                if not zipfile.is_zipfile(io.BytesIO(raw)):return raw
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    files=[item for item in archive.infolist() if not item.is_dir()]
                    assert len(files)==1,'The neutral fixture must contain exactly one model'
                    return archive.read(files[0])
            saved=only_model(edited);prior=only_model(previous);assert saved==prior and saved!=only_model(source)
            raw=pathlib.Path(package).read_bytes();assert sha(raw)==package_hash
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries=archive.namelist();assert len(entries)==len(set(entries))
                assert all(not pathlib.PurePosixPath(item).is_absolute() and '..' not in pathlib.PurePosixPath(item).parts for item in entries)
                manifests=[item for item in entries if pathlib.PurePosixPath(item).name=='modinstall.txt'];assert len(manifests)==1
                assert [item for item in entries if item.lower().endswith('.txt')]==manifests
                assert not any(item.lower().endswith('.zip') for item in entries)
                values={}
                for node in ast.parse(archive.read(manifests[0]).decode('utf-8-sig')).body:
                    assert isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
                    key=node.targets[0].id;assert key not in values;values[key]=ast.literal_eval(node.value)
                names={key:values.get(key) for key in ['costume_name_en','costume_name_ko','costume_name_zh','costume_name_ja','costume_description']}
                diagnostic={'owner':values.get('chara_id'),'expected_characters':len(name),
                    'expected_nfc':unicodedata.normalize('NFC',name)==name,
                    'manifest_characters':{key:len(value) if isinstance(value,str) else None for key,value in names.items()},
                    'manifest_names_equal':all(value==name for value in names.values())}
                assert values['chara_id']==6 and len(name)==120 and unicodedata.normalize('NFC',name)==name,diagnostic
                assert all(value==name and len(value)==120 and unicodedata.normalize('NFC',value)==value for value in names.values()),diagnostic
                model=values['costume_file'];assert archive.read(model)==saved
                thumbnail=values['thumbnail_file'];assert archive.read(thumbnail).startswith(b'\\x89PNG\\r\\n\\x1a\\n')
                assert not values.get('costume_file_ios') and not values.get('rina_unmask_costume_file')
            assert pathlib.Path(source).read_bytes()==original
            print(json.dumps({'status':'PASS','character_id':6,'name_characters':len(name),'manifest_names_match':True,
                'model_bytes_match':True,'model_sha256':sha(saved),'source_preserved':True,'thumbnail_png':True,
                'safe_installer_structure':True,'expected_name_transport':'base64-utf8','manifest_names_nfc':True,
                'private_prefix_samefile':private_prefix_samefile,
                'package_sha256':sha(raw),'package_bytes':len(raw),'python_executable':sys.executable}))
            """
        let child = Process(), output = Pipe(), errors = Pipe()
        child.executableURL = model.resourceDirectory.appendingPathComponent("runtime/arm64/python/bin/python3")
        // Foundation can use decomposed filesystem representations for argv.
        // Preserve the exact expected text through an ASCII-only transport;
        // the inspector compares the actual manifest without normalizing it.
        let expectedNameArgument = Data(expectedName.utf8).base64EncodedString()
        child.arguments = ["-I", "-B", "-c", code, path, edited, previous, source.path, sourceHash, expectedNameArgument, expectedHash, model.resourceDirectory.path]
        child.currentDirectoryURL = model.dataDirectory
        var environment = ProcessInfo.processInfo.environment
        for key in Array(environment.keys) where key.hasPrefix("DYLD_") || key == "PYTHONPATH" || key == "PYTHONHOME" { environment.removeValue(forKey: key) }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"; environment["PYTHONNOUSERSITE"] = "1"
        child.environment = environment; child.standardInput = FileHandle.nullDevice
        child.standardOutput = output; child.standardError = errors
        try child.run()
        do { try await wait("bundled Python installer ZIP inspection", timeout: 30) { !child.isRunning } }
        catch {
            if child.isRunning { child.terminate() }
            let deadline = Date().addingTimeInterval(2)
            while child.isRunning && Date() < deadline { try? await Task.sleep(nanoseconds: 50_000_000) }
            if child.isRunning { Darwin.kill(child.processIdentifier, SIGKILL) }
            throw error
        }
        let result = output.fileHandleForReading.readDataToEndOfFile()
        let failure = errors.fileHandleForReading.readDataToEndOfFile()
        try require(child.terminationStatus == 0, "The bundled Python Mod ZIP inspection failed: " + String(decoding: failure.prefix(2048), as: UTF8.self))
        guard let decoded = try JSONSerialization.jsonObject(with: result) as? [String: Any], decoded["status"] as? String == "PASS" else { throw NativeError.invalidResponse }
        return decoded
    }

    private func checkNativeEditorNavigation(_ webView: WKWebView) async throws {
        let before = try await editingSnapshot(webView)
        let prepares = try await js(webView, "return performance.getEntriesByType('resource').filter(function(entry){return new URL(entry.name).pathname==='/api/viewer/prepare';}).length;") as? Int
        let session = model.browser(.assets)
        model.selectedSection = .assets
        session.setEditorSurface(.tools)
        try await waitJS(webView, "the native asset tool surface", timeout: 10, expression:
            "document.getElementById('tab-tools').classList.contains('active')&&!ModelViewer.getState().visible")
        try require(model.assetWebView === webView, "The asset tools and 3D sidebar must share one WebView.")
        let tools = try await object(webView, """
            return JSON.stringify({headerHidden:getComputedStyle(document.querySelector('body > header')).display==='none',
              galleryInTools:document.querySelectorAll('#tool-list button[data-id="texture_previews"]').length===1,
              noGalleryTab:document.querySelectorAll('.tab[data-tab="gallery"]').length===0});
            """)
        for key in ["headerHidden", "galleryInTools", "noGalleryTab"] {
            try require(tools[key] as? Bool == true, "The native sidebar must replace duplicate web navigation: " + key)
        }
        model.selectedSection = .viewer
        session.setEditorSurface(.viewer)
        try await waitJS(webView, "the retained native 3D surface", timeout: 10, expression:
            "document.getElementById('tab-viewer').classList.contains('active')&&ModelViewer.getState().visible")
        try require(model.assetWebView === webView, "Returning to 3D must retain the same WebView.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        let after = try await js(webView, "return performance.getEntriesByType('resource').filter(function(entry){return new URL(entry.name).pathname==='/api/viewer/prepare';}).length;") as? Int
        try require(prepares != nil && prepares == after, "Native sidebar changes must not reload or prepare the model again.")
        report["native_editor_navigation"] = ["status": "PASS", "single_webview": true,
            "model_camera_authoring_preserved": true, "no_extra_prepare": true,
            "header_hidden": true, "texture_previews_inside_tools": true,
            "scope": "Actual native sidebar selection binding and the same cached WebKit document"]
        try checkpoint("native-editor-navigation-preserved")
    }

    private func checkPoseBodyStructure(_ webView: WKWebView) async throws {
        let structure = try await object(webView, """
            var pose=document.getElementById('viewer-adjustments'),body=document.getElementById('viewer-body-adjustments');
            var expression=document.getElementById('viewer-expression-adjustments');
            return JSON.stringify({poseOpen:pose.open,bodyOpen:body.open,
              accessoryOpen:document.getElementById('viewer-accessory-card').open,
              siblings:pose.parentElement===body.parentElement&&body.parentElement===expression.parentElement,
              separate:!pose.contains(body)&&!body.contains(pose)&&!body.contains(expression),
              motionOwnedByPose:['viewer-motion','viewer-play','viewer-time'].every(function(id){return pose.contains(document.getElementById(id))&&!body.contains(document.getElementById(id));}),
              editingOwnedByBody:['viewer-editor-tabs','viewer-node-editor'].every(function(id){return body.contains(document.getElementById(id))&&!pose.contains(document.getElementById(id));})});
            """)
        report["pose_body_panel_structure"] = structure
        try checkpoint("pose-body-panel-structure")
        try require(structure["poseOpen"] as? Bool == false, "Pose and motion must start collapsed.")
        try require(structure["accessoryOpen"] as? Bool == true, "The accessory panel must start open before smoke helpers expose controls.")
        for key in ["bodyOpen", "siblings", "separate", "motionOwnedByPose", "editingOwnedByBody"] {
            try require(structure[key] as? Bool == true, "Pose and body must be independent sibling panels with their own controls: " + key)
        }
        try await checkFreshFileHeader(webView)
    }

    private func checkFreshFileHeader(_ webView: WKWebView) async throws {
        let observed = try await object(webView, """
            var state=ModelViewer.getState(),model=document.getElementById('viewer-model-files'),motions=document.getElementById('viewer-motion-files');
            var list=document.getElementById('viewer-file-list'),motionList=document.getElementById('viewer-motion-file-list');
            var name=document.getElementById('viewer-model-file-name'),count=document.getElementById('viewer-model-file-count');
            var badge=document.getElementById('viewer-model-options-count'),motionCount=document.getElementById('viewer-motion-file-count');
            var workspaceBadge=document.getElementById('viewer-workspace-model-count');
            var options=document.getElementById('viewer-file-options'),summary=model.querySelector('summary'),gear=options.querySelector('summary');
            function rect(node){var r=node.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};}
            var files={modelPaths:Array.from(list.querySelectorAll('li > span')).map(function(row){return row.title;}),
              motionPaths:Array.from(motionList.querySelectorAll('li > span')).map(function(row){return row.title;}),modelName:name.textContent,
              modelCount:Number(count.textContent),modelCountHidden:count.hidden,modelBadge:Number(badge.textContent),modelBadgeHidden:badge.hidden,
              motionCount:Number(motionCount.textContent),motionHidden:motions.hidden,modelListOwned:model.contains(list),
              motionListOwned:motions.contains(motionList)&&document.getElementById('viewer-adjustments').contains(motions),
              compactEmbedded:model.classList.contains('viewer-model-files-embedded'),modelHeaderHeight:summary.getBoundingClientRect().height,
              fileActionsHeight:document.querySelector('.viewer-file-actions').getBoundingClientRect().height,badgePosition:getComputedStyle(badge).position,
              workspaceCount:Number(workspaceBadge.textContent),workspaceCountHidden:workspaceBadge.hidden,workspaceBadgePosition:getComputedStyle(workspaceBadge).position};
            if(JSON.stringify(files.modelPaths)!==JSON.stringify(state.paths)||JSON.stringify(files.motionPaths)!==JSON.stringify(state.motionLibraryPaths)||
              !files.modelListOwned||!files.motionListOwned||model.contains(motionList)||files.modelCount!==state.paths.length||files.modelBadge!==state.paths.length||
              files.modelName!==state.paths[0].split('/').pop()||files.modelCountHidden!==(state.paths.length<2)||files.modelBadgeHidden!==(state.paths.length<2)||
              files.workspaceCount!==state.paths.length||files.workspaceCountHidden!==(state.paths.length<2)||files.workspaceBadgePosition!=='absolute'||
              files.motionCount!==state.motionLibraryPaths.length||files.motionHidden!==!state.motionLibraryPaths.length)throw new Error('Fresh native model and motion lists must remain separate and source-bound');
            var style=getComputedStyle(name),layout={viewport:{width:innerWidth,height:innerHeight},summary:rect(summary),name:rect(name),gear:rect(gear),
              nameOverflow:style.overflow,nameWhiteSpace:style.whiteSpace,nameTextOverflow:style.textOverflow,
              summaryDisplay:getComputedStyle(summary).display,embeddedInOptions:options.contains(model),badgePosition:files.badgePosition};
            if(layout.badgePosition!=='absolute'||files.fileActionsHeight<=0)throw new Error('The compact model count must not create another flow row');
            if(files.compactEmbedded){if(!layout.embeddedInOptions||layout.summaryDisplay!=='none')throw new Error('Compact model files must be inside model options');}
            else if(layout.summary.width<=0||layout.summary.height<32||layout.name.width<=0||layout.name.left<layout.summary.left-1||layout.name.right>layout.summary.right+1||
              layout.nameOverflow!=='hidden'||layout.nameWhiteSpace!=='nowrap'||layout.nameTextOverflow!=='ellipsis')throw new Error('The actual model header must stay bounded and truncate long names');
            return JSON.stringify({status:'PASS',statePaths:state.paths,stateMotionPaths:state.motionLibraryPaths,files:files,layout:layout,
              scope:'Actual native fresh model header, source-bound file lists and measured desktop layout; no360px native-window claim.'});
            """)
        try require(observed["status"] as? String == "PASS", "The actual fresh native file header must pass.")
        report["native_file_header"] = observed
        try checkpoint("native-file-header-source-and-layout")
        try await checkMacSidebarLayout(webView)
    }

    private func checkMacSidebarLayout(_ webView: WKWebView) async throws {
        let before = try await editingSnapshot(webView)
        let observed = try await object(webView, """
            var panel=document.getElementById('viewer-files-panel'),display=document.getElementById('viewer-display-options'),save=document.getElementById('viewer-save-panel');
            var importer=document.querySelector('.viewer-file-actions'),chooser=document.getElementById('viewer-model-files');
            var displaySlot=document.getElementById('viewer-macos-display-slot'),saveSlot=document.getElementById('viewer-macos-save-slot');
            if(!panel||!displaySlot||!saveSlot||display.parentElement!==displaySlot||save.parentElement!==saveSlot||
              !panel.contains(displaySlot)||!panel.contains(importer)||!panel.contains(saveSlot))throw new Error('Mac View and Save must belong to their left-sidebar groups');
            var order=!!(displaySlot.compareDocumentPosition(importer)&Node.DOCUMENT_POSITION_FOLLOWING)&&!!(importer.compareDocumentPosition(saveSlot)&Node.DOCUMENT_POSITION_FOLLOWING);
            if(!order||document.getElementById('viewer-control-panel').contains(display)||document.getElementById('viewer-control-panel').contains(save))throw new Error('The Mac left-sidebar order must remain View, Import, Save');
            var priorOpen=chooser.open,priorScroll=panel.scrollTop;
            try {
              chooser.open=true;await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
              var button=document.querySelector('#viewer-file-list .viewer-remove');if(!button)throw new Error('The actual selected model must have one remove control');
              button.scrollIntoView({block:'nearest'});await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
              for(var ancestor=button.parentElement;ancestor;ancestor=ancestor.parentElement)ancestor.scrollLeft=0;
              var rect=button.getBoundingClientRect(),row=button.parentElement.getBoundingClientRect(),bounds=panel.getBoundingClientRect(),list=button.closest('ul');
              var hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2),name=button.parentElement.querySelector('span'),style=getComputedStyle(name);
              var remove={width:rect.width,height:rect.height,left:rect.left,right:rect.right,rowRight:row.right,panelLeft:bounds.left,panelRight:bounds.right,
                panelClientWidth:panel.clientWidth,panelScrollWidth:panel.scrollWidth,listClientWidth:list.clientWidth,listScrollWidth:list.scrollWidth,
                hittable:hit===button||button.contains(hit),filename:name.textContent,title:name.title,ellipsis:style.textOverflow,whiteSpace:style.whiteSpace};
              if(button.disabled||remove.width<32||remove.height<32||!remove.hittable||remove.left<remove.panelLeft-1||remove.right>remove.panelRight-1||remove.right>remove.rowRight+1)throw new Error('The actual Mac filename remove X must remain visible and hittable inside its sidebar row');
              if(remove.panelScrollWidth>remove.panelClientWidth+1||remove.listScrollWidth>remove.listClientWidth+1||remove.ellipsis!=='ellipsis'||remove.whiteSpace!=='nowrap'||!remove.title.endsWith(remove.filename))throw new Error('Mac filename rows must truncate text without horizontal clipping');
              return JSON.stringify({status:'PASS',checks:{leftOwned:true,displayThenImportThenSave:true,rightColumnExcludesLeftCards:true,
                noHorizontalOverflow:true,removeVisibleHittable:true,filenameTruncation:true},
                displayParent:display.parentElement.id,saveParent:save.parentElement.id,remove:remove,
                scope:'Actual AppKit WKWebView layout and DOM hit testing for the selected neutral fixture; no OS pointer-click or long-filename stress claim.'});
            } finally {chooser.open=priorOpen;panel.scrollTop=priorScroll;}
            """)
        try require(observed["status"] as? String == "PASS", "Native Mac left-sidebar and remove control checks must pass.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        var result = observed
        result["model_camera_authoring_and_save_preserved"] = true
        report["native_sidebar_layout"] = result
        try checkpoint("native-left-sidebar-order-and-remove-target")
    }

    private func editingSnapshot(_ webView: WKWebView) async throws -> [String: Any] {
        try await object(webView, """
            var s=ModelViewer.getState(),r=s.rig,a=ModelViewer.getAuthoringState();
            return JSON.stringify({modelId:s.modelId,loadedPaths:JSON.stringify(s.loadedPaths),
              authoring:JSON.stringify(a),authoringEdits:JSON.stringify(a.edits),camera:JSON.stringify(s.camera),
              rig:JSON.stringify({selectedNode:r.selectedNode,editorGroup:r.editorGroup,editingMethods:r.editingMethods,
                nodeAdjustments:r.nodeAdjustments,selectedClip:r.selectedClip,playing:r.playing,time:r.time,evaluation:r.evaluation,
                body:r.body,bodyControls:r.bodyControls,expressions:r.expressions}),
              persistence:JSON.stringify(s.persistence),saveEnabled:!document.getElementById('viewer-save').disabled,
              expressionOpen:document.getElementById('viewer-expression-adjustments').open});
            """)
    }

    private func checkAssetNavigationPreservesDraft(_ webView: WKWebView) async throws {
        let before = try await editingSnapshot(webView)
        _ = try await js(webView, """
            window.__nativeAssetNavigationCanvas=document.getElementById('viewer-canvas');
            window.__nativeAssetNavigationContext=__nativeAssetNavigationCanvas.getContext('webgl2')||__nativeAssetNavigationCanvas.getContext('webgl');
            return !!window.__nativeAssetNavigationContext;
            """)
        model.selectedSection = .assets
        try await waitJS(webView, "the native asset-tools destination", timeout: 15,
                         expression: "window.ElichikaNavigation&&ElichikaNavigation.currentSection()==='tools'")
        try require(model.assetWebView === webView, "Tools and 3D must reuse the same native WebView.")
        _ = try await js(webView, "ElichikaNavigation.showSection('viewer',{notify:true});return true;")
        try await wait("page-to-native viewer selection", timeout: 15) { self.model.selectedSection == .viewer }
        try await waitJS(webView, "the page-selected viewer destination", timeout: 15,
                         expression: "ElichikaNavigation.currentSection()==='viewer'")
        model.selectedSection = .assets
        try await waitJS(webView, "the second native asset-tools destination", timeout: 15,
                         expression: "ElichikaNavigation.currentSection()==='tools'")
        model.selectedSection = .viewer
        try await waitJS(webView, "the native 3D destination", timeout: 15,
                         expression: "ElichikaNavigation.currentSection()==='viewer'")
        _ = try await js(webView, "return await ElichikaPlatform.request('setSection',{section:'tools',event:'ready'});")
        try require(model.selectedSection == .viewer, "A late page-ready event must not replace the native destination.")
        try await waitJS(webView, "the latest native destination after page readiness", timeout: 15,
                         expression: "ElichikaNavigation.currentSection()==='viewer'")
        let retainedContext = try await js(webView, """
            var canvas=document.getElementById('viewer-canvas');
            var context=canvas.getContext('webgl2')||canvas.getContext('webgl');
            return canvas===window.__nativeAssetNavigationCanvas&&context===window.__nativeAssetNavigationContext&&!context.isContextLost();
            """)
        try require(retainedContext as? Bool == true, "Native navigation must preserve the live canvas and WebGL context.")
        try require(model.assetWebView === webView, "Native section changes must not replace the editor session.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        report["asset_navigation"] = ["same_webview": true, "same_canvas_and_context": true,
            "unsaved_node_mesh_edits_preserved": true, "page_change_selected_viewer": true,
            "late_ready_preserved_native_destination": true]
        try checkpoint("native-asset-navigation-preserved")
    }

    private func requireEditingSnapshot(_ actual: [String: Any], matches expected: [String: Any], invalidDraft: Bool = false) throws {
        for key in ["modelId", "loadedPaths", "authoringEdits", "camera", "rig", "persistence"] + (invalidDraft ? [] : ["authoring"]) {
            guard let current = actual[key] as? String, let retained = expected[key] as? String else { throw NativeError.invalidResponse }
            try require(current == retained, "Independent panel operations must preserve the actual editing state: " + key)
        }
        guard let expression = actual["expressionOpen"] as? Bool, let retainedExpression = expected["expressionOpen"] as? Bool else { throw NativeError.invalidResponse }
        try require(expression == retainedExpression, "Pose/body toggles must preserve the independent expression panel.")
        if !invalidDraft {
            guard let enabled = actual["saveEnabled"] as? Bool, let retainedEnabled = expected["saveEnabled"] as? Bool else { throw NativeError.invalidResponse }
            try require(enabled == retainedEnabled, "Panel collapse must preserve Save availability.")
        }
    }

    private func togglePoseBodyPanel(_ webView: WKWebView, body: Bool) async throws -> [String: Any] {
        try await object(webView, """
            var panel=document.getElementById('\(body ? "viewer-body-adjustments" : "viewer-adjustments")'),summary=panel.querySelector('summary');
            summary.scrollIntoView({block:'nearest'});
            await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var rect=summary.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
            if(rect.width<34||rect.height<34||!(hit===summary||summary.contains(hit)))throw new Error('The real panel summary must be a visible native WebKit target');
            summary.click();await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var style=getComputedStyle(panel);
            return JSON.stringify({poseOpen:document.getElementById('viewer-adjustments').open,
              bodyOpen:document.getElementById('viewer-body-adjustments').open,
              expressionOpen:document.getElementById('viewer-expression-adjustments').open,panelOpen:panel.open,
              summaryTarget:{width:rect.width,height:rect.height,hittable:true},sectionHeight:panel.getBoundingClientRect().height,
              summaryHeight:summary.getBoundingClientRect().height,
              chromeHeight:parseFloat(style.paddingTop)+parseFloat(style.paddingBottom)+parseFloat(style.borderTopWidth)+parseFloat(style.borderBottomWidth)});
            """)
    }

    private func checkSeparatePoseBodyPanels(_ webView: WKWebView) async throws {
        let before = try await editingSnapshot(webView)
        try require(before["saveEnabled"] as? Bool == true, "The two real edits must be ready before testing independent panels.")
        var observations: [[String: Any]] = []
        for body in [false, false, true, true] {
            let observation = try await togglePoseBodyPanel(webView, body: body)
            let opening = observations.count % 2 == 1
            try require(observation[body ? "bodyOpen" : "poseOpen"] as? Bool == opening &&
                        observation[body ? "poseOpen" : "bodyOpen"] as? Bool == true,
                        "Toggling one panel must preserve the other open panel.")
            if !opening {
                let summary = observation["summaryHeight"] as? Double ?? -1
                let chrome = observation["chromeHeight"] as? Double ?? -1
                try require(abs((observation["sectionHeight"] as? Double ?? -100) - summary - chrome) <= 1,
                            "A collapsed native details panel must occupy only its summary and chrome.")
            }
            try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
            observations.append(observation)
        }
        report["separate_pose_body_panels"] = ["status": "PASS", "before": before, "toggles": observations,
            "both_restored_open": true, "model_camera_recipe_and_save_preserved": true,
            "scope": "Actual native WebKit details summaries and preserved paused fixture state; no motion playback claim"]
        try checkpoint("separate-pose-body-panels")
    }

    private func checkInvalidBodyDraftMenuSave(_ webView: WKWebView) async throws {
        let before = try await editingSnapshot(webView)
        let originalVertices = try await vertices(webView)
        _ = try await togglePoseBodyPanel(webView, body: false)
        let draft = try await object(webView, """
            var field=document.querySelector('#viewer-node-fields input[data-viewer-node-kind="scale"][data-axis="X"]');
            for(var parent=field;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
            field.scrollIntoView({block:'center'});field.focus();var previous=field.value;
            await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            var rect=field.getBoundingClientRect(),hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
            if(field.disabled||rect.width<34||rect.height<34||hit!==field)throw new Error('The open body panel must keep its real editable field usable while pose is collapsed');
            field.value='0';field.dispatchEvent(new Event('input',{bubbles:true}));
            return JSON.stringify({previous:previous,raw:field.value,focused:document.activeElement===field,
              poseOpen:document.getElementById('viewer-adjustments').open,bodyOpen:document.getElementById('viewer-body-adjustments').open,
              invalid:field.validity.customError&&field.getAttribute('aria-invalid')==='true',
              saveDisabled:document.getElementById('viewer-save').disabled,unsupported:ModelViewer.getAuthoringState().unsupported});
            """)
        report["invalid_body_draft_before_menu_save"] = draft
        try checkpoint("invalid-body-draft-ready")
        try require(draft["raw"] as? String == "0" && draft["focused"] as? Bool == true &&
                    draft["invalid"] as? Bool == true && draft["saveDisabled"] as? Bool == true &&
                    draft["poseOpen"] as? Bool == false && draft["bodyOpen"] as? Bool == true &&
                    !(draft["unsupported"] as? [String] ?? []).isEmpty,
                    "A focused invalid body draft must block Save while pose is collapsed.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before, invalidDraft: true)
        model.perform("saveModel")
        // The native dispatch is intentionally fire-and-forget. An acknowledged
        // call to the same production command also proves its guard ran, rather
        // than treating a delayed or absent native dispatch as a passing no-op.
        let acknowledged = try await js(webView, "return ElichikaPlatform.perform('saveModel');")
        try require(acknowledged as? Bool == true, "The real production Save command must handle the invalid draft.")
        try await Task.sleep(nanoseconds: 250_000_000)
        let after = try await object(webView, """
            var field=document.querySelector('#viewer-node-fields input[data-viewer-node-kind="scale"][data-axis="X"]');
            return JSON.stringify({raw:field.value,focused:document.activeElement===field,invalid:field.validity.customError,
              poseOpen:document.getElementById('viewer-adjustments').open,bodyOpen:document.getElementById('viewer-body-adjustments').open,
              saveDisabled:document.getElementById('viewer-save').disabled,unsupported:ModelViewer.getAuthoringState().unsupported});
            """)
        report["invalid_body_draft_after_menu_save"] = after
        try checkpoint("invalid-body-draft-menu-save-observed")
        try require(after["raw"] as? String == "0" && after["focused"] as? Bool == true &&
                    after["invalid"] as? Bool == true && after["saveDisabled"] as? Bool == true &&
                    after["poseOpen"] as? Bool == false && after["bodyOpen"] as? Bool == true &&
                    !(after["unsupported"] as? [String] ?? []).isEmpty,
                    "Native menu Save must preserve the invalid draft and refuse to export stale valid values.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before, invalidDraft: true)
        let unchangedVertices = try await vertices(webView)
        try require(try difference(originalVertices, unchangedVertices) < 0.000000001,
                    "An invalid draft must not alter the actual deformed geometry.")
        guard let previous = draft["previous"] as? String else { throw NativeError.invalidResponse }
        let quoted = String(decoding: try JSONSerialization.data(withJSONObject: [previous]), as: UTF8.self) + "[0]"
        _ = try await js(webView, "var field=document.querySelector('#viewer-node-fields input[data-viewer-node-kind=\"scale\"][data-axis=\"X\"]');field.value=" + quoted + ";field.dispatchEvent(new Event('input',{bubbles:true}));field.blur();return true;")
        let restored = try await togglePoseBodyPanel(webView, body: false)
        try require(restored["poseOpen"] as? Bool == true && restored["bodyOpen"] as? Bool == true,
                    "Both independent panels must be restored before the real export.")
        try requireEditingSnapshot(try await editingSnapshot(webView), matches: before)
        let focused = try await js(webView, "var field=document.querySelector('#viewer-node-fields input[data-viewer-node-kind=\"scale\"][data-axis=\"X\"]');field.focus();return document.activeElement===field;")
        try require(focused as? Bool == true, "The valid body draft must remain focused before native menu export.")
        report["invalid_body_draft_native_menu_save"] = ["status": "PASS", "no_export_started": true,
            "invalid_raw_draft_preserved": true, "valid_draft_restored": true, "pose_and_body_restored_open": true,
            "valid_body_field_focused_before_real_export": true, "production_command_acknowledged": true,
            "scope": "Native dispatch plus acknowledged production-command guard; the following valid native export verifies native delivery"]
        try checkpoint("invalid-body-draft-restored")
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

    private func checkOfflineManagement(_ directory: URL) async throws {
        try checkpoint("offline-management-pages")
        let previous = model.selectedSection
        defer { model.selectedSection = previous }
        await model.refresh()
        try require(!model.snapshot.serverRunning, "Management must prepare while the game server remains stopped.")
        model.selectedSection = .serverSettings
        model.retryManagement()
        try await wait("the local management service", timeout: 120) {
            await self.model.refresh()
            return !self.model.snapshot.serverRunning && self.model.snapshot.management?.running == true && self.model.snapshot.management?.httpReady == true
        }
        guard let pid = model.snapshot.management?.pid, pid > 0 else { throw NativeError.invalidResponse }
        let pages: [(BrowserRoute, AppSection, String, String)] = [
            (.serverSettings, .serverSettings, "/webui/admin/", "offline-management-settings.png"),
            (.accounts, .accounts, "/webui/user/", "offline-management-user.png")]
        var observed: [[String: Any]] = []
        for (route, section, path, filename) in pages {
            guard let endpoint = model.goEndpoint(path: path), endpoint.localWebUIToken != nil,
                  let origin = TrustedOrigin(endpoint.url) else { throw NativeError.invalidResponse }
            let (_, response) = try await URLSession.shared.data(for: endpoint.initialRequest)
            try require((response as? HTTPURLResponse)?.statusCode == 200,
                        "The real management page must respond while the game server is stopped.")
            model.selectedSection = section
            let webView = model.browser(route).webView
            try await wait("the attached native management page", timeout: 20) { webView.window != nil }
            try await waitJS(webView, "the management document", timeout: 30, expression:
                "document.readyState==='complete'&&location.pathname.indexOf('/webui/')===0&&!!document.body&&document.body.innerText.trim().length>20&&document.body.dataset.elichikaLocalAccess==='true'")
            guard let actualURL = webView.url else { throw NativeError.invalidResponse }
            try require(origin.contains(actualURL) && !model.snapshot.serverRunning,
                        "Native management navigation must stay on the ready loopback origin and leave the game server stopped.")
            let page = try await object(webView,
                "return JSON.stringify({url:location.href,title:document.title,bodyCharacters:document.body.innerText.trim().length,localAccess:document.body.dataset.elichikaLocalAccess==='true',passwordPrompt:Array.from(document.querySelectorAll('#admin_password,#user_password')).some(x=>x.getClientRects().length>0)});")
            try require(page["localAccess"] as? Bool == true && page["passwordPrompt"] as? Bool == false,
                        "App-owned management must open authorized server settings and the account picker without a password prompt.")
            try await snapshot(webView, directory.appendingPathComponent(filename))
            observed.append(["requested_path": path, "http_status": 200, "document": page, "screenshot": filename])
        }
        let settings = model.browser(.serverSettings)
        let accounts = model.browser(.accounts)
        guard let originalOrigin = model.goURL(path: "/webui/admin/") else { throw NativeError.invalidResponse }
        let managementPages = [settings.webView, accounts.webView]
        _ = try await js(settings.webView, "location.assign('/webui/admin/config_editor');return true;")
        try await waitJS(settings.webView, "the authorized server config form", timeout: 30, expression:
            "document.readyState==='complete'&&document.body.dataset.elichikaLocalAccess==='true'&&!!document.querySelector('#config_form [name=CdnServer]')")
        // An unsent form draft exercises actual document preservation, beyond
        // merely reusing a WKWebView with a newly loaded login page.
        for (index, webView) in managementPages.enumerated() {
            let selector = index == 0 ? "#config_form [name=CdnServer]" : "#native-account-filter"
            let prepared = try await js(webView, """
                var field=document.querySelector('\(selector):not([disabled]):not([readonly])');
                if(!field)return false;
                window.elichikaNavigationDraft={field:field,previous:field.value};
                field.value='Elichika unsaved navigation draft';field.dispatchEvent(new Event('input',{bubbles:true}));
                return field.value==='Elichika unsaved navigation draft';
                """)
            try require(prepared as? Bool == true, "Each management page must contain a real editable form draft before navigation.")
        }
        let stopRequests = stages.filter { $0["stage"] as? String == "management-demand-stop-requested" }.count
        for destination in [AppSection.viewer, .content, .server, .settings] {
            model.selectedSection = destination
            // Let SwiftUI detach the hidden page, then exercise the ordinary
            // state refresh that previously stopped and destroyed its session.
            try await Task.sleep(nanoseconds: 250_000_000)
            await model.refresh()
            try require(model.snapshot.management?.pid == pid && model.snapshot.management?.httpReady == true
                        && model.goURL(path: "/webui/admin/") == originalOrigin && !model.snapshot.serverRunning,
                        "Visiting another menu must retain the same ready management process and origin.")
            for (route, section, _, _) in pages {
                model.selectedSection = section
                model.retryManagement()
                let session = model.browser(route)
                try require(session === (route == .serverSettings ? settings : accounts),
                            "Returning to management must retain its original browser session.")
                try await wait("the reattached management form", timeout: 20) { session.webView.window != nil }
                let preserved = try await js(session.webView,
                    "return !!window.elichikaNavigationDraft&&window.elichikaNavigationDraft.field.isConnected&&window.elichikaNavigationDraft.field.value==='Elichika unsaved navigation draft';")
                try require(preserved as? Bool == true,
                            "Returning from another menu must retain the unsent form in the original document.")
            }
        }
        for webView in managementPages {
            _ = try await js(webView, "var saved=window.elichikaNavigationDraft;if(saved){saved.field.value=saved.previous;saved.field.dispatchEvent(new Event('input',{bubbles:true}));delete window.elichikaNavigationDraft;}return true;")
        }
        model.selectedSection = previous
        await model.refresh()
        try require(model.snapshot.management?.pid == pid && model.snapshot.management?.httpReady == true
                    && model.managementSessionWanted && !model.snapshot.serverRunning,
                    "The management session must stay ready after returning to editing; the game server stays stopped.")
        try require(stages.filter { $0["stage"] as? String == "management-demand-stop-requested" }.count == stopRequests,
                    "Menu navigation must not request a management shutdown.")
        report["native_offline_management"] = ["status": "PASS", "server_stayed_stopped": true,
            "management_pid": pid, "management_pid_after_navigation": pid, "pages": observed,
            "session_retained_while_editing": true, "fast_navigation_cycles": 4,
            "browser_sessions_preserved": true, "unsaved_form_drafts_preserved": true,
            "app_owned_access_without_password_prompt": true,
            "origin_unchanged": true, "navigation_shutdown_requests": 0,
            "scope": "Actual native Server settings/Accounts WebViews, authorized with the app-owned capability, and the same real loopback Go management process across menu round trips; no game server or account mutation requested"]
        try checkpoint("offline-management-pages-passed")
    }

    private func checkConsoleActions(_ directory: URL) async throws {
        try checkpoint("native-console-actions")
        let previousSection = model.selectedSection
        defer { model.dismissConsolePresentation(); model.selectedSection = previousSection }
        func readConsole() async throws -> ConsoleState {
            try JSONDecoder().decode(ConsoleState.self, from: await model.request("/v1/console"))
        }
        let before = try await readConsole()
        guard let originalCache = before.cacheEnabled else { throw NativeError.invalidResponse }
        let originalJob = before.job?.id
        let configURL = model.dataDirectory.appendingPathComponent("config.json")
        let originalConfigData = try Data(contentsOf: configURL)
        let originalConfig = try JSONSerialization.jsonObject(with: originalConfigData) as? [String: Any] ?? [:]
        var refused: [String] = []
        for action in ["runShell", "reset_server"] {
            var denied = false
            do { _ = try await model.request("/v1/console/run", method: "POST", body: ["action": action]) }
            catch { denied = true; refused.append(action) }
            try require(denied, "The real Console API must reject an unknown action and unconfirmed reset.")
        }
        try require(try Data(contentsOf: configURL) == originalConfigData,
                    "Rejected Console actions must not change the private configuration.")
        try await wait("the attached asset window before switching to Console", timeout: 20) {
            self.model.assetWebView?.window?.contentView != nil
        }
        guard let window = model.assetWebView?.window, let content = window.contentView else {
            throw NativeError.service("The native Console capture requires the existing application window attached to the asset WebView.")
        }
        model.selectedSection = .server
        NSApplication.shared.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        try await wait("the actual Console window and laid-out content before capture", timeout: 10) {
            self.model.selectedSection == .server && NSApplication.shared.isActive && window.isVisible && window.isKeyWindow &&
                NSApplication.shared.keyWindow === window && content.window === window &&
                !content.isHiddenOrHasHiddenAncestor && content.bounds.width > 0 && content.bounds.height > 0 &&
                self.consoleMarker(in: content, window: window) != nil && self.model.assetWebView?.window !== window
        }
        await Task.yield()
        try await Task.sleep(nanoseconds: 100_000_000)
        content.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        try require(consoleMarker(in: content, window: window) != nil && model.assetWebView?.window !== window,
                    "The actual Console layout must have replaced the asset WebView before capture.")
        report["native_console_capture"] = ["owned_asset_window": true, "window_number": window.windowNumber,
            "app_active": NSApplication.shared.isActive, "window_visible": window.isVisible,
            "window_key": window.isKeyWindow, "content_width": content.bounds.width, "content_height": content.bounds.height,
            "console_render_marker_visible": true, "previous_asset_view_detached": true]
        guard let bitmap = content.bitmapImageRepForCachingDisplay(in: content.bounds) else {
            throw NativeError.service("The actual native Console view must be visible for capture.")
        }
        content.cacheDisplay(in: content.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]), !png.isEmpty else {
            throw NativeError.invalidResponse
        }
        try png.write(to: directory.appendingPathComponent("console-menus.png"), options: .atomic)
        model.presentConsole(.action(.downloadArchive))
        try require(model.consoleRegion == ConsoleRegion.defaultRegion(language: model.language),
                    "The archive picker must default to JP only in Japanese and GL otherwise.")
        try require(model.consolePresentation != nil, "The actual archive action must present its native confirmation.")
        try await Task.sleep(nanoseconds: 150_000_000)
        model.dismissConsolePresentation()
        model.presentConsole(.action(.resetServer))
        let resetSubmitted = await model.confirmConsoleAction()
        try require(!resetSubmitted && model.consoleResetFinal && model.consolePresentation != nil,
                    "The first reset confirmation must only advance to the second native confirmation.")
        model.dismissConsolePresentation()
        for presentation in [ConsolePresentation.guide, .about] {
            model.presentConsole(presentation)
            try require(model.consolePresentation != nil, "Guide and About must open native sheets.")
            try await Task.sleep(nanoseconds: 150_000_000)
            model.dismissConsolePresentation()
        }
        let afterPresentations = try await readConsole()
        try require(afterPresentations.job?.id == originalJob,
                    "Cancelling archive/reset and opening Help must not start any Console operation.")
        var toggles: [[String: Any]] = []
        for expected in [!originalCache, originalCache] {
            try await model.runConsoleAction(.cdnCacheToggle)
            guard let id = model.consoleState?.job?.id else { throw NativeError.invalidResponse }
            try await wait("the private CDN cache operation", timeout: 90) {
                await self.model.refresh()
                return self.model.consoleState?.job?.id == id && self.model.consoleState?.job?.running == false && !self.model.snapshot.busy
            }
            let completed = try await readConsole()
            try require(completed.job?.id == id && completed.job?.status == "done" && completed.cacheEnabled == expected,
                        "The native Console must run the genuine CDN toggle command and persist its setting.")
            toggles.append(["id": id, "status": completed.job?.status ?? "", "cache_enabled": expected])
        }
        let restoredConfig = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any] ?? [:]
        for key in ["server_address", "cdn_server", "cdn_cache_dir", "webui_language", "locales", "admin_password"] {
            if let old = originalConfig[key] as? NSObject {
                try require(old.isEqual(restoredConfig[key]), "The Console cache toggle must preserve other configuration fields.")
            }
        }
        report["native_console_actions"] = ["status": "PASS", "unsafe_requests_rejected": refused,
            "cancelled_presentations_started_no_job": true, "reset_requires_second_confirmation": true,
            "archive_default_region": ConsoleRegion.defaultRegion(language: model.language).rawValue,
            "cache_toggles": toggles, "original_cache_setting_restored": true,
            "other_config_fields_preserved": true, "native_view_screenshot": "console-menus.png",
            "console_render_marker_visible": true, "previous_asset_view_detached": true,
            "scope": "Actual native Console sheets/model actions and authenticated bundled Go CDN command in private smoke data; no archive download or reset executed"]
        try checkpoint("native-console-actions-passed")
    }

    private func checkUnauthorizedControl(_ url: URL) async throws {
        let endpoint = URL(string: "/v1/state", relativeTo: url)!.absoluteURL
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieAcceptPolicy = .never; config.httpShouldSetCookies = false
        let (_, response) = try await URLSession(configuration: config).data(from: endpoint)
        try require([401, 403].contains((response as? HTTPURLResponse)?.statusCode ?? 0), "Control API must refuse unauthenticated requests.")
        report["unauthenticated_control_refused"] = true
    }

    private func consoleMarker(in view: NSView, window: NSWindow) -> NSView? {
        if view.identifier?.rawValue == "elichika.console.rendered", view.window === window,
           !view.isHiddenOrHasHiddenAncestor, view.bounds.width > 0, view.bounds.height > 0 { return view }
        for child in view.subviews {
            if let marker = consoleMarker(in: child, window: window) { return marker }
        }
        return nil
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
        do {
            return try await withCheckedThrowingContinuation { continuation in
                webView.callAsyncJavaScript(source, arguments: [:], in: nil, in: .page) { continuation.resume(with: $0) }
            }
        } catch {
            let failure = error as NSError
            guard let message = failure.userInfo["WKJavaScriptExceptionMessage"] as? String else { throw error }
            let line = failure.userInfo["WKJavaScriptExceptionLineNumber"] as? Int ?? 0
            let column = failure.userInfo["WKJavaScriptExceptionColumnNumber"] as? Int ?? 0
            report["javascript_exception"] = ["message": String(message.prefix(2048)), "line": line, "column": column]
            throw NativeError.service("JavaScript: " + String(message.prefix(2048)) + " (line \(line), column \(column))")
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

    private func loaded(_ webView: WKWebView, reviewing: Bool = false, expectedVertices: Int = 6, expectedTriangles: Int = 4) async throws {
        let review = reviewing ? "&&s.persistence.reviewingSaved" : ""
        try await waitJS(webView, "the actual Unity skin and native framebuffer", timeout: 120, expression:
            "(function(){var s=ModelViewer.getState(),p=s.loaded?ModelViewer.renderProbe(33):{ready:false};return s.loaded&&!s.loading&&!s.contextLost&&s.rig&&s.rig.available&&s.stats.meshes===1&&s.stats.vertices===\(expectedVertices)&&s.stats.triangles===\(expectedTriangles)&&p.ready&&p.glError===0&&p.nonBackgroundSamples>=3&&document.getElementById('viewer-busy').hidden" + review + ";})()")
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

    private func vertices(_ webView: WKWebView, expectedCount: Int = 6) async throws -> [[Double]] {
        let result = try await object(webView, "return JSON.stringify(ViewerRigQa.deformedVertices(\(expectedCount)));")
        guard let values = result["vertices"] as? [[Double]], values.count == expectedCount else { throw NativeError.invalidResponse }
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
