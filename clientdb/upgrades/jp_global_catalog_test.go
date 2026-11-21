package upgrades

import (
	"os"
	"path/filepath"
	"regexp"
	"testing"
)

func TestGlobalCatalogPrunesOnlyShadowedMappings(t *testing.T) {
	for _, tc := range []struct {
		name, liveEdit string
		wantRemoved    int64
	}{
		{"stock", "", 1},
		{"a lookup uses the JP pack", "UPDATE texture SET pack_name = 'jp0001' WHERE asset_path = 'banner';", 0},
		{"a mod movie uses the JP pack", "INSERT INTO m_movie VALUES ('owner', 'jp0001');", 0},
		{"a mod sound uses the JP pack", "INSERT INTO m_asset_sound VALUES ('owner', NULL, 'jp0001');", 0},
		{"a mod changes retention", "UPDATE m_asset_pack SET auto_delete = 0 WHERE pack_name = 'jp0001';", 0},
		{"a mod changes pack metadata", "UPDATE m_asset_package_mapping SET metapack_offset = 10 WHERE pack_name = 'jp0001';", 0},
		{"a mod adds package membership", "INSERT INTO m_asset_package_mapping VALUES ('owner','jp0001',100,NULL,0,8);", 0},
		{"a replacement is only in a different package", "UPDATE m_asset_package_mapping SET package_key = 'owner' WHERE pack_name = 'gl0001';", 0},
		{"a replacement no longer fits the file", "UPDATE texture SET head = 60 WHERE asset_path = 'banner';", 0},
		{"a lookup was deleted", "DELETE FROM texture WHERE asset_path = 'banner';", 0},
		{"an extended asset table has a binary pack reference", "CREATE TABLE owner_packs (pack BLOB); INSERT INTO owner_packs VALUES (CAST('jp0001' AS BLOB));", 0},
		{"an owner reference includes the pack in a path", "INSERT INTO m_movie VALUES ('owner', '/archive/jp0001.ranged');", 0},
		{"the replacement metapack is invalid", "UPDATE metapack SET file_size = 50 WHERE metapack_name = 'meta01';", 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			sourcePath := filepath.Join(root, "db", "gl", "asset_a_en.db")
			jpPath := filepath.Join(root, "db", "jp", "asset_a_ja.db")
			destination := filepath.Join(root, "served.db")
			for _, path := range []string{sourcePath, jpPath} {
				if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
					t.Fatal(err)
				}
				db := testDatabase(t, path)
				execTestSQL(t, db,
					`CREATE TABLE m_asset_package (package_key TEXT PRIMARY KEY, version TEXT, pack_num INTEGER)`,
					`CREATE TABLE m_asset_package_mapping (package_key TEXT, pack_name TEXT, file_size INTEGER, metapack_name TEXT, metapack_offset INTEGER, category INTEGER, PRIMARY KEY (package_key, pack_name))`,
					`CREATE TABLE m_asset_pack (pack_name TEXT PRIMARY KEY, auto_delete INTEGER)`,
					`CREATE TABLE metapack (metapack_name TEXT PRIMARY KEY, file_size INTEGER, category INTEGER)`,
					`CREATE TABLE texture (asset_path TEXT PRIMARY KEY, pack_name TEXT, head INTEGER, size INTEGER, key1 INTEGER, key2 INTEGER)`,
					`CREATE TABLE m_movie (pavement TEXT PRIMARY KEY, pack_name TEXT)`,
					`CREATE TABLE m_asset_sound (sheet_name TEXT PRIMARY KEY, acb_pack_name TEXT, awb_pack_name TEXT)`,
					`INSERT INTO m_asset_package VALUES ('main','merged',1),('owner','keep',0)`,
					`INSERT INTO m_asset_package_mapping VALUES ('main','jp0001',100,NULL,0,8)`,
					`INSERT INTO m_asset_pack VALUES ('jp0001',1)`,
					`INSERT INTO texture VALUES ('banner','jp0001',0,100,1,2)`,
				)
				db.Close()
			}
			jpSHA, err := jpGlobalFingerprint(jpPath)
			if err != nil {
				t.Fatal(err)
			}
			source := testDatabase(t, sourcePath)
			execTestSQL(t, source,
				`CREATE TABLE elichika_jp_global_merge (id INTEGER PRIMARY KEY, source_sha TEXT, algorithm_version TEXT)`,
				`UPDATE m_asset_package SET pack_num = 2 WHERE package_key = 'main'`,
				`INSERT INTO m_asset_package_mapping VALUES ('main','gl0001',100,'meta01',0,8)`,
				`INSERT INTO m_asset_pack VALUES ('gl0001',0)`,
				`INSERT INTO metapack VALUES ('meta01',150,8)`,
				`UPDATE texture SET pack_name = 'gl0001', size = 50 WHERE asset_path = 'banner'`,
			)
			if _, err := source.Exec("INSERT INTO elichika_jp_global_merge VALUES (1,?,?)", jpSHA, jpGlobalAlgorithm); err != nil {
				t.Fatal(err)
			}
			if tc.liveEdit != "" {
				execTestSQL(t, source, tc.liveEdit)
			}
			source.Close()
			master := testDatabase(t, filepath.Join(root, "db", "gl", "masterdata.db"))
			execTestSQL(t, master, "CREATE TABLE stock_master (sample TEXT)")
			master.Close()

			original, err := jpGlobalFingerprint(sourcePath)
			if err != nil {
				t.Fatal(err)
			}
			policy, err := newGlobalDownloadCatalogs(root, globalCatalogEvidence{
				SourceSHA256: map[string]string{"a": jpSHA},
				Catalogs:     map[string][]string{"asset_a_en.db": {"jp0001"}},
			})
			if err != nil || policy == nil {
				t.Fatalf("prepare policy: %v", err)
			}
			removed, err := policy.Prepare(sourcePath, destination)
			if err != nil || removed != tc.wantRemoved {
				t.Fatalf("removed %d, want %d, error %v", removed, tc.wantRemoved, err)
			}
			if current, err := jpGlobalFingerprint(sourcePath); err != nil || current != original {
				t.Fatalf("installed catalog changed: %s, %v", current, err)
			}
			if removed == 0 {
				if _, err := os.Stat(destination); !os.IsNotExist(err) {
					t.Fatalf("unexpected derived catalog: %v", err)
				}
				return
			}

			served, err := openJPGlobalReadOnly(destination)
			if err != nil {
				t.Fatal(err)
			}
			defer served.Close()
			var version, ownerVersion, status string
			var count, pack, mappings int
			if err := served.QueryRow("PRAGMA quick_check").Scan(&status); err != nil || status != "ok" {
				t.Fatalf("invalid derived catalog: %s, %v", status, err)
			}
			if err := served.QueryRow("SELECT version, pack_num FROM m_asset_package WHERE package_key='main'").Scan(&version, &count); err != nil {
				t.Fatal(err)
			}
			if count != 1 || !regexp.MustCompile("^[0-9a-f]{40}$").MatchString(version) {
				t.Fatalf("invalid changed package header: %s, %d", version, count)
			}
			if err := served.QueryRow("SELECT version FROM m_asset_package WHERE package_key='owner'").Scan(&ownerVersion); err != nil || ownerVersion != "keep" {
				t.Fatalf("owner package revision: %s, %v", ownerVersion, err)
			}
			if err := served.QueryRow("SELECT count(*) FROM m_asset_pack WHERE pack_name='jp0001'").Scan(&pack); err != nil || pack != 1 {
				t.Fatalf("registered JP pack changed: %d, %v", pack, err)
			}
			if err := served.QueryRow("SELECT count(*) FROM m_asset_package_mapping WHERE pack_name='jp0001'").Scan(&mappings); err != nil || mappings != 0 {
				t.Fatalf("JP pack mappings: %d, %v", mappings, err)
			}
		})
	}
}
