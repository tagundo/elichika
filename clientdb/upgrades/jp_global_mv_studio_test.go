package upgrades

import (
	"path/filepath"
	"testing"
)

// JP's MV Studio stock overrides stay in JP: GL keeps its own stock MVs, packages and bookkeeping,
// and a JP-only MV copied into GL plays its stock timeline. MV-only songs still copy as before.
func TestJapaneseContentKeepsMVStudioStockOverridesRegionLocal(t *testing.T) {
	f := newJapaneseContentFixture(t)
	const override = "abcd1234"
	const onlyOverride = "beef5678"
	const androidPack = "mvstudio_0123456789abcdef_0123456789ab"
	const iosPack = "mvstudio_fedcba9876543210_ba9876543210"
	const onlyPack = "mvstudio_1111111111111111_111111111111"
	const songPack = "mvstudio_2222222222222222_222222222222"
	bookkeeping := `CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, lives TEXT NOT NULL)`
	jp := testDatabase(t, f.jpMaster)
	execTestSQL(t, jp,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL)`,
		// 1203503 is shared with GL; 4200101 is JP-only; 9600001 is a JP MV-only song.
		`INSERT INTO m_live_3d_asset VALUES (1203503, '`+override+`'), (4200101, '`+onlyOverride+`'), (9600001, 'song0001')`,
		bookkeeping,
		`INSERT INTO _elichika_mv_studio_timeline VALUES
			(1203503, 'stock035', '`+override+`', 2, 0, '{"android":["`+androidPack+`",50],"ios":["`+iosPack+`",51]}', '{}', '{}', '{}', '[12035]'),
			(4200101, 'stock042', '`+onlyOverride+`', 1, 0, '{"android":["`+onlyPack+`",60],"ios":null}', '{}', '{}', '{}', '[42001]')`,
	)
	jp.Close()
	gl := testDatabase(t, f.glMaster)
	execTestSQL(t, gl,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL)`,
		`INSERT INTO m_live_3d_asset VALUES (1203503, 'stock035')`,
		bookkeeping,
	)
	gl.Close()
	catalog := []string{
		`CREATE TABLE live_timeline (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL, size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL)`,
		`CREATE TABLE live_timeline_dependency (asset_path TEXT NOT NULL, dependency TEXT NOT NULL, PRIMARY KEY (asset_path, dependency))`,
	}
	for index, path := range f.jpAssets {
		pack := []string{androidPack, iosPack}[index]
		db := testDatabase(t, path)
		execTestSQL(t, db, catalog...)
		execTestSQL(t, db,
			`INSERT INTO live_timeline VALUES ('stock035', 'pack035', 0, 100, 1, 2), ('stock042', 'pack042', 0, 110, 1, 2), ('song0001', '`+songPack+`', 0, 70, 0, 0)`,
			`INSERT INTO live_timeline_dependency VALUES ('stock035', 'chor035'), ('stock042', 'chor042'), ('song0001', 'chor035')`,
			`INSERT INTO m_asset_package VALUES ('live:1203503', 'jp override version', 2), ('live:4200101', 'jp only override version', 2), ('live:9600001', 'jp song version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES ('live:1203503', 'pack035', 100, NULL, 0, 0), ('live:4200101', 'pack042', 110, NULL, 0, 0), ('live:9600001', '`+songPack+`', 70, NULL, 0, 0)`,
			`INSERT INTO m_asset_pack VALUES ('pack035', 1), ('pack042', 1), ('`+songPack+`', 0)`,
			// The override: its key in every catalog (iOS of 4200101 aliases the stock pack), its packs added to live:<asset>.
			`INSERT INTO live_timeline VALUES ('`+override+`', '`+pack+`', 0, 50, 0, 0)`,
			`INSERT INTO live_timeline_dependency VALUES ('`+override+`', 'chor035'), ('`+onlyOverride+`', 'chor042')`,
			`INSERT INTO m_asset_package_mapping VALUES ('live:1203503', '`+pack+`', 50, NULL, 0, 0)`,
			`INSERT INTO m_asset_pack VALUES ('`+pack+`', 0)`,
		)
		if index == 0 {
			execTestSQL(t, db,
				`INSERT INTO live_timeline VALUES ('`+onlyOverride+`', '`+onlyPack+`', 0, 60, 0, 0)`,
				`INSERT INTO m_asset_package_mapping VALUES ('live:4200101', '`+onlyPack+`', 60, NULL, 0, 0)`,
				`INSERT INTO m_asset_pack VALUES ('`+onlyPack+`', 0)`)
		} else {
			execTestSQL(t, db,
				`INSERT INTO live_timeline VALUES ('`+onlyOverride+`', 'pack042', 0, 110, 1, 2)`,
				`UPDATE m_asset_package SET pack_num = 1 WHERE package_key = 'live:4200101'`)
		}
		db.Close()
	}
	for _, path := range f.glAssets {
		db := testDatabase(t, path)
		execTestSQL(t, db, catalog...)
		execTestSQL(t, db,
			`INSERT INTO live_timeline VALUES ('stock035', 'pack035', 0, 100, 1, 2)`,
			`INSERT INTO live_timeline_dependency VALUES ('stock035', 'chor035')`,
			`INSERT INTO m_asset_package VALUES ('live:1203503', 'gl stock version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES ('live:1203503', 'pack035', 100, NULL, 0, 0)`,
			`INSERT INTO m_asset_pack VALUES ('pack035', 1)`,
		)
		db.Close()
	}
	if _, err := JapaneseContent(f.root); err != nil {
		t.Fatal(err)
	}
	assertJapaneseContentRows(t, f.glMaster, `SELECT id, timeline FROM m_live_3d_asset ORDER BY id`, [][]any{
		{int64(1203503), "stock035"}, {int64(4200101), "stock042"}, {int64(9600001), "song0001"},
	})
	assertJapaneseContentRows(t, f.glMaster, `SELECT COUNT(*) FROM _elichika_mv_studio_timeline`, [][]any{{int64(0)}})
	for _, path := range f.glAssets {
		assertJapaneseContentRows(t, path, `SELECT asset_path, pack_name FROM live_timeline ORDER BY asset_path`, [][]any{
			{"song0001", songPack}, {"stock035", "pack035"}, {"stock042", "pack042"},
		})
		assertJapaneseContentRows(t, path, `SELECT asset_path, dependency FROM live_timeline_dependency ORDER BY asset_path`, [][]any{
			{"song0001", "chor035"}, {"stock035", "chor035"}, {"stock042", "chor042"},
		})
		assertJapaneseContentRows(t, path, `SELECT package_key, pack_name FROM m_asset_package_mapping WHERE package_key LIKE 'live:%' ORDER BY package_key, pack_name`, [][]any{
			{"live:1203503", "pack035"}, {"live:4200101", "pack042"}, {"live:9600001", songPack},
		})
		assertJapaneseContentRows(t, path, `SELECT pack_name FROM m_asset_pack WHERE pack_name LIKE 'mvstudio%' ORDER BY pack_name`, [][]any{{songPack}})
		// GL's own stock package is untouched; the JP-only MV's package is recounted without the override.
		assertJapaneseContentRows(t, path, `SELECT version, pack_num FROM m_asset_package WHERE package_key = 'live:1203503'`, [][]any{{"gl stock version", int64(1)}})
		db := testDatabase(t, path)
		var version string
		var count int64
		if err := db.QueryRow(`SELECT version, pack_num FROM m_asset_package WHERE package_key = 'live:4200101'`).Scan(&version, &count); err != nil {
			t.Fatal(err)
		}
		db.Close()
		if count != 1 || version == "jp only override version" {
			t.Fatalf("%s: live:4200101 header (%q, %d) was not recounted without the override", path, version, count)
		}
	}
	// A later start with the same JP databases does nothing more.
	before := japaneseContentSnapshot(t, f.allPaths())
	if report, err := JapaneseContent(f.root); err != nil || report.MasterRows != 0 || report.AssetRows != 0 || report.PackagesUpdated != 0 {
		t.Fatalf("repeat should do no work: report=%+v err=%v", report, err)
	}
	assertJapaneseContentSnapshot(t, before)
}

// A JP masterdata whose MV Studio bookkeeping cannot be read refuses the merge before any write.
func TestJapaneseContentRefusesAnUnreadableStockOverrideRecord(t *testing.T) {
	f := newJapaneseContentFixture(t)
	jp := testDatabase(t, f.jpMaster)
	execTestSQL(t, jp,
		`CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, packs TEXT NOT NULL)`,
		`INSERT INTO _elichika_mv_studio_timeline VALUES (1, 'a', 'b', 'not json')`)
	jp.Close()
	before := japaneseContentSnapshot(t, append(append([]string{f.glMaster}, f.glAssets...), f.glDictionaries...))
	if _, err := JapaneseContent(f.root); err == nil {
		t.Fatal("an unreadable override record must refuse the merge")
	}
	assertJapaneseContentSnapshot(t, before)
}

// A JP override that also swapped the stage (mv_studio_stock "stage"): a JP-only MV the merge copies
// into GL gets its stock timeline AND its original stage fields back.
func TestJapaneseContentPutsBackTheStageOfAJPOverride(t *testing.T) {
	dir := t.TempDir()
	jpPath, glPath := filepath.Join(dir, "jp.db"), filepath.Join(dir, "gl.db")
	jp := testDatabase(t, jpPath)
	execTestSQL(t, jp,
		`CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, lives TEXT NOT NULL, source TEXT NOT NULL DEFAULT '{}', stage TEXT NOT NULL DEFAULT '{}', extras TEXT NOT NULL DEFAULT '{}')`,
		`INSERT INTO _elichika_mv_studio_timeline VALUES (4200101, 'stock042', 'beef5678', 1, 0, '{"android":null,"ios":null}', '{}', '{}', '{}', '[]', '{"assetId":4200103,"stockKey":"stock043"}', '{"original":{"live_stage_master_id":101,"stage_effect_asset_path":"E101","live_prop_skeleton_asset_path":null,"quality_setitng_set_id":1,"shader_variant_asset_path":null}}', '{}')`)
	jp.Close()
	overrides, err := readJPGlobalOverrides(jpPath)
	if err != nil || len(overrides.items) != 1 {
		t.Fatalf("overrides=%+v err=%v", overrides, err)
	}
	gl := testDatabase(t, glPath)
	execTestSQL(t, gl,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL, live_stage_master_id INTEGER NOT NULL, stage_effect_asset_path TEXT NOT NULL, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER NOT NULL, shader_variant_asset_path TEXT)`,
		`INSERT INTO m_live_3d_asset VALUES (4200101, 'beef5678', 202, 'E202', 'P202', 3, 'S202')`)
	var columns []jpGlobalColumn
	for _, name := range []string{"id", "timeline", "live_stage_master_id", "stage_effect_asset_path", "live_prop_skeleton_asset_path", "quality_setitng_set_id", "shader_variant_asset_path"} {
		columns = append(columns, jpGlobalColumn{name: name})
	}
	tx, err := gl.Begin()
	if err != nil {
		t.Fatal(err)
	}
	if err = overrides.restoreStockTimelines(tx, []jpGlobalTable{{name: "m_live_3d_asset", columns: columns}}); err != nil {
		t.Fatal(err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	gl.Close()
	assertJapaneseContentRows(t, glPath, `SELECT * FROM m_live_3d_asset`, [][]any{
		{int64(4200101), "stock042", int64(101), "E101", nil, int64(1), nil},
	})
}
