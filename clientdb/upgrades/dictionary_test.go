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

const testDictionaryPlan = `{"changes":[
{"id":"known_en","from":["Old English's \"quoted\" line\n<color=#ff>{0}</color>","기존 한국어"],"to":"새 한국어 '설명'\n<color=#ff>{0}</color>"},
{"id":"known_zh","from":["舊版說明\n{0}"],"to":"新的繁體中文說明\n{0}"},
{"id":"custom","from":["Known old English"],"to":"정규 번역"},
{"id":"null","from":["Known old English"],"to":"정규 번역"},
{"id":"already","from":["Already localized"],"to":"Already localized"},
{"id":"missing","from":[],"to":"新加入的文字 {0}"}
]}`

func newDictionaryFixture(t *testing.T) (string, string) {
	t.Helper()
	dir := t.TempDir()
	databasePath := filepath.Join(dir, "dictionary.db")
	planPath := filepath.Join(dir, "dictionary.json")
	database := testDatabase(t, databasePath)
	execTestSQL(t, database,
		`CREATE TABLE m_dictionary (id TEXT PRIMARY KEY, message TEXT, custom_meta TEXT DEFAULT 'custom-default')`,
		`CREATE TABLE custom_notes (id INTEGER PRIMARY KEY, note TEXT)`,
		`INSERT INTO custom_notes VALUES (1, 'keep custom settings')`,
	)
	for _, row := range []struct {
		id      string
		message any
	}{
		{"known_en", "Old English's \"quoted\" line\n<color=#ff>{0}</color>"},
		{"known_zh", "舊版說明\n{0}"},
		{"custom", "An owner's custom English message"},
		{"null", nil},
		{"already", "Already localized"},
		{"unknown", "Do not modify this unrelated key {0}"},
	} {
		if _, err := database.Exec("INSERT INTO m_dictionary VALUES (?, ?, ?)", row.id, row.message, "keep metadata for "+row.id); err != nil {
			t.Fatal(err)
		}
	}
	database.Close()
	writeTestScript(t, planPath, testDictionaryPlan)
	return databasePath, planPath
}

func dictionaryRows(t *testing.T, databasePath string) [][]any {
	t.Helper()
	database := testDatabase(t, databasePath)
	defer database.Close()
	return queryTestRows(t, database, "SELECT id, message, custom_meta FROM m_dictionary ORDER BY id")
}

func assertDictionaryLocalized(t *testing.T, databasePath string) {
	t.Helper()
	want := [][]any{
		{"already", "Already localized", "keep metadata for already"},
		{"custom", "An owner's custom English message", "keep metadata for custom"},
		{"known_en", "새 한국어 '설명'\n<color=#ff>{0}</color>", "keep metadata for known_en"},
		{"known_zh", "新的繁體中文說明\n{0}", "keep metadata for known_zh"},
		{"missing", "新加入的文字 {0}", "custom-default"},
		{"null", nil, "keep metadata for null"},
		{"unknown", "Do not modify this unrelated key {0}", "keep metadata for unknown"},
	}
	if got := dictionaryRows(t, databasePath); !reflect.DeepEqual(got, want) {
		t.Fatalf("localized rows: got %#v, want %#v", got, want)
	}
}

func TestDictionaryTextPreservesCustomDataAndFillsMissingKeys(t *testing.T) {
	databasePath, planPath := newDictionaryFixture(t)
	database := testDatabase(t, databasePath)
	schemas := queryTestRows(t, database, "SELECT name, type, sql FROM sqlite_master ORDER BY name")
	notes := queryTestRows(t, database, "SELECT * FROM custom_notes ORDER BY id")
	database.Close()
	changed, err := DictionaryText(databasePath, planPath)
	if err != nil || changed != 3 {
		t.Fatalf("expected two replacements and one insertion: changed=%v, err=%v", changed, err)
	}
	assertDictionaryLocalized(t, databasePath)
	database = testDatabase(t, databasePath)
	if !reflect.DeepEqual(schemas, queryTestRows(t, database, "SELECT name, type, sql FROM sqlite_master ORDER BY name")) ||
		!reflect.DeepEqual(notes, queryTestRows(t, database, "SELECT * FROM custom_notes ORDER BY id")) {
		t.Fatal("dictionary text upgrade changed schemas or other tables")
	}
	database.Close()
	beforeRepeat := databaseBytes(t, databasePath)
	changed, err = DictionaryText(databasePath, planPath)
	if err != nil || changed != 0 {
		t.Fatalf("repeat should be a no-op: changed=%v, err=%v", changed, err)
	}
	if !bytes.Equal(beforeRepeat, databaseBytes(t, databasePath)) {
		t.Fatal("repeat dictionary upgrade rewrote the DB")
	}
}

func TestDictionaryTextReadOnlyAlreadyCorrectDatabase(t *testing.T) {
	if os.Getuid() == 0 || runtime.GOOS == "windows" {
		t.Skip("filesystem permissions require a non-root Unix user")
	}
	databasePath, planPath := newDictionaryFixture(t)
	if changed, err := DictionaryText(databasePath, planPath); err != nil || changed != 3 {
		t.Fatalf("setup upgrade: changed=%v, err=%v", changed, err)
	}
	before := databaseBytes(t, databasePath)
	if err := os.Chmod(databasePath, 0400); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(databasePath, 0600) })
	changed, err := DictionaryText(databasePath, planPath)
	if err != nil || changed != 0 {
		t.Fatalf("already correct read-only DB should work: changed=%v, err=%v", changed, err)
	}
	if !bytes.Equal(before, databaseBytes(t, databasePath)) {
		t.Fatal("already correct read-only DB was rewritten")
	}
}

func TestDictionaryTextRollsBackMidwayFailureAndRetries(t *testing.T) {
	databasePath, planPath := newDictionaryFixture(t)
	database := testDatabase(t, databasePath)
	execTestSQL(t, database, `CREATE TRIGGER reject_second_change BEFORE UPDATE ON m_dictionary WHEN NEW.id = 'known_zh' BEGIN SELECT RAISE(ABORT, 'test midway failure'); END`)
	database.Close()
	before := dictionaryRows(t, databasePath)
	beforeBytes := databaseBytes(t, databasePath)
	changed, err := DictionaryText(databasePath, planPath)
	if err == nil || changed != 0 || !strings.Contains(err.Error(), "known_zh") || !strings.Contains(err.Error(), "test midway failure") {
		t.Fatalf("midway failure should identify its key: changed=%v, err=%v", changed, err)
	}
	if !reflect.DeepEqual(before, dictionaryRows(t, databasePath)) || !bytes.Equal(beforeBytes, databaseBytes(t, databasePath)) {
		t.Fatal("midway failure left the first replacement committed")
	}
	database = testDatabase(t, databasePath)
	execTestSQL(t, database, "DROP TRIGGER reject_second_change")
	database.Close()
	changed, err = DictionaryText(databasePath, planPath)
	if err != nil || changed != 3 {
		t.Fatalf("retry after removing the failure should succeed: changed=%v, err=%v", changed, err)
	}
	assertDictionaryLocalized(t, databasePath)
}

func TestDictionaryTextRejectsInvalidPlansBeforeMutation(t *testing.T) {
	for _, tc := range []struct {
		name string
		plan string
	}{
		{"invalid UTF-8", "{\"changes\":[{\"id\":\"known_en\",\"to\":\"" + string([]byte{0xff}) + "\"}]}"},
		{"malformed", `{"changes":`},
		{"trailing JSON", testDictionaryPlan + `{}`},
		{"duplicate dictionary keys", `{"changes":[{"id":"known_en","from":["old"],"to":"new"},{"id":"known_en","from":["old"],"to":"other"}]}`},
		{"unknown field", `{"changes":[{"id":"known_en","from":["old"],"to":"new","typo":true}]}`},
		{"empty key", `{"changes":[{"id":"","to":"new"}]}`},
		{"empty destination", `{"changes":[{"id":"known_en","to":""}]}`},
		{"no changes", `{"changes":[]}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			databasePath, planPath := newDictionaryFixture(t)
			before := databaseBytes(t, databasePath)
			writeTestScript(t, planPath, tc.plan)
			changed, err := DictionaryText(databasePath, planPath)
			if err == nil || changed != 0 {
				t.Fatalf("invalid plan should fail: changed=%v, err=%v", changed, err)
			}
			if !bytes.Equal(before, databaseBytes(t, databasePath)) {
				t.Fatal("invalid plan rewrote the DB")
			}
		})
	}
}

func TestDictionaryTextMissingOptionalPlanIsNoOp(t *testing.T) {
	databasePath, planPath := newDictionaryFixture(t)
	if err := os.Remove(planPath); err != nil {
		t.Fatal(err)
	}
	before := databaseBytes(t, databasePath)
	changed, err := DictionaryText(databasePath, planPath)
	if err != nil || changed != 0 || !bytes.Equal(before, databaseBytes(t, databasePath)) {
		t.Fatalf("missing optional plan should be a no-op: changed=%v, err=%v", changed, err)
	}
}

func TestDictionaryTextMissingDatabaseIsNotCreated(t *testing.T) {
	dir := t.TempDir()
	databasePath, planPath := filepath.Join(dir, "missing.db"), filepath.Join(dir, "plan.json")
	writeTestScript(t, planPath, testDictionaryPlan)
	changed, err := DictionaryText(databasePath, planPath)
	if err == nil || changed != 0 {
		t.Fatalf("missing DB should fail: changed=%v, err=%v", changed, err)
	}
	if _, err := os.Stat(databasePath); !os.IsNotExist(err) {
		t.Fatalf("missing DB was created: %v", err)
	}
}

func TestDictionaryTextMissingTableAndCustomViewAreNoOps(t *testing.T) {
	for _, view := range []bool{false, true} {
		name := "missing table"
		if view {
			name = "custom view"
		}
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			databasePath, planPath := filepath.Join(dir, "dictionary.db"), filepath.Join(dir, "plan.json")
			database := testDatabase(t, databasePath)
			execTestSQL(t, database, "CREATE TABLE custom_notes (id TEXT, message TEXT)", "INSERT INTO custom_notes VALUES ('known_en', 'custom view message')")
			if view {
				execTestSQL(t, database, "CREATE VIEW m_dictionary AS SELECT * FROM custom_notes")
			}
			database.Close()
			writeTestScript(t, planPath, testDictionaryPlan)
			before := databaseBytes(t, databasePath)
			changed, err := DictionaryText(databasePath, planPath)
			if err != nil || changed != 0 || !bytes.Equal(before, databaseBytes(t, databasePath)) {
				t.Fatalf("absent/custom target should be a no-op: changed=%v, err=%v", changed, err)
			}
		})
	}
}

func TestDictionaryTextSerializesConcurrentUpdates(t *testing.T) {
	databasePath, planPath := newDictionaryFixture(t)
	start := make(chan struct{})
	results := make(chan struct {
		count int64
		err   error
	}, 2)
	for i := 0; i < 2; i++ {
		go func() {
			<-start
			count, err := DictionaryText(databasePath, planPath)
			results <- struct {
				count int64
				err   error
			}{count, err}
		}()
	}
	close(start)
	changedCalls := 0
	var changedRows int64
	for i := 0; i < 2; i++ {
		result := <-results
		if result.err != nil {
			t.Error(result.err)
		}
		if result.count != 0 {
			changedCalls++
			changedRows += result.count
		}
	}
	if changedCalls != 1 || changedRows != 3 {
		t.Fatalf("only one caller should apply the three changes: callers=%d rows=%d", changedCalls, changedRows)
	}
	assertDictionaryLocalized(t, databasePath)
}

func TestDictionaryTextEscapesDatabaseAndPlanPaths(t *testing.T) {
	databasePath, planPath := newDictionaryFixture(t)
	directory, databaseName, planName := "translated files 漢字 # ? %", "dictionary ?mode=ro#%.db", "translations ? # %.json"
	if runtime.GOOS == "windows" {
		directory, databaseName, planName = "translated files 漢字 # %", "dictionary #%.db", "translations # %.json"
	}
	dir := filepath.Join(filepath.Dir(databasePath), directory)
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	newDatabase := filepath.Join(dir, databaseName)
	newPlan := filepath.Join(dir, planName)
	if err := os.Rename(databasePath, newDatabase); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(planPath, newPlan); err != nil {
		t.Fatal(err)
	}
	changed, err := DictionaryText(newDatabase, newPlan)
	if err != nil || changed != 3 {
		t.Fatalf("special paths should update the intended DB: changed=%v, err=%v", changed, err)
	}
	assertDictionaryLocalized(t, newDatabase)
	files, err := os.ReadDir(dir)
	if err != nil || len(files) != 2 {
		t.Fatalf("special paths created unexpected files: files=%v err=%v", files, err)
	}
}
