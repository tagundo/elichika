package upgrades

import "testing"

// A stage-only JP override (mv_studio_stock writes timeline_key = stock_key when only the stage
// changes): a JP-only MV the merge copies into GL gets its original stage back, while an MV GL
// already had keeps GL's own row (its stock key matches too, so only "copied from JP" may change).
func TestJapaneseContentPutsBackTheStageOfAStageOnlyJPOverride(t *testing.T) {
	f := newJapaneseContentFixture(t)
	asset := `CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL, live_stage_master_id INTEGER NOT NULL, stage_effect_asset_path TEXT NOT NULL, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER NOT NULL, shader_variant_asset_path TEXT)`
	original := `'{"original":{"live_stage_master_id":101,"stage_effect_asset_path":"E101","live_prop_skeleton_asset_path":null,"quality_setitng_set_id":1,"shader_variant_asset_path":null}}'`
	jp := testDatabase(t, f.jpMaster)
	execTestSQL(t, jp, asset,
		// Both play their stock timeline with a swapped stage: 4200101 is JP-only, 1203503 is shared with GL.
		`INSERT INTO m_live_3d_asset VALUES (4200101, 'stock042', 202, 'E202', 'P202', 3, 'S202'), (1203503, 'stock035', 202, 'E202', 'P202', 3, 'S202')`,
		`CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, lives TEXT NOT NULL, source TEXT NOT NULL DEFAULT '{}', stage TEXT NOT NULL DEFAULT '{}', extras TEXT NOT NULL DEFAULT '{}')`,
		`INSERT INTO _elichika_mv_studio_timeline VALUES
			(4200101, 'stock042', 'stock042', 1, 0, '{"android":null,"ios":null}', '{}', '{}', '{}', '[]', '{}', `+original+`, '{}'),
			(1203503, 'stock035', 'stock035', 1, 0, '{"android":null,"ios":null}', '{}', '{}', '{}', '[]', '{}', `+original+`, '{}')`)
	jp.Close()
	gl := testDatabase(t, f.glMaster)
	execTestSQL(t, gl, asset, `INSERT INTO m_live_3d_asset VALUES (1203503, 'stock035', 105, 'E105', NULL, 2, NULL)`)
	gl.Close()
	if _, err := JapaneseContent(f.root); err != nil {
		t.Fatal(err)
	}
	assertJapaneseContentRows(t, f.glMaster, `SELECT * FROM m_live_3d_asset ORDER BY id`, [][]any{
		{int64(1203503), "stock035", int64(105), "E105", nil, int64(2), nil},
		{int64(4200101), "stock042", int64(101), "E101", nil, int64(1), nil},
	})
}

// restoreStockTimelines itself: a stage-only override puts the stage back on a copied row and
// leaves a row GL had; an override with neither a key of its own nor a stage changes nothing.
func TestRestoreStockTimelinesOfStageOnlyOverrides(t *testing.T) {
	stage := map[string]any{"live_stage_master_id": float64(101), "stage_effect_asset_path": "E101", "live_prop_skeleton_asset_path": nil,
		"quality_setitng_set_id": float64(1), "shader_variant_asset_path": nil}
	overrides := jpGlobalOverrides{items: []jpGlobalOverride{
		{asset: 1, stockKey: "k1", timelineKey: "k1", originalStage: stage},
		{asset: 2, stockKey: "k2", timelineKey: "k2", originalStage: stage},
		{asset: 3, stockKey: "k3", timelineKey: "k3"},
	}}
	db := testDatabase(t, t.TempDir()+"/gl.db")
	execTestSQL(t, db,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL, live_stage_master_id INTEGER NOT NULL, stage_effect_asset_path TEXT NOT NULL, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER NOT NULL, shader_variant_asset_path TEXT)`,
		`INSERT INTO m_live_3d_asset VALUES (1, 'k1', 202, 'E202', 'P202', 3, 'S202'), (2, 'k2', 202, 'E202', 'P202', 3, 'S202'), (3, 'k3', 202, 'E202', 'P202', 3, 'S202')`)
	var columns []jpGlobalColumn
	for _, name := range []string{"id", "timeline", "live_stage_master_id", "stage_effect_asset_path", "live_prop_skeleton_asset_path", "quality_setitng_set_id", "shader_variant_asset_path"} {
		columns = append(columns, jpGlobalColumn{name: name})
	}
	tx, err := db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	if err = overrides.restoreStockTimelines(tx, []jpGlobalTable{{name: "m_live_3d_asset", columns: columns}}, map[int64]bool{2: true}); err != nil {
		t.Fatal(err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	rows, err := db.Query(`SELECT id, timeline, live_stage_master_id, stage_effect_asset_path FROM m_live_3d_asset ORDER BY id`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	want := []struct {
		id       int64
		timeline string
		stage    int64
		effect   string
	}{{1, "k1", 101, "E101"}, {2, "k2", 202, "E202"}, {3, "k3", 202, "E202"}}
	for index := 0; rows.Next(); index++ {
		var id, stageID int64
		var timeline, effect string
		if err = rows.Scan(&id, &timeline, &stageID, &effect); err != nil {
			t.Fatal(err)
		}
		if index >= len(want) || id != want[index].id || timeline != want[index].timeline || stageID != want[index].stage || effect != want[index].effect {
			t.Fatalf("row %d = (%d, %q, %d, %q)", index, id, timeline, stageID, effect)
		}
	}
	db.Close()
}
