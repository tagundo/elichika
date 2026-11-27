package upgrades

import "testing"

// A JP cross-slot override (mv_studio_stock "extras") added its source MV's stock packs to
// live:<target>. Those mapping rows stay in JP: GL's live:<target> keeps its own rows and header,
// so GL clients download nothing new, while the packs themselves still come over as the stock
// packs of live:<source>.
func TestJapaneseContentKeepsTheSourcePacksOfAJPCrossSlotOverrideInJP(t *testing.T) {
	f := newJapaneseContentFixture(t)
	const override, onlyOverride = "abcd1234", "beef5678"
	const sourcePack = "srcpack043" // a JP stock pack of live:4200103, the source MV
	overridePacks := []string{"mvstudio_0123456789abcdef_0123456789ab", "mvstudio_fedcba9876543210_ba9876543210"}
	extras := `'{"asset_a_ja":["` + sourcePack + `"],"asset_i_ja":["` + sourcePack + `"]}'`
	jp := testDatabase(t, f.jpMaster)
	execTestSQL(t, jp,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL)`,
		// 1203503 is shared with GL; 4200101 and the source 4200103 are JP-only.
		`INSERT INTO m_live_3d_asset VALUES (1203503, '`+override+`'), (4200101, '`+onlyOverride+`'), (4200103, 'stock043')`,
		`CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, packs TEXT NOT NULL, content TEXT NOT NULL, fingerprints TEXT NOT NULL, packages TEXT NOT NULL, lives TEXT NOT NULL, source TEXT NOT NULL DEFAULT '{}', stage TEXT NOT NULL DEFAULT '{}', extras TEXT NOT NULL DEFAULT '{}')`,
		`INSERT INTO _elichika_mv_studio_timeline VALUES
			(1203503, 'stock035', '`+override+`', 1, 0, '{"android":["`+overridePacks[0]+`",50],"ios":["`+overridePacks[1]+`",51]}', '{}', '{}', '{}', '[12035]', '{"assetId":4200103,"stockKey":"stock043"}', '{}', `+extras+`),
			(4200101, 'stock042', '`+onlyOverride+`', 1, 0, '{"android":null,"ios":null}', '{}', '{}', '{}', '[42001]', '{"assetId":4200103,"stockKey":"stock043"}', '{}', `+extras+`)`,
	)
	jp.Close()
	gl := testDatabase(t, f.glMaster)
	execTestSQL(t, gl,
		`CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL)`,
		`INSERT INTO m_live_3d_asset VALUES (1203503, 'stock035')`)
	gl.Close()
	for index, path := range f.jpAssets {
		pack := overridePacks[index]
		db := testDatabase(t, path)
		execTestSQL(t, db,
			`INSERT INTO m_asset_package VALUES ('live:1203503', 'jp override version', 3), ('live:4200101', 'jp only override version', 2), ('live:4200103', 'jp source version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES
				('live:1203503', 'pack035', 100, NULL, 0, 0), ('live:1203503', '`+pack+`', 50, NULL, 0, 0), ('live:1203503', '`+sourcePack+`', 30, NULL, 0, 5),
				('live:4200101', 'pack042', 110, NULL, 0, 0), ('live:4200101', '`+sourcePack+`', 30, NULL, 0, 5),
				('live:4200103', '`+sourcePack+`', 30, NULL, 0, 5)`,
			`INSERT INTO m_asset_pack VALUES ('pack035', 1), ('pack042', 1), ('`+pack+`', 0), ('`+sourcePack+`', 1)`,
		)
		db.Close()
	}
	for _, path := range f.glAssets {
		db := testDatabase(t, path)
		execTestSQL(t, db,
			`INSERT INTO m_asset_package VALUES ('live:1203503', 'gl stock version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES ('live:1203503', 'pack035', 100, NULL, 0, 0)`,
			`INSERT INTO m_asset_pack VALUES ('pack035', 1)`,
		)
		db.Close()
	}
	if _, err := JapaneseContent(f.root); err != nil {
		t.Fatal(err)
	}
	for _, path := range f.glAssets {
		assertJapaneseContentRows(t, path, `SELECT package_key, pack_name FROM m_asset_package_mapping WHERE package_key LIKE 'live:%' ORDER BY package_key, pack_name`, [][]any{
			{"live:1203503", "pack035"}, {"live:4200101", "pack042"}, {"live:4200103", sourcePack},
		})
		// The source's pack is a JP stock pack (live:4200103 needs it); the override packs stay in JP.
		assertJapaneseContentRows(t, path, `SELECT pack_name FROM m_asset_pack WHERE pack_name IN ('`+sourcePack+`', '`+overridePacks[0]+`', '`+overridePacks[1]+`') ORDER BY pack_name`, [][]any{{sourcePack}})
		// GL's own live:1203503 keeps its header: GL clients get no new version and download nothing.
		assertJapaneseContentRows(t, path, `SELECT version, pack_num FROM m_asset_package WHERE package_key = 'live:1203503'`, [][]any{{"gl stock version", int64(1)}})
		assertJapaneseContentRows(t, path, `SELECT pack_num FROM m_asset_package WHERE package_key IN ('live:4200101', 'live:4200103') ORDER BY package_key`, [][]any{{int64(1)}, {int64(1)}})
	}
}

// An extras value that is not {schema: [pack names]} refuses the merge before any write, like an
// unreadable packs value.
func TestJapaneseContentRefusesUnreadableOverrideExtras(t *testing.T) {
	for _, extras := range []string{`'not json'`, `'{"asset_a_ja":[1]}'`, `'{"asset_a_ja":[""]}'`, `'["x"]'`} {
		f := newJapaneseContentFixture(t)
		jp := testDatabase(t, f.jpMaster)
		execTestSQL(t, jp,
			`CREATE TABLE _elichika_mv_studio_timeline (asset_id INTEGER PRIMARY KEY, stock_key TEXT NOT NULL, timeline_key TEXT NOT NULL, packs TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '{}', extras TEXT NOT NULL DEFAULT '{}')`,
			`INSERT INTO _elichika_mv_studio_timeline VALUES (1, 'a', 'b', '{"android":null,"ios":null}', '{}', `+extras+`)`)
		jp.Close()
		before := japaneseContentSnapshot(t, append(append([]string{f.glMaster}, f.glAssets...), f.glDictionaries...))
		if _, err := JapaneseContent(f.root); err == nil {
			t.Fatalf("extras %s must refuse the merge", extras)
		}
		assertJapaneseContentSnapshot(t, before)
	}
}
