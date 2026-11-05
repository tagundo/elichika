package serverdata

import (
	"bytes"
	"elichika/config"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"xorm.io/xorm"
)

type deterministicRow struct {
	ID    int64 `xorm:"pk 'id'"`
	Value string
}

// These tests replace only the serverdata builder globals, never its initialized
// production Database handle. Package tests are serialized by run_go_tests.py.
func isolatedBuilder(t *testing.T, database string) *xorm.Engine {
	t.Helper()
	connection, err := xorm.NewEngine("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { connection.Close() })
	return connection
}

func TestFreshTableAndInitializerOrderIsRepeatable(t *testing.T) {
	savedEngine, savedTables, savedInitializers, savedRebuild := engine, serverDataTableNameToInterface, serverDataTableNameToInitializer, rebuildAsset
	defer func() {
		engine, serverDataTableNameToInterface, serverDataTableNameToInitializer, rebuildAsset = savedEngine, savedTables, savedInitializers, savedRebuild
	}()
	var expected []byte
	for repeat := 0; repeat < 20; repeat++ {
		path := filepath.Join(t.TempDir(), "serverdata.db")
		engine = isolatedBuilder(t, path)
		serverDataTableNameToInterface = map[string]interface{}{
			"z_dependent": deterministicRow{}, "a_first": deterministicRow{},
		}
		serverDataTableNameToInitializer = map[string]Initializer{
			"a_first": func(session *xorm.Session) {
				// Every table must exist before the first initializer runs.
				exists, err := session.Table("z_dependent").IsTableExist("z_dependent")
				if err != nil || !exists {
					t.Fatalf("Dependent table missing before initialization: %v", err)
				}
				if _, err := session.Table("a_first").Insert(deterministicRow{ID: 1, Value: "ready"}); err != nil {
					t.Fatal(err)
				}
			},
			"z_dependent": func(session *xorm.Session) {
				count, err := session.Table("a_first").Count()
				if err != nil || count != 1 {
					t.Fatalf("Initializers did not follow stable table order: %d, %v", count, err)
				}
				if _, err := session.Table("z_dependent").Insert(deterministicRow{ID: 2, Value: "later"}); err != nil {
					t.Fatal(err)
				}
			},
		}
		rebuildAsset = true
		InitTables()
		if err := engine.Close(); err != nil {
			t.Fatal(err)
		}
		actual, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if repeat == 0 {
			expected = actual
		} else if !bytes.Equal(actual, expected) {
			t.Fatalf("Fresh build %d changed raw SQLite bytes", repeat)
		}
	}
}

func TestDictionaryIDsHaveStableInsertionOrder(t *testing.T) {
	root := t.TempDir()
	text := `{"z":{"ja":"z","en":"z","ko":"z","zh":"z"},"a":{"ja":"a","en":"a","ko":"a","zh":"a"},"m":{"ja":"m","en":"m","ko":"m","zh":"m"}}`
	if err := os.WriteFile(filepath.Join(root, "dictionary.json"), []byte(text), 0600); err != nil {
		t.Fatal(err)
	}
	savedPath := config.AssetPath
	config.AssetPath = root + string(os.PathSeparator)
	defer func() { config.AssetPath = savedPath }()
	var expected []byte
	for repeat := 0; repeat < 10; repeat++ {
		path := filepath.Join(t.TempDir(), "serverdata.db")
		connection := isolatedBuilder(t, path)
		for _, language := range []string{"en", "ja", "ko", "zh"} {
			if err := connection.Table("s_dictionary_" + language).CreateTable(DictionaryItem{}); err != nil {
				t.Fatal(err)
			}
		}
		session := connection.NewSession()
		if err := session.Begin(); err != nil {
			t.Fatal(err)
		}
		initDictionary(session)
		if err := session.Commit(); err != nil {
			t.Fatal(err)
		}
		session.Close()
		for _, language := range []string{"en", "ja", "ko", "zh"} {
			rows, err := connection.QueryString("SELECT id FROM s_dictionary_" + language + " ORDER BY rowid")
			if err != nil {
				t.Fatal(err)
			}
			ids := make([]string, 0, len(rows))
			for _, row := range rows {
				ids = append(ids, row["id"])
			}
			if !reflect.DeepEqual(ids, []string{"a", "m", "z"}) {
				t.Fatalf("%s dictionary insertion order: %v", language, ids)
			}
		}
		connection.Close()
		actual, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if repeat == 0 {
			expected = actual
		} else if !bytes.Equal(actual, expected) {
			t.Fatal("Dictionary build changed raw SQLite bytes")
		}
	}
}

func TestDailyTheaterMembersKeepSortedUniqueIDs(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "daily_theater"), 0700); err != nil {
		t.Fatal(err)
	}
	text := `{"language":"ko","daily_theater_id":1,"year":2026,"month":11,"day":4,"title":"synthetic","detail_text":"<:th_ch0201/><:th_ch0102/><:th_ch0101/><:th_ch0102/><:th_ch0000/>"}`
	if err := os.WriteFile(filepath.Join(root, "daily_theater", "test.json"), []byte(text), 0600); err != nil {
		t.Fatal(err)
	}
	savedPath := config.AssetPath
	config.AssetPath = root + string(os.PathSeparator)
	defer func() { config.AssetPath = savedPath }()
	var expected []byte
	for repeat := 0; repeat < 10; repeat++ {
		path := filepath.Join(t.TempDir(), "serverdata.db")
		connection := isolatedBuilder(t, path)
		for _, item := range []struct {
			name string
			bean interface{}
		}{{"s_daily_theater", DailyTheater{}}, {"s_daily_theater_member", DailyTheaterMember{}}} {
			if err := connection.Table(item.name).CreateTable(item.bean); err != nil {
				t.Fatal(err)
			}
		}
		session := connection.NewSession()
		if err := session.Begin(); err != nil {
			t.Fatal(err)
		}
		InitializeDailyTheater(session)
		if err := session.Commit(); err != nil {
			t.Fatal(err)
		}
		session.Close()
		rows, err := connection.QueryString("SELECT member_master_id FROM s_daily_theater_member ORDER BY rowid")
		if err != nil {
			t.Fatal(err)
		}
		ids := make([]string, 0, len(rows))
		for _, row := range rows {
			ids = append(ids, row["member_master_id"])
		}
		if !reflect.DeepEqual(ids, []string{"101", "102", "201"}) {
			t.Fatalf("Unexpected sorted/deduplicated theater members: %v", ids)
		}
		connection.Close()
		actual, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if repeat == 0 {
			expected = actual
		} else if !bytes.Equal(actual, expected) {
			t.Fatal("Daily-theater build changed raw SQLite bytes")
		}
	}
}
