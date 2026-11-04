package upgrades

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestJapaneseContentDoesNotReimportRetainedRegionalMods(t *testing.T) {
	root, state := managedTestState(t)
	state.Algorithm = jpGlobalAlgorithm
	for i := range state.Coverage {
		state.Coverage[i].Algorithm = jpGlobalAlgorithm
	}
	for _, region := range []string{"jp", "gl"} {
		path := filepath.Join(root, "assets", "db", region, "masterdata.db")
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
		db := testDatabase(t, path)
		execTestSQL(t, db, `CREATE TABLE m_lesson_drop_amount (id INTEGER)`,
			`CREATE TABLE m_content (id INTEGER PRIMARY KEY, name TEXT NOT NULL)`)
		if region == "jp" {
			execTestSQL(t, db, `INSERT INTO m_content VALUES (1, 'stock'), (900, 'JP-only owner mod')`)
		} else {
			execTestSQL(t, db, `ALTER TABLE m_content ADD COLUMN owner_note TEXT NOT NULL DEFAULT 'owner default'`,
				`INSERT INTO m_content VALUES (1, 'GL owner override', 'keep custom schema and values')`)
		}
		db.Close()
	}
	managedTestSave(t, root, state)
	paths := []string{}
	before := map[string][]byte{}
	for relative := range state.IncomingDatabases {
		path := filepath.Join(root, filepath.FromSlash(relative))
		paths = append(paths, path)
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		before[path] = data
	}
	report, err := JapaneseContent(filepath.Join(root, "assets"))
	if err != nil || !strings.Contains(report.SkippedReason, "managed installer") ||
		report.MasterRows != 0 || report.AssetRows != 0 || report.DictionaryRows != 0 {
		t.Fatalf("managed catalog was reimported: report=%+v error=%v", report, err)
	}
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(before[path], data) {
			t.Fatalf("retained database changed during server import: %s", filepath.Base(path))
		}
	}
	db := testDatabase(t, filepath.Join(root, "assets/db/gl/masterdata.db"))
	defer db.Close()
	var leaked int
	if err = db.QueryRow(`SELECT COUNT(*) FROM m_content WHERE id=900`).Scan(&leaked); err != nil || leaked != 0 {
		t.Fatal("JP-only owner mod leaked into GL")
	}
}

func TestJapaneseContentRejectsStaleManagedStateWithoutDatabaseWrites(t *testing.T) {
	root, state := managedTestState(t)
	state.Algorithm = jpGlobalAlgorithm
	for i := range state.Coverage {
		state.Coverage[i].Algorithm = jpGlobalAlgorithm
	}
	state.PayloadVersion = "uncommitted-version"
	managedTestSave(t, root, state)
	path := filepath.Join(root, "assets/db/gl/masterdata.db")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = JapaneseContent(filepath.Join(root, "assets")); err == nil {
		t.Fatal("stale managed state was allowed to fall through to the importer")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("failed managed setup mutated a database")
	}
}
