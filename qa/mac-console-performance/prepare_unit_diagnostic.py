import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--evidence',type=pathlib.Path,required=True);p.add_argument('--qa',type=pathlib.Path,required=True);a=p.parse_args()
original_sha='49cacaafaab2beff76efe76ade0a2aac63237c03f1e4e350aa712c6ab9453bc1'
receipt={'status':'QA_ONLY_FACTOR_DIAGNOSTIC_NOT_NEW_PRODUCTION_TEST','source_test_sha256':original_sha,'state_factor':['default','actual-ready-runtime-and-console'],'optimization_factor':['debug','release'],'ready_state_source':'Same source-bound authenticated zero-log Fixture and RuntimeReady as actual native probe; unit calls unmodified AppModel.refresh to obtain RuntimeState, ConsoleState and network presentation. No Go server is claimed.','fixture_driver_sha256':hashlib.sha256((a.qa/'run_performance.py').read_bytes()).hexdigest(),'projection_changes':'Adds environment-selected actual fixture refresh and stdout geometry witnesses only; every v3 assertion and timing remains unchanged.','variants':{}}
helper='''
    @MainActor
    private func qaWitness(_ phase: String, stateCase: String, model: AppModel, text: NSTextView,
                           scroll: NSScrollView, value: (character: Int, offset: CGFloat, line: String),
                           head: Int, pixelsMatch: Bool? = nil, copiedMatch: Bool? = nil) throws {
        #if DEBUG
        let optimization = "debug"
        #else
        let optimization = "release"
        #endif
        var values: [String: Any] = ["phase": phase, "state_case": stateCase, "optimization": optimization,
            "server_running": model.snapshot.serverRunning, "prepared": model.snapshot.prepared,
            "runtime_phase": model.snapshot.phase, "server_url_row_present": model.snapshot.serverRunning && (model.connectionAddress ?? model.snapshot.server?.url) != nil,
            "has_console_state": model.consoleState != nil, "has_job_row": model.consoleState?.job != nil,
            "cache_enabled": model.consoleState?.cacheEnabled ?? false,
            "cache_value_available": model.consoleState?.cacheEnabled != nil,
            "viewport_width": Double(scroll.contentView.bounds.width), "viewport_height": Double(scroll.contentView.bounds.height),
            "origin_y": Double(scroll.contentView.bounds.origin.y), "document_height": Double(text.bounds.height),
            "visible_character": value.character, "glyph_offset_y": Double(value.offset), "head_utf16": head,
            "selected_location": text.selectedRange().location, "selected_length": text.selectedRange().length,
            "line_prefix": String(value.line.prefix(40)), "text_utf16": (text.string as NSString).length,
            "tail_at_bottom": scroll.contentView.bounds.maxY >= text.bounds.maxY - 20]
        if let pixelsMatch { values["pixels_match_before"] = pixelsMatch }
        if let copiedMatch { values["copied_matches_selection_before"] = copiedMatch }
        let data = try JSONSerialization.data(withJSONObject: values, options: [.sortedKeys])
        print("QA_UNIT_WITNESS " + String(decoding: data, as: UTF8.self))
    }
'''
for label in ['C4-negative','proposed-positive']:
 file=a.build/label/'macos/Tests/ConsoleWrappedScrollTests.swift';raw=file.read_text();assert hashlib.sha256(raw.encode()).hexdigest()==original_sha
 needle='        model.selectedSection = .server\n';assert raw.count(needle)==1
 addition='''        let qaStateCase = ProcessInfo.processInfo.environment["ELICHIKA_QA_UNIT_STATE"] ?? "default"
        XCTAssertTrue(["default", "ready"].contains(qaStateCase))
        if qaStateCase == "ready" {
            let readyPath = try XCTUnwrap(ProcessInfo.processInfo.environment["ELICHIKA_QA_UNIT_READY_FILE"])
            let ready = try JSONDecoder().decode(RuntimeReady.self, from: Data(contentsOf: URL(fileURLWithPath: readyPath)))
            try ready.validate()
            model.connection = ready
            await model.refresh()
            XCTAssertTrue(model.snapshot.serverRunning && model.snapshot.prepared)
            XCTAssertEqual(model.consoleState?.cacheEnabled, false)
            XCTAssertNil(model.consoleState?.job)
        }
'''
 s=raw.replace(needle,needle+addition,1)
 needle='        let beforePixels = try viewportPixels(scroll)\n';assert s.count(needle)==1
 s=s.replace(needle,needle+'        try qaWitness("before", stateCase: qaStateCase, model: model, text: text, scroll: scroll, value: before, head: beforeHead)\n',1)
 needle='        text.copy(nil)\n';assert s.count(needle)==1
 s=s.replace(needle,needle+'''        try qaWitness("after", stateCase: qaStateCase, model: model, text: text, scroll: scroll, value: after,
                      head: model.consoleLogs.snapshot.headUTF16Offset, pixelsMatch: try viewportPixels(scroll) == beforePixels,
                      copiedMatch: NSPasteboard.general.string(forType: .string) == selected)
''',1)
 needle='        XCTAssertGreaterThanOrEqual(scroll.contentView.bounds.maxY, text.bounds.maxY - 20)\n';assert s.count(needle)==1
 s=s.replace(needle,needle+'''        try qaWitness("tail", stateCase: qaStateCase, model: model, text: text, scroll: scroll,
                      value: try anchor(text, scroll), head: model.consoleLogs.snapshot.headUTF16Offset)
''',1)
 position=s.index('\n    @MainActor\n    private func logDocument');s=s[:position]+helper+s[position:]
 file.write_text(s);receipt['variants'][label]={'projected_test_sha256':hashlib.sha256(s.encode()).hexdigest(),'production_app_sha256':hashlib.sha256((a.build/label/'macos/App/ElichikaApp.swift').read_bytes()).hexdigest()}
(a.evidence/'unit-factor-diagnostic-source.json').write_text(json.dumps(receipt,indent=2)+'\n')
