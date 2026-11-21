package upgrades

import (
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

const scopedIntegrationTitle = `
    CREATE TABLE m_asset_package(package_key TEXT PRIMARY KEY NOT NULL, version TEXT NOT NULL, pack_num INTEGER NOT NULL);
    INSERT INTO m_asset_package VALUES ('main','existing-main',3), ('live:stage','unchanged-3d-stage',1), ('owner','unchanged-owner',1);
    CREATE TABLE m_asset_package_mapping(package_key TEXT NOT NULL, pack_name TEXT NOT NULL, file_size INTEGER NOT NULL, metapack_name TEXT, metapack_offset INTEGER NOT NULL, category INTEGER NOT NULL, PRIMARY KEY(package_key,pack_name));
    INSERT INTO m_asset_package_mapping VALUES ('main','jpthmb',250,NULL,0,8), ('main','jpold1',50,'bigold',180,8), ('main','glkeep',120,NULL,0,8), ('live:stage','stg001',400,'stgmet',60,3), ('owner','mod001',19,NULL,0,3);
    CREATE TABLE texture(asset_path TEXT PRIMARY KEY NOT NULL, pack_name TEXT NOT NULL, head INTEGER NOT NULL, size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
    INSERT INTO texture VALUES ('thumbnail','glkeep',4,8,2,3), ('owner/texture','mod001',1,12,6,8);
    CREATE TABLE stage(stage_path TEXT PRIMARY KEY NOT NULL, pack_name TEXT NOT NULL, head INTEGER NOT NULL, size INTEGER NOT NULL);
    INSERT INTO stage VALUES ('stage/base','stg001',15,38);
    CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY NOT NULL, file_size INTEGER NOT NULL, category INTEGER NOT NULL);
    INSERT INTO metapack VALUES ('stgmet',4500,3), ('bigold',2000,8);
`

func scopedIntegrationSource(t *testing.T, additionalSQL string) (string, globalCatalogDelta) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "asset_a_en.db")
	db := testDatabase(t, path)
	execTestSQL(t, db, scopedIntegrationTitle)
	if additionalSQL != "" {
		execTestSQL(t, db, additionalSQL)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	fingerprint, err := jpGlobalFingerprint(path)
	if err != nil {
		t.Fatal(err)
	}
	return path, globalCatalogDelta{SourceSHA256: fingerprint, Tables: map[string]globalCatalogTableDelta{
		"m_asset_package": {
			Columns: []string{"package_key", "version", "pack_num"},
			Remove:  [][]any{{"main", "existing-main", int64(3)}},
			Add:     [][]any{{"main", "f1bb01dc843ffad3adcb9813ecfad39a3990054b", int64(2)}},
		},
		"m_asset_package_mapping": {
			Columns: []string{"package_key", "pack_name", "file_size", "metapack_name", "metapack_offset", "category"},
			Remove:  [][]any{{"main", "jpthmb", int64(250), nil, int64(0), int64(8)}, {"main", "jpold1", int64(50), "bigold", int64(180), int64(8)}},
			Add:     [][]any{{"main", "addbak", int64(100), nil, int64(0), int64(8)}},
		},
		"texture": {
			Columns: []string{"asset_path", "pack_name", "head", "size", "key1", "key2"},
			Add:     [][]any{{"restored/thumbnail", "addbak", int64(7), int64(44), json.Number("-2"), int64(3)}},
		},
	}}
}

func TestScopedCatalogDeltaKeepsStageAndOwnerRoutes(t *testing.T) {
	source, delta := scopedIntegrationSource(t, "")
	path := filepath.Join(t.TempDir(), "served.db")
	var firstDigest string
	for i := 0; i < 4; i++ {
		if err := copyGlobalCatalog(source, path); err != nil {
			t.Fatal(err)
		}
		if count, err := applyGlobalCatalogSelection(path, delta); err != nil || count != 2 {
			t.Fatalf("apply exact delta: %d, %v", count, err)
		}
		digest, err := jpGlobalFingerprint(path)
		if err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			firstDigest = digest
		} else if digest != firstDigest {
			t.Fatalf("same source and proof generated new catalog bytes: %s != %s", digest, firstDigest)
		}
		if i < 3 {
			if err := os.Remove(path); err != nil {
				t.Fatal(err)
			}
		}
	}
	assertJapaneseContentRows(t, path, `SELECT package_key, version, pack_num FROM m_asset_package ORDER BY package_key`, [][]any{
		{"live:stage", "unchanged-3d-stage", int64(1)},
		{"main", "f1bb01dc843ffad3adcb9813ecfad39a3990054b", int64(2)},
		{"owner", "unchanged-owner", int64(1)},
	})
	assertJapaneseContentRows(t, path, `SELECT package_key, pack_name, file_size, metapack_name, metapack_offset, category FROM m_asset_package_mapping ORDER BY package_key, pack_name`, [][]any{
		{"live:stage", "stg001", int64(400), "stgmet", int64(60), int64(3)},
		{"main", "addbak", int64(100), nil, int64(0), int64(8)},
		{"main", "glkeep", int64(120), nil, int64(0), int64(8)},
		{"owner", "mod001", int64(19), nil, int64(0), int64(3)},
	})
	assertJapaneseContentRows(t, path, `SELECT * FROM texture ORDER BY asset_path`, [][]any{
		{"owner/texture", "mod001", int64(1), int64(12), int64(6), int64(8)},
		{"restored/thumbnail", "addbak", int64(7), int64(44), int64(-2), int64(3)},
		{"thumbnail", "glkeep", int64(4), int64(8), int64(2), int64(3)},
	})
	assertJapaneseContentRows(t, path, `SELECT * FROM stage`, [][]any{{"stage/base", "stg001", int64(15), int64(38)}})
	assertJapaneseContentRows(t, path, `SELECT count(*) FROM m_asset_package p WHERE pack_num != (SELECT count(*) FROM m_asset_package_mapping m WHERE m.package_key=p.package_key)`, [][]any{{int64(0)}})
	assertJapaneseContentRows(t, path, `PRAGMA quick_check`, [][]any{{"ok"}})
}

func TestScopedCatalogDeltaRejectsPartialOrTriggeredChanges(t *testing.T) {
	for _, tc := range []struct {
		name   string
		sql    string
		change func(globalCatalogDelta)
	}{
		{name: "remove must match every affected field", change: func(d globalCatalogDelta) {
			d.Tables["m_asset_package_mapping"].Remove[1][4] = int64(179)
		}},
		{name: "nullable metadata is part of the exact row", change: func(d globalCatalogDelta) {
			d.Tables["m_asset_package_mapping"].Remove[0][3] = ""
		}},
		{name: "inconsistent package counts roll back", change: func(d globalCatalogDelta) {
			d.Tables["m_asset_package"].Add[0][2] = int64(3)
		}},
		{name: "conflicting add rolls back previously applied rows", change: func(d globalCatalogDelta) {
			d.Tables["texture"].Add[0][0] = "thumbnail"
		}},
		{name: "unexpected schema column is refused", change: func(d globalCatalogDelta) {
			d.Tables["texture"].Columns[5] = "other_field"
		}},
		{name: "owner trigger could rewrite the stage", sql: `
            CREATE TRIGGER owner_trigger AFTER DELETE ON m_asset_package_mapping BEGIN
                UPDATE stage SET pack_name='owner1' WHERE stage_path='stage/base';
            END
        `},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path, delta := scopedIntegrationSource(t, tc.sql)
			if tc.change != nil {
				tc.change(delta)
			}
			n, err := applyGlobalCatalogSelection(path, delta)
			if n != 0 || err == nil {
				t.Fatalf("accepted an unsafe change: count %d, err %v", n, err)
			}
			actualSHA, err := jpGlobalFingerprint(path)
			if err != nil || actualSHA != delta.SourceSHA256 {
				t.Fatalf("failed operation modified candidate file: %s, err %v", actualSHA, err)
			}
			assertJapaneseContentRows(t, path, `SELECT * FROM stage`, [][]any{{"stage/base", "stg001", int64(15), int64(38)}})
			assertJapaneseContentRows(t, path, `SELECT version,pack_num FROM m_asset_package WHERE package_key='main'`, [][]any{{"existing-main", int64(3)}})
		})
	}
}

func TestScopedCatalogFingerprintAcceptsManagedHeaderAndRejectsOwnerChanges(t *testing.T) {
	stock, delta := scopedIntegrationSource(t, "")
	proof, err := globalCatalogContentFingerprint(stock)
	if err != nil {
		t.Fatal(err)
	}
	if matches, err := matchesGlobalCatalog(stock, delta.SourceSHA256, proof); err != nil || !matches {
		t.Fatalf("raw stock match: %t, %v", matches, err)
	}
	contents, err := os.ReadFile(stock)
	if err != nil {
		t.Fatal(err)
	}
	// Actual v21.2 SQLite backups change only these fixed-width words.
	binary.BigEndian.PutUint32(contents[24:28], 37)
	binary.BigEndian.PutUint32(contents[40:44], 52)
	binary.BigEndian.PutUint32(contents[92:96], 37)
	binary.BigEndian.PutUint32(contents[96:100], 3045001)
	installed := filepath.Join(t.TempDir(), "asset_a_en.db")
	if err := os.WriteFile(installed, contents, 0600); err != nil {
		t.Fatal(err)
	}
	if matches, err := matchesGlobalCatalog(installed, delta.SourceSHA256, proof); err != nil || !matches {
		t.Fatalf("managed snapshot was refused: %t, %v", matches, err)
	}
	if err := os.WriteFile(installed+"-journal", []byte("in-progress owner transaction"), 0600); err != nil {
		t.Fatal(err)
	}
	if matches, err := matchesGlobalCatalog(installed, delta.SourceSHA256, proof); err != nil || matches {
		t.Fatalf("an unsettled owner transaction was accepted: %t, %v", matches, err)
	}
	if err := os.Remove(installed + "-journal"); err != nil {
		t.Fatal(err)
	}
	db := testDatabase(t, installed)
	execTestSQL(t, db, "UPDATE texture SET pack_name='jpthmb' WHERE asset_path='thumbnail'")
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if matches, err := matchesGlobalCatalog(installed, delta.SourceSHA256, proof); err != nil || matches {
		t.Fatalf("an owner lookup was accepted as stock: %t, %v", matches, err)
	}
}

func TestScopedCatalogPhysicalOwnerFilesInBucketsAndLinks(t *testing.T) {
	root := t.TempDir()
	cache := filepath.Join(root, "cache")
	bucket := filepath.Join(root, "bucket")
	if err := os.MkdirAll(cache, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(bucket, 0700); err != nil {
		t.Fatal(err)
	}
	for _, location := range []string{filepath.Join(bucket, "jpthmb"), filepath.Join(cache, "stg001")} {
		if err := os.WriteFile(location, []byte("retained local pack data"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	for link, target := range map[string]string{
		filepath.Join(cache, "group-0"):       bucket,
		filepath.Join(bucket, "parent-cache"): cache,
		filepath.Join(cache, "jpold1"):        filepath.Join(cache, "stg001"),
		filepath.Join(cache, "broken"):        filepath.Join(bucket, "missing-file"),
	} {
		if err := os.Symlink(target, link); err != nil {
			t.Skipf("symlink setup unavailable: %v", err)
		}
	}
	found, err := localGlobalCatalogOverrides([]string{filepath.Join(root, "missing"), cache, bucket}, map[string]bool{"jpthmb": true, "jpold1": true, "broken": true, "missing": true})
	if err != nil || !reflect.DeepEqual(found, map[string]bool{"jpthmb": true, "jpold1": true}) {
		t.Fatalf("missed or overreported physical owner pack files: %v, %v", found, err)
	}
}

func TestScopedCatalogDownloadExcludesRemovedIndependentMetapacks(t *testing.T) {
	source, _ := scopedIntegrationSource(t, "INSERT INTO metapack VALUES ('extrak',30,8),('extrad',20,8)")
	served, _ := scopedIntegrationSource(t, `
        DELETE FROM m_asset_package_mapping WHERE pack_name='jpold1';
        INSERT INTO metapack VALUES ('extrak',30,8);
    `)
	selected, err := PreparedGlobalDownloadFiles(source, served)
	expected := map[string]struct{}{"jpthmb": {}, "glkeep": {}, "mod001": {}, "stgmet": {}, "extrak": {}}
	if err != nil || !reflect.DeepEqual(selected, expected) {
		t.Fatalf("unscoped or incompletely scoped pack membership: got %v, err %v; want %v", selected, err, expected)
	}
}
