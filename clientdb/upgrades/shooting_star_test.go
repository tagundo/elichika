package upgrades

import (
	"bytes"
	"database/sql"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

const testShootingStarScript = `-- An asset-provided, single-line-per-statement upgrade.
CREATE TABLE m_lesson_skill_shooting_star (skill_master_id INTEGER, lesson_menu_id INTEGER, PRIMARY KEY (skill_master_id, lesson_menu_id));
INSERT INTO m_lesson_skill_shooting_star VALUES (30000526, 1);
INSERT INTO m_lesson_skill_shooting_star VALUES (30000057, 3);
`

func testDatabase(t *testing.T, path string) *sql.DB {
	t.Helper()
	// Construct the fixture URI independently of openExisting. SQLite accepts
	// file:C:/... without treating a Windows drive as an authority.
	slashPath := filepath.ToSlash(path)
	uri := "file:" + (&url.URL{Path: slashPath}).EscapedPath()
	if strings.HasPrefix(slashPath, "//") {
		uri = "file://localhost" + (&url.URL{Path: slashPath}).EscapedPath()
	}
	database, err := sql.Open("sqlite", uri)
	if err != nil {
		t.Fatal(err)
	}
	database.SetMaxOpenConns(1)
	t.Cleanup(func() { database.Close() })
	return database
}

func execTestSQL(t *testing.T, database *sql.DB, statements ...string) {
	t.Helper()
	for _, statement := range statements {
		if _, err := database.Exec(statement); err != nil {
			t.Fatalf("%s: %v", statement, err)
		}
	}
}

func writeTestScript(t *testing.T, path, contents string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(contents), 0600); err != nil {
		t.Fatal(err)
	}
}

func newUpgradeFixture(t *testing.T) (string, string) {
	t.Helper()
	dir := t.TempDir()
	databasePath := filepath.Join(dir, "masterdata.db")
	scriptPath := filepath.Join(dir, "shooting-star.sql")
	database := testDatabase(t, databasePath)
	execTestSQL(t, database,
		`CREATE TABLE m_lesson_skill_content (skill_master_id INTEGER PRIMARY KEY, drop_type INTEGER, rarity INTEGER, lesson_menu_id1 INTEGER, lesson_menu_id2 INTEGER, custom_note TEXT)`,
		`INSERT INTO m_lesson_skill_content VALUES (30000057, 1, 5, 3, NULL, 'keep verified eligibility'), (999999, 4, 2, 7, 4, 'custom skill and rates')`,
		`CREATE TABLE custom_notes (id INTEGER PRIMARY KEY, note TEXT NOT NULL)`,
		`INSERT INTO custom_notes VALUES (1, 'custom outfits and server settings stay intact')`,
		`CREATE INDEX custom_skill_index ON m_lesson_skill_content (custom_note)`,
		`CREATE TRIGGER custom_skill_watch AFTER UPDATE ON m_lesson_skill_content BEGIN UPDATE custom_notes SET note = 'unexpectedly modified'; END`,
	)
	if err := database.Close(); err != nil {
		t.Fatal(err)
	}
	writeTestScript(t, scriptPath, testShootingStarScript)
	return databasePath, scriptPath
}

func queryTestRows(t *testing.T, database *sql.DB, query string) [][]any {
	t.Helper()
	rows, err := database.Query(query)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		t.Fatal(err)
	}
	result := [][]any{}
	for rows.Next() {
		values := make([]any, len(columns))
		pointers := make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			t.Fatal(err)
		}
		result = append(result, values)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	return result
}

func existingData(t *testing.T, databasePath string) [][][]any {
	t.Helper()
	database := testDatabase(t, databasePath)
	defer database.Close()
	return [][][]any{
		queryTestRows(t, database, `SELECT name, type, sql FROM sqlite_master WHERE lower(name) != 'm_lesson_skill_shooting_star' AND name NOT LIKE 'sqlite_%' ORDER BY name`),
		queryTestRows(t, database, `SELECT * FROM m_lesson_skill_content ORDER BY skill_master_id`),
		queryTestRows(t, database, `SELECT * FROM custom_notes ORDER BY id`),
	}
}

func databaseBytes(t *testing.T, databasePath string) []byte {
	t.Helper()
	contents, err := os.ReadFile(databasePath)
	if err != nil {
		t.Fatal(err)
	}
	return contents
}

func assertNoShootingStarObject(t *testing.T, databasePath string) {
	t.Helper()
	database := testDatabase(t, databasePath)
	defer database.Close()
	if rows := queryTestRows(t, database, `SELECT name FROM sqlite_master WHERE lower(name) = 'm_lesson_skill_shooting_star'`); len(rows) != 0 {
		t.Fatalf("failed/skipped upgrade left a shooting-star object: %v", rows)
	}
}

func TestLessonShootingStarsAddsOnlyMissingMetadata(t *testing.T) {
	databasePath, scriptPath := newUpgradeFixture(t)
	before := existingData(t, databasePath)
	changed, err := LessonShootingStars(databasePath, scriptPath)
	if err != nil || !changed {
		t.Fatalf("upgrade: changed=%v, err=%v", changed, err)
	}
	if after := existingData(t, databasePath); !reflect.DeepEqual(before, after) {
		t.Fatalf("upgrade changed existing schemas or custom data:\nbefore=%v\nafter=%v", before, after)
	}
	database := testDatabase(t, databasePath)
	got := queryTestRows(t, database, `SELECT skill_master_id, lesson_menu_id FROM m_lesson_skill_shooting_star ORDER BY skill_master_id`)
	want := [][]any{{int64(30000057), int64(3)}, {int64(30000526), int64(1)}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("metadata: got %v, want %v", got, want)
	}
	database.Close()
	upgradedBytes := databaseBytes(t, databasePath)
	changed, err = LessonShootingStars(databasePath, scriptPath)
	if err != nil || changed {
		t.Fatalf("repeat should be a no-op: changed=%v, err=%v", changed, err)
	}
	if !bytes.Equal(upgradedBytes, databaseBytes(t, databasePath)) {
		t.Fatal("repeat upgrade rewrote the database")
	}
}

func TestLessonShootingStarsPreservesExistingCustomization(t *testing.T) {
	for _, tc := range []struct {
		name string
		sql  []string
	}{
		{"custom table", []string{
			`CREATE TABLE m_lesson_skill_shooting_star (custom_animation TEXT PRIMARY KEY)`,
			`INSERT INTO m_lesson_skill_shooting_star VALUES ('keep this custom schema and row')`,
		}},
		{"empty table", []string{
			`CREATE TABLE m_lesson_skill_shooting_star (skill_master_id INTEGER, lesson_menu_id INTEGER)`,
		}},
		{"case-insensitive name", []string{
			`CREATE TABLE M_LESSON_SKILL_SHOOTING_STAR (custom_animation TEXT)`,
			`INSERT INTO M_LESSON_SKILL_SHOOTING_STAR VALUES ('custom uppercase table')`,
		}},
		{"custom view", []string{
			`CREATE VIEW m_lesson_skill_shooting_star AS SELECT skill_master_id, lesson_menu_id1 AS lesson_menu_id FROM m_lesson_skill_content`,
		}},
		{"custom index with reserved name", []string{
			`CREATE INDEX m_lesson_skill_shooting_star ON custom_notes (note)`,
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			databasePath, scriptPath := newUpgradeFixture(t)
			database := testDatabase(t, databasePath)
			execTestSQL(t, database, tc.sql...)
			database.Close()
			before := databaseBytes(t, databasePath)
			// Existing customizations must be checked before loading/executing scripts.
			writeTestScript(t, scriptPath, "INVALID SQL;\n")
			changed, err := LessonShootingStars(databasePath, scriptPath)
			if err != nil || changed {
				t.Fatalf("customized object should be a no-op: changed=%v, err=%v", changed, err)
			}
			if !bytes.Equal(before, databaseBytes(t, databasePath)) {
				t.Fatal("existing customization was rewritten")
			}
		})
	}
}

func TestLessonShootingStarsMissingDatabaseIsNotCreated(t *testing.T) {
	dir := t.TempDir()
	databasePath := filepath.Join(dir, "missing.db")
	scriptPath := filepath.Join(dir, "upgrade.sql")
	writeTestScript(t, scriptPath, testShootingStarScript)
	changed, err := LessonShootingStars(databasePath, scriptPath)
	if err == nil || changed {
		t.Fatalf("missing DB should fail without mutation: changed=%v, err=%v", changed, err)
	}
	if _, err := os.Stat(databasePath); !os.IsNotExist(err) {
		t.Fatalf("missing DB was created, stat err=%v", err)
	}
}

func TestLessonShootingStarsMissingOptionalScriptIsNoOp(t *testing.T) {
	databasePath, scriptPath := newUpgradeFixture(t)
	if err := os.Remove(scriptPath); err != nil {
		t.Fatal(err)
	}
	before := databaseBytes(t, databasePath)
	changed, err := LessonShootingStars(databasePath, scriptPath)
	if err != nil || changed {
		t.Fatalf("older assets should remain usable: changed=%v, err=%v", changed, err)
	}
	if !bytes.Equal(before, databaseBytes(t, databasePath)) {
		t.Fatal("missing optional script changed the DB")
	}
	assertNoShootingStarObject(t, databasePath)
}

func TestLessonShootingStarsReadOnlyDatabase(t *testing.T) {
	if os.Getuid() == 0 || runtime.GOOS == "windows" {
		t.Skip("filesystem permission checks require a non-root Unix user")
	}
	for _, alreadyUpgraded := range []bool{false, true} {
		name := "missing metadata"
		if alreadyUpgraded {
			name = "existing metadata"
		}
		t.Run(name, func(t *testing.T) {
			databasePath, scriptPath := newUpgradeFixture(t)
			if alreadyUpgraded {
				if changed, err := LessonShootingStars(databasePath, scriptPath); err != nil || !changed {
					t.Fatalf("setup upgrade: changed=%v, err=%v", changed, err)
				}
			}
			before := databaseBytes(t, databasePath)
			if err := os.Chmod(databasePath, 0400); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { os.Chmod(databasePath, 0600) })
			changed, err := LessonShootingStars(databasePath, scriptPath)
			if changed || (alreadyUpgraded && err != nil) || (!alreadyUpgraded && err == nil) {
				t.Fatalf("read-only DB: changed=%v, err=%v, alreadyUpgraded=%v", changed, err, alreadyUpgraded)
			}
			if !bytes.Equal(before, databaseBytes(t, databasePath)) {
				t.Fatal("read-only DB was mutated")
			}
		})
	}
}

func TestLessonShootingStarsPreTrainingDatabaseIsNoOp(t *testing.T) {
	dir := t.TempDir()
	databasePath := filepath.Join(dir, "old.db")
	scriptPath := filepath.Join(dir, "upgrade.sql")
	database := testDatabase(t, databasePath)
	execTestSQL(t, database, `CREATE TABLE custom_notes (note TEXT)`, `INSERT INTO custom_notes VALUES ('older untouched database')`)
	database.Close()
	writeTestScript(t, scriptPath, testShootingStarScript)
	before := databaseBytes(t, databasePath)
	changed, err := LessonShootingStars(databasePath, scriptPath)
	if err != nil || changed {
		t.Fatalf("pre-training DB should be a no-op: changed=%v, err=%v", changed, err)
	}
	if !bytes.Equal(before, databaseBytes(t, databasePath)) {
		t.Fatal("pre-training DB was rewritten")
	}
	assertNoShootingStarObject(t, databasePath)
}

func TestLessonShootingStarsRollsBackFailedScriptAndRetries(t *testing.T) {
	databasePath, scriptPath := newUpgradeFixture(t)
	before := existingData(t, databasePath)
	writeTestScript(t, scriptPath, testShootingStarScript+"INSERT INTO missing_table VALUES (1);\n")
	changed, err := LessonShootingStars(databasePath, scriptPath)
	if err == nil || changed || !strings.Contains(err.Error(), scriptPath+":5:") {
		t.Fatalf("mid-script failure should report its location: changed=%v, err=%v", changed, err)
	}
	assertNoShootingStarObject(t, databasePath)
	if after := existingData(t, databasePath); !reflect.DeepEqual(before, after) {
		t.Fatalf("failed upgrade changed custom data: %v", after)
	}
	writeTestScript(t, scriptPath, testShootingStarScript)
	changed, err = LessonShootingStars(databasePath, scriptPath)
	if err != nil || !changed {
		t.Fatalf("corrected script should retry successfully: changed=%v, err=%v", changed, err)
	}
}

func TestLessonShootingStarsRejectsIncompleteScriptsWithoutMutation(t *testing.T) {
	for _, tc := range []struct {
		name   string
		script string
	}{
		{"empty", ""},
		{"comments only", "-- no metadata statements\n\n"},
		{"missing target table", "UPDATE custom_notes SET note = 'must roll back';\n"},
		{"scanner overflow after create", testShootingStarScript + strings.Repeat("x", 70_000) + "\n"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			databasePath, scriptPath := newUpgradeFixture(t)
			before := existingData(t, databasePath)
			writeTestScript(t, scriptPath, tc.script)
			changed, err := LessonShootingStars(databasePath, scriptPath)
			if err == nil || changed {
				t.Fatalf("incomplete script should fail: changed=%v, err=%v", changed, err)
			}
			assertNoShootingStarObject(t, databasePath)
			if after := existingData(t, databasePath); !reflect.DeepEqual(before, after) {
				t.Fatalf("incomplete script changed custom data: %v", after)
			}
		})
	}
}

func TestLessonShootingStarsSerializesConcurrentUpgrades(t *testing.T) {
	databasePath, scriptPath := newUpgradeFixture(t)
	start := make(chan struct{})
	results := make(chan struct {
		changed bool
		err     error
	}, 2)
	for i := 0; i < 2; i++ {
		go func() {
			<-start
			changed, err := LessonShootingStars(databasePath, scriptPath)
			results <- struct {
				changed bool
				err     error
			}{changed, err}
		}()
	}
	close(start)
	changes := 0
	for i := 0; i < 2; i++ {
		result := <-results
		if result.err != nil {
			t.Error(result.err)
		}
		if result.changed {
			changes++
		}
	}
	if changes != 1 {
		t.Fatalf("exactly one competing upgrade should change the DB, got %d", changes)
	}
	database := testDatabase(t, databasePath)
	if got := queryTestRows(t, database, `SELECT COUNT(*) FROM m_lesson_skill_shooting_star`); !reflect.DeepEqual(got, [][]any{{int64(2)}}) {
		t.Fatalf("concurrent upgrades duplicated or lost metadata: %v", got)
	}
}

func TestLessonShootingStarsEscapesDatabasePaths(t *testing.T) {
	databasePath, scriptPath := newUpgradeFixture(t)
	directory, filename := "custom assets 漢字 # ? %", "master data ?mode=ro#%.db"
	if runtime.GOOS == "windows" {
		// '?' is not a legal Windows filename; space, Unicode, '#' and '%' are.
		directory, filename = "custom assets 漢字 # %", "master data #%.db"
	}
	dir := filepath.Join(filepath.Dir(databasePath), directory)
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	newPath := filepath.Join(dir, filename)
	if err := os.Rename(databasePath, newPath); err != nil {
		t.Fatal(err)
	}
	changed, err := LessonShootingStars(newPath, scriptPath)
	if err != nil || !changed {
		t.Fatalf("escaped path should upgrade the intended DB: changed=%v, err=%v", changed, err)
	}
	database := testDatabase(t, newPath)
	if got := queryTestRows(t, database, `SELECT COUNT(*) FROM m_lesson_skill_shooting_star`); !reflect.DeepEqual(got, [][]any{{int64(2)}}) {
		t.Fatalf("wrong escaped-path metadata: %v", got)
	}
	files, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 1 || files[0].Name() != filepath.Base(newPath) {
		t.Fatalf("URI-special path created unexpected files: %v", files)
	}
}
