package upgrades

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

// The fixtures intentionally contain only a few independent rows. They cover
// an owner's edits and additions as well as JP additions, without shipping or
// modifying any real game database.
type japaneseContentFixture struct {
	root           string
	jpMaster       string
	glMaster       string
	jpAssets       []string
	glAssets       []string
	jpDictionary   string
	glDictionaries []string
}

func newJapaneseContentFixture(t *testing.T) japaneseContentFixture {
	t.Helper()
	name := "owner's assets 日本語 # ? %"
	if runtime.GOOS == "windows" {
		name = "owner's assets 日本語 # %"
	}
	f := japaneseContentFixture{root: filepath.Join(t.TempDir(), name)}
	for _, locale := range []string{"jp", "gl"} {
		if err := os.MkdirAll(filepath.Join(f.root, "db", locale), 0700); err != nil {
			t.Fatal(err)
		}
	}
	f.jpMaster = filepath.Join(f.root, "db", "jp", "masterdata.db")
	f.glMaster = filepath.Join(f.root, "db", "gl", "masterdata.db")
	jp := testDatabase(t, f.jpMaster)
	execTestSQL(t, jp,
		// The initialized game table is an unkeyed weighted rowset. Its rows
		// cannot be matched safely to another server's configured drop rates.
		`CREATE TABLE m_lesson_drop_amount (item_id INTEGER, count INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_drop_amount VALUES (1, 1, 8000), (1, 2, 1500), (1, 3, 500), (2, 1, 10000)`,
		`CREATE TABLE m_content (id INTEGER NOT NULL PRIMARY KEY, name TEXT NOT NULL, payload BLOB, nullable_value TEXT)`,
		`INSERT INTO m_content VALUES (1, 'JP existing name', X'0001FF', 'JP value'), (2, '新しい JP ''quoted'' content', X'00FEFF', NULL)`,
		`CREATE TABLE m_jp_only (id INTEGER PRIMARY KEY, note TEXT)`,
		`INSERT INTO m_jp_only VALUES (1, 'table absent from GL')`,
	)
	jp.Close()
	gl := testDatabase(t, f.glMaster)
	execTestSQL(t, gl,
		`CREATE TABLE m_lesson_drop_amount (item_id INTEGER, count INTEGER, weight INTEGER)`,
		`INSERT INTO m_lesson_drop_amount VALUES (1, 1, 3000), (1, 2, 6000), (1, 5, 1000), (900, 10, 10000)`,
		// A different physical column order catches INSERT ... SELECT * merges.
		`CREATE TABLE m_content (name TEXT NOT NULL, id INTEGER NOT NULL PRIMARY KEY, nullable_value TEXT, payload BLOB)`,
		`INSERT INTO m_content VALUES ('Owner edited existing row', 1, 'custom value', X'AA00'), ('Owner added row', 900, NULL, X'BBFF')`,
		`CREATE TABLE custom_notes (id INTEGER PRIMARY KEY, note TEXT NOT NULL)`,
		`INSERT INTO custom_notes VALUES (1, 'keep custom settings and schema')`,
		`CREATE INDEX custom_content_index ON m_content (name)`,
	)
	gl.Close()
	for _, platform := range []string{"a", "i"} {
		path := filepath.Join(f.root, "db", "jp", "asset_"+platform+"_ja.db")
		f.jpAssets = append(f.jpAssets, path)
		createJapaneseAssetFixture(t, path, true)
		for _, language := range []string{"en", "ko", "zh"} {
			path = filepath.Join(f.root, "db", "gl", "asset_"+platform+"_"+language+".db")
			f.glAssets = append(f.glAssets, path)
			createJapaneseAssetFixture(t, path, false)
		}
	}
	f.jpDictionary = filepath.Join(f.root, "db", "jp", "dictionary_ja_k.db")
	jp = testDatabase(t, f.jpDictionary)
	execTestSQL(t, jp,
		`CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT)`,
		`INSERT INTO m_dictionary VALUES ('accessory_name_33', 'ニジガク帽子'), ('accessory_name_45', 'ローダンセの髪飾り'), ('new_story_key', '新しい日本語 ''quote''`+"\n"+`{0}'), ('existing_custom_key', 'JP baseline')`,
	)
	jp.Close()
	for _, language := range []string{"en", "ko", "zh"} {
		path := filepath.Join(f.root, "db", "gl", "dictionary_"+language+"_k.db")
		f.glDictionaries = append(f.glDictionaries, path)
		gl = testDatabase(t, path)
		execTestSQL(t, gl,
			`CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT, custom_note TEXT DEFAULT 'new default')`,
			`INSERT INTO m_dictionary VALUES ('accessory_name_33', 'ニジガク帽子', 'keep translated metadata'), ('accessory_name_45', 'Owner translation `+language+`', 'keep owner metadata'), ('existing_custom_key', 'Existing `+language+` translation', 'keep existing metadata'), ('owner_only_key', 'Owner-only wording', 'keep owner-only metadata')`,
			`CREATE TABLE custom_dictionary_notes (note TEXT)`,
			`INSERT INTO custom_dictionary_notes VALUES ('keep this unrelated table')`,
		)
		gl.Close()
	}
	return f
}

func createJapaneseAssetFixture(t *testing.T, path string, source bool) {
	t.Helper()
	db := testDatabase(t, path)
	defer db.Close()
	execTestSQL(t, db,
		`CREATE TABLE m_asset_package (package_key TEXT NOT NULL PRIMARY KEY, version TEXT NOT NULL, pack_num INTEGER NOT NULL)`,
		`CREATE TABLE m_asset_package_mapping (package_key TEXT NOT NULL, pack_name TEXT NOT NULL, file_size INTEGER NOT NULL, metapack_name TEXT, metapack_offset INTEGER NOT NULL, category INTEGER NOT NULL, PRIMARY KEY (package_key, pack_name))`,
		`CREATE TABLE m_asset_pack (pack_name TEXT NOT NULL PRIMARY KEY, auto_delete INTEGER NOT NULL)`,
	)
	if source {
		execTestSQL(t, db,
			`INSERT INTO m_asset_package VALUES ('shared', 'jp shared version', 2), ('untouched', 'jp untouched version', 1), ('new', 'jp new version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES ('shared', 'base', 10, NULL, 0, 1), ('shared', 'imported', 20, 'JP pack', 10, 2), ('untouched', 'unchanged', 30, NULL, 0, 3), ('new', 'new', 40, NULL, 0, 4)`,
			`INSERT INTO m_asset_pack VALUES ('base', 1), ('imported', 1), ('unchanged', 1), ('new', 1)`,
		)
	} else {
		execTestSQL(t, db,
			`INSERT INTO m_asset_package VALUES ('shared', 'owner shared version', 2), ('untouched', 'owner untouched version', 1), ('custom', 'owner custom version', 1)`,
			`INSERT INTO m_asset_package_mapping VALUES ('shared', 'base', 999, 'owner pack', 7, 8), ('shared', 'owner', 50, NULL, 0, 5), ('untouched', 'unchanged', 30, NULL, 0, 3), ('custom', 'custom', 60, NULL, 0, 6)`,
			`INSERT INTO m_asset_pack VALUES ('base', 77), ('unchanged', 1), ('owner', 9), ('custom', 9)`,
			`CREATE TABLE custom_asset_notes (note TEXT)`,
			`INSERT INTO custom_asset_notes VALUES ('owner data')`,
		)
	}
}

func (f japaneseContentFixture) allPaths() []string {
	paths := []string{f.jpMaster, f.glMaster, f.jpDictionary}
	paths = append(paths, f.jpAssets...)
	paths = append(paths, f.glAssets...)
	return append(paths, f.glDictionaries...)
}

func japaneseContentSnapshot(t *testing.T, paths []string) map[string][]byte {
	t.Helper()
	result := map[string][]byte{}
	for _, path := range paths {
		result[path] = databaseBytes(t, path)
	}
	return result
}

func assertJapaneseContentSnapshot(t *testing.T, snapshot map[string][]byte) {
	t.Helper()
	for path, want := range snapshot {
		if !bytes.Equal(want, databaseBytes(t, path)) {
			t.Errorf("database changed unexpectedly: %s", path)
		}
	}
}

func assertJapaneseContentRows(t *testing.T, path, query string, want [][]any) {
	t.Helper()
	db := testDatabase(t, path)
	defer db.Close()
	if got := queryTestRows(t, db, query); !reflect.DeepEqual(got, want) {
		t.Fatalf("%s\n%s\ngot %#v\nwant %#v", path, query, got, want)
	}
}

func assertJapaneseContentApplied(t *testing.T, f japaneseContentFixture) {
	t.Helper()
	assertJapaneseContentRows(t, f.glMaster, `SELECT id, name, payload, nullable_value FROM m_content ORDER BY id`, [][]any{
		{int64(1), "Owner edited existing row", []byte{0xaa, 0}, "custom value"},
		{int64(2), "新しい JP 'quoted' content", []byte{0, 0xfe, 0xff}, nil},
		{int64(900), "Owner added row", []byte{0xbb, 0xff}, nil},
	})
	assertJapaneseContentRows(t, f.glMaster, `SELECT item_id, count, weight FROM m_lesson_drop_amount ORDER BY item_id, count`, [][]any{
		{int64(1), int64(1), int64(3000)},
		{int64(1), int64(2), int64(6000)},
		{int64(1), int64(5), int64(1000)},
		{int64(900), int64(10), int64(10000)},
	})
	assertJapaneseContentRows(t, f.glMaster, `SELECT note FROM custom_notes`, [][]any{{"keep custom settings and schema"}})
	assertJapaneseContentRows(t, f.glMaster, `SELECT name FROM sqlite_master WHERE name = 'm_jp_only'`, [][]any{})
	assertJapaneseContentRows(t, f.glMaster, `SELECT name FROM sqlite_master WHERE name = 'custom_content_index'`, [][]any{{"custom_content_index"}})
	for _, path := range f.glAssets {
		assertJapaneseContentRows(t, path, `SELECT package_key, pack_name, file_size, metapack_name, metapack_offset, category FROM m_asset_package_mapping ORDER BY package_key, pack_name`, [][]any{
			{"custom", "custom", int64(60), nil, int64(0), int64(6)},
			{"new", "new", int64(40), nil, int64(0), int64(4)},
			{"shared", "base", int64(999), "owner pack", int64(7), int64(8)},
			{"shared", "imported", int64(20), "JP pack", int64(10), int64(2)},
			{"shared", "owner", int64(50), nil, int64(0), int64(5)},
			{"untouched", "unchanged", int64(30), nil, int64(0), int64(3)},
		})
		assertJapaneseContentRows(t, path, `SELECT pack_name, auto_delete FROM m_asset_pack ORDER BY pack_name`, [][]any{
			{"base", int64(77)}, {"custom", int64(9)}, {"imported", int64(1)}, {"new", int64(1)}, {"owner", int64(9)}, {"unchanged", int64(1)},
		})
		assertJapaneseContentRows(t, path, `SELECT version, pack_num FROM m_asset_package WHERE package_key IN ('custom', 'untouched') ORDER BY package_key`, [][]any{
			{"owner custom version", int64(1)}, {"owner untouched version", int64(1)},
		})
		db := testDatabase(t, path)
		for key, count := range map[string]int64{"shared": 3, "new": 1} {
			var version string
			var packCount int64
			if err := db.QueryRow(`SELECT version, pack_num FROM m_asset_package WHERE package_key = ?`, key).Scan(&version, &packCount); err != nil {
				t.Fatal(err)
			}
			if version == "" || version == "owner shared version" || version == "jp new version" || version == "jp shared version" || packCount != count {
				t.Errorf("package %s was not invalidated with its actual mapping count: version=%q pack_num=%d", key, version, packCount)
			}
		}
		db.Close()
		assertJapaneseContentRows(t, path, `SELECT note FROM custom_asset_notes`, [][]any{{"owner data"}})
	}
	for i, language := range []string{"en", "ko", "zh"} {
		translation := []string{"Nijigaku Cap", "니지가쿠 모자", "虹咲帽子"}[i]
		assertJapaneseContentRows(t, f.glDictionaries[i], `SELECT id, message, custom_note FROM m_dictionary ORDER BY id`, [][]any{
			{"accessory_name_33", translation, "keep translated metadata"},
			{"accessory_name_45", "Owner translation " + language, "keep owner metadata"},
			{"existing_custom_key", "Existing " + language + " translation", "keep existing metadata"},
			{"new_story_key", "新しい日本語 'quote'\n{0}", "new default"},
			{"owner_only_key", "Owner-only wording", "keep owner-only metadata"},
		})
		assertJapaneseContentRows(t, f.glDictionaries[i], `SELECT note FROM custom_dictionary_notes`, [][]any{{"keep this unrelated table"}})
	}
}

func TestJapaneseContentImportsMissingRowsAndPreservesCustomizations(t *testing.T) {
	f := newJapaneseContentFixture(t)
	sources := append([]string{f.jpMaster, f.jpDictionary}, f.jpAssets...)
	beforeSources := japaneseContentSnapshot(t, sources)
	report, err := JapaneseContent(f.root)
	if err != nil || report.SkippedReason != "" || report.MasterRows != 1 || report.AssetRows != 30 || report.DictionaryRows != 6 || report.PackagesUpdated != 12 {
		t.Fatalf("upgrade counts: report=%+v err=%v", report, err)
	}
	assertJapaneseContentApplied(t, f)
	assertJapaneseContentSnapshot(t, beforeSources)
	beforeRepeat := japaneseContentSnapshot(t, f.allPaths())
	report, err = JapaneseContent(f.root)
	if err != nil || report.MasterRows != 0 || report.AssetRows != 0 || report.DictionaryRows != 0 || report.PackagesUpdated != 0 {
		t.Fatalf("repeat should do no work: report=%+v err=%v", report, err)
	}
	assertJapaneseContentSnapshot(t, beforeRepeat)
}

func TestJapaneseContentSuitTitlesFollowMemberNameReferencesAndPreserveCustomTitles(t *testing.T) {
	f := newJapaneseContentFixture(t)
	db := testDatabase(t, f.jpMaster)
	execTestSQL(t, db,
		`CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT)`,
		`CREATE TABLE m_member (id INTEGER PRIMARY KEY, name TEXT)`,
		// These original references are correct: member IDs and name-key
		// suffixes are independent. Owner 211 is Mia through name key 212.
		`INSERT INTO m_member VALUES (211, 'k.m_dic_member_name_212'), (212, 'k.m_dic_member_name_211')`,
		`INSERT INTO m_suit VALUES (321107, 211, 'k.suit_name_321207'), (321207, 212, 'k.suit_name_321107')`,
	)
	db.Close()
	db = testDatabase(t, f.glMaster)
	execTestSQL(t, db,
		`CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT)`,
		`CREATE TABLE m_member (id INTEGER PRIMARY KEY, name TEXT)`,
		`INSERT INTO m_member VALUES (211, 'k.m_dic_member_name_212'), (212, 'k.m_dic_member_name_211')`,
	)
	db.Close()
	db = testDatabase(t, f.jpDictionary)
	execTestSQL(t, db,
		`INSERT INTO m_dictionary VALUES ('m_dic_member_name_211', 'ショウ・ランジュ'), ('m_dic_member_name_212', 'ミア・テイラー'), ('suit_name_321207', 'ODAIBAゲーマーズ Tシャツ ミア・テイラー'), ('suit_name_321107', 'ODAIBAゲーマーズ Tシャツ ショウ・ランジュ')`,
	)
	db.Close()
	locales := []struct{ prefix, lanzhu, mia string }{
		{"ODAIBA Gamers T-Shirt", "Lanzhu Zhong", "Mia Taylor"},
		{"오다이바 게이머즈 T셔츠", "쇼우 란쥬", "미아 테일러"},
		{"ODAIBA Gamers T恤", "鐘嵐珠", "米雅・泰勒"},
	}
	for i, locale := range locales {
		db = testDatabase(t, f.glDictionaries[i])
		for key, message := range map[string]string{
			"m_dic_member_name_211": locale.lanzhu,
			"m_dic_member_name_212": locale.mia,
			// Reproduce the exact previously generated wrong owner-211 title;
			// leave owner 212 absent to also cover the initial localization.
			"suit_name_321207": locale.prefix + " " + locale.lanzhu,
		} {
			if _, err := db.Exec(`INSERT INTO m_dictionary (id, message) VALUES (?, ?)`, key, message); err != nil {
				t.Fatal(err)
			}
		}
		db.Close()
	}
	beforeSources := japaneseContentSnapshot(t, append([]string{f.jpMaster, f.jpDictionary}, f.jpAssets...))
	assertTitles := func() {
		t.Helper()
		for i, locale := range locales {
			assertJapaneseContentRows(t, f.glDictionaries[i], `SELECT id, message FROM m_dictionary WHERE id LIKE 'suit_name_%' ORDER BY id`, [][]any{
				{"suit_name_321107", locale.prefix + " " + locale.lanzhu},
				{"suit_name_321207", locale.prefix + " " + locale.mia},
			})
		}
	}
	report, err := JapaneseContent(f.root)
	if err != nil || report.DictionaryRows != 12 {
		t.Fatalf("initial suit names and known wrong titles: report=%+v err=%v", report, err)
	}
	assertTitles()
	assertJapaneseContentSnapshot(t, beforeSources)
	assertJapaneseContentRows(t, f.glMaster, `SELECT s.id, s.member_m_id, s.name, m.name FROM m_suit s JOIN m_member m ON m.id = s.member_m_id ORDER BY s.id`, [][]any{
		{int64(321107), int64(211), "k.suit_name_321207", "k.m_dic_member_name_212"},
		{int64(321207), int64(212), "k.suit_name_321107", "k.m_dic_member_name_211"},
	})
	// An already migrated database can also contain the reverse legacy title.
	for i, locale := range locales {
		db = testDatabase(t, f.glDictionaries[i])
		if _, err := db.Exec(`UPDATE m_dictionary SET message = ? WHERE id = 'suit_name_321107'`, locale.prefix+" "+locale.mia); err != nil {
			t.Fatal(err)
		}
		db.Close()
	}
	report, err = JapaneseContent(f.root)
	if err != nil || report.DictionaryRows != 3 || report.MasterRows != 0 || report.AssetRows != 0 || report.PackagesUpdated != 0 {
		t.Fatalf("repair reverse legacy title after migration: report=%+v err=%v", report, err)
	}
	assertTitles()
	assertJapaneseContentSnapshot(t, beforeSources)
	for i, path := range f.glDictionaries {
		db = testDatabase(t, path)
		if _, err := db.Exec(`UPDATE m_dictionary SET message = ? WHERE id LIKE 'suit_name_%'`, "Owner's custom suit title {0} "+locales[i].mia); err != nil {
			t.Fatal(err)
		}
		db.Close()
	}
	beforeCustom := japaneseContentSnapshot(t, f.allPaths())
	report, err = JapaneseContent(f.root)
	if err != nil || report.DictionaryRows != 0 || report.MasterRows != 0 || report.AssetRows != 0 || report.PackagesUpdated != 0 {
		t.Fatalf("custom titles should remain unchanged: report=%+v err=%v", report, err)
	}
	assertJapaneseContentSnapshot(t, beforeCustom)
}

func TestJapaneseContentSuitTitlesHonorGlobalMemberNameReference(t *testing.T) {
	f := newJapaneseContentFixture(t)
	db := testDatabase(t, f.jpMaster)
	execTestSQL(t, db,
		`CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT)`,
		`CREATE TABLE m_member (id INTEGER PRIMARY KEY, name TEXT)`,
		`INSERT INTO m_member VALUES (211, 'k.m_dic_member_name_212')`,
		`INSERT INTO m_suit VALUES (321107, 211, 'k.suit_name_321207')`,
	)
	db.Close()
	db = testDatabase(t, f.glMaster)
	execTestSQL(t, db,
		`CREATE TABLE m_member (id INTEGER PRIMARY KEY, name TEXT)`,
		`INSERT INTO m_member VALUES (211, 'k.owner_member_name')`,
	)
	db.Close()
	db = testDatabase(t, f.jpDictionary)
	execTestSQL(t, db,
		`INSERT INTO m_dictionary VALUES ('m_dic_member_name_211', 'ショウ・ランジュ'), ('m_dic_member_name_212', 'ミア・テイラー'), ('suit_name_321207', 'ODAIBAゲーマーズ Tシャツ ミア・テイラー')`,
	)
	db.Close()
	for i, language := range []string{"en", "ko", "zh"} {
		db = testDatabase(t, f.glDictionaries[i])
		if _, err := db.Exec(`INSERT INTO m_dictionary (id,message) VALUES ('owner_member_name', ?)`, "Owner's chosen member name "+language); err != nil {
			t.Fatal(err)
		}
		db.Close()
	}
	if _, err := JapaneseContent(f.root); err != nil {
		t.Fatal(err)
	}
	for i, prefix := range []string{"ODAIBA Gamers T-Shirt", "오다이바 게이머즈 T셔츠", "ODAIBA Gamers T恤"} {
		assertJapaneseContentRows(t, f.glDictionaries[i], `SELECT message FROM m_dictionary WHERE id='suit_name_321207'`, [][]any{
			{prefix + " Owner's chosen member name " + []string{"en", "ko", "zh"}[i]},
		})
	}
	assertJapaneseContentRows(t, f.glMaster, `SELECT name FROM m_member WHERE id=211`, [][]any{{"k.owner_member_name"}})
}

func TestJapaneseContentRejectsDictionarySourceAliasesBeforeMutation(t *testing.T) {
	for _, link := range []struct {
		name   string
		create func(string, string) error
	}{{"hardlink", os.Link}, {"symlink", os.Symlink}} {
		t.Run(link.name, func(t *testing.T) {
			f := newJapaneseContentFixture(t)
			target := f.glDictionaries[0]
			if err := os.Remove(target); err != nil {
				t.Fatal(err)
			}
			if err := link.create(f.jpDictionary, target); err != nil {
				t.Skipf("%s unavailable: %v", link.name, err)
			}
			before := japaneseContentSnapshot(t, f.allPaths())
			_, err := JapaneseContent(f.root)
			if err == nil || !strings.Contains(err.Error(), "JP source and GL target must be different files") {
				t.Errorf("expected dictionary source alias rejection, got %v", err)
			}
			assertJapaneseContentSnapshot(t, before)
		})
	}
}

func TestJapaneseContentPreflightsAllDatabasesBeforeMutation(t *testing.T) {
	for _, problem := range []string{"late asset schema mismatch", "late dictionary schema mismatch", "missing target", "missing source"} {
		t.Run(problem, func(t *testing.T) {
			f := newJapaneseContentFixture(t)
			var missing string
			switch problem {
			case "late asset schema mismatch":
				db := testDatabase(t, f.glAssets[len(f.glAssets)-1])
				execTestSQL(t, db, `ALTER TABLE m_asset_pack ADD COLUMN incompatible TEXT`)
				db.Close()
			case "late dictionary schema mismatch":
				db := testDatabase(t, f.glDictionaries[2])
				execTestSQL(t, db, `ALTER TABLE m_dictionary RENAME COLUMN message TO incompatible_message`)
				db.Close()
			case "missing target":
				missing = f.glAssets[len(f.glAssets)-1]
			case "missing source":
				missing = f.jpAssets[len(f.jpAssets)-1]
			}
			paths := f.allPaths()
			if missing != "" {
				if err := os.Remove(missing); err != nil {
					t.Fatal(err)
				}
				for i, path := range paths {
					if path == missing {
						paths = append(paths[:i], paths[i+1:]...)
						break
					}
				}
			}
			before := japaneseContentSnapshot(t, paths)
			report, err := JapaneseContent(f.root)
			if missing == "" && err == nil {
				t.Fatalf("schema mismatch should fail preflight: report=%+v", report)
			}
			if missing != "" && (err != nil || report.SkippedReason == "") {
				t.Fatalf("incomplete assets should report a skip: report=%+v err=%v", report, err)
			}
			if report.MasterRows != 0 || report.AssetRows != 0 || report.DictionaryRows != 0 || report.PackagesUpdated != 0 {
				t.Fatalf("preflight should not commit work: %+v", report)
			}
			assertJapaneseContentSnapshot(t, before)
			if missing != "" {
				if _, err := os.Stat(missing); !os.IsNotExist(err) {
					t.Fatalf("preflight created missing SQLite file: %s: %v", missing, err)
				}
			}
		})
	}
}

func TestJapaneseContentRollsBackOneDatabaseAndResumesAfterFailure(t *testing.T) {
	f := newJapaneseContentFixture(t)
	failedPath := f.glAssets[0]
	db := testDatabase(t, failedPath)
	execTestSQL(t, db, `CREATE TRIGGER reject_import BEFORE INSERT ON m_asset_package_mapping WHEN NEW.pack_name = 'imported' BEGIN SELECT RAISE(ABORT, 'injected content import failure'); END`)
	db.Close()
	beforeFailed := databaseBytes(t, failedPath)
	report, err := JapaneseContent(f.root)
	if err == nil || !strings.Contains(err.Error(), "injected content import failure") {
		t.Fatalf("expected a real mid-transaction failure: report=%+v err=%v", report, err)
	}
	if !bytes.Equal(beforeFailed, databaseBytes(t, failedPath)) {
		t.Fatal("failed asset transaction committed partial rows, package versions, or marker")
	}
	// Earlier DB commits are durable; restarting must retain them and finish the
	// remaining DBs without importing or counting the master row twice.
	assertJapaneseContentRows(t, f.glMaster, `SELECT id FROM m_content WHERE id = 2`, [][]any{{int64(2)}})
	db = testDatabase(t, failedPath)
	execTestSQL(t, db, `DROP TRIGGER reject_import`)
	db.Close()
	report, err = JapaneseContent(f.root)
	if err != nil || report.MasterRows != 0 || report.AssetRows != 30 || report.DictionaryRows != 6 || report.PackagesUpdated != 12 {
		t.Fatalf("restart should finish only uncommitted databases: report=%+v err=%v", report, err)
	}
	assertJapaneseContentApplied(t, f)
	beforeRepeat := japaneseContentSnapshot(t, f.allPaths())
	if report, err = JapaneseContent(f.root); err != nil || report.MasterRows != 0 || report.AssetRows != 0 || report.DictionaryRows != 0 || report.PackagesUpdated != 0 {
		t.Fatalf("completed restart should be idempotent: report=%+v err=%v", report, err)
	}
	assertJapaneseContentSnapshot(t, beforeRepeat)
}
