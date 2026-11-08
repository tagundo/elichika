package gamedata

import (
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
	"xorm.io/xorm"
)

func TestStartupBatchOrderGuardPreservesOwnerSchemas(t *testing.T) {
	for _, tc := range []struct {
		name       string
		statements []string
		key        []string
		unique     [][]string
		want       bool
	}{
		{"standard compound key", []string{`CREATE TABLE owner_rows(owner INTEGER, position INTEGER, value INTEGER, PRIMARY KEY(owner,position))`}, []string{"owner", "position"}, nil, true},
		{"allowed unique key", []string{`CREATE TABLE owner_rows(owner INTEGER, position INTEGER, value INTEGER UNIQUE, PRIMARY KEY(owner,position))`}, []string{"owner", "position"}, [][]string{{"value"}}, true},
		{"owner index changes unordered scans", []string{`CREATE TABLE owner_rows(owner INTEGER, position INTEGER, value INTEGER, PRIMARY KEY(owner,position))`, `CREATE INDEX custom_order ON owner_rows(owner,value DESC)`}, []string{"owner", "position"}, nil, false},
		{"descending primary key", []string{`CREATE TABLE owner_rows(owner INTEGER,position INTEGER,value INTEGER,PRIMARY KEY(owner,position DESC))`}, []string{"owner", "position"}, nil, false},
		{"noncanonical primary key", []string{`CREATE TABLE owner_rows(owner INTEGER,position INTEGER,value INTEGER,PRIMARY KEY(position,owner))`}, []string{"owner", "position"}, nil, false},
		{"noninteger owner", []string{`CREATE TABLE owner_rows(owner TEXT,position INTEGER,value INTEGER,PRIMARY KEY(owner,position))`}, []string{"owner", "position"}, nil, false},
		{"rowid primary key", []string{`CREATE TABLE owner_rows(owner INTEGER PRIMARY KEY,value INTEGER)`}, []string{"owner"}, nil, true},
		{"descending integer key is not rowid", []string{`CREATE TABLE owner_rows(owner INTEGER PRIMARY KEY DESC,value INTEGER)`}, []string{"owner"}, nil, false},
		{"unexpected unique index", []string{`CREATE TABLE owner_rows(owner INTEGER,position INTEGER,value INTEGER UNIQUE,PRIMARY KEY(owner,position))`}, []string{"owner", "position"}, nil, false},
		{"missing table", nil, []string{"owner", "position"}, nil, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			engine, err := xorm.NewEngine("sqlite", filepath.Join(t.TempDir(), "order.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer engine.Close()
			for _, sql := range tc.statements {
				if _, err := engine.Exec(sql); err != nil {
					t.Fatal(err)
				}
			}
			session := engine.NewSession()
			defer session.Close()
			got, err := batchReadOrderSafe(session, "owner_rows", tc.key, tc.unique...)
			if err != nil || got != tc.want {
				t.Fatalf("order guard got %v/%v want %v", got, err, tc.want)
			}
		})
	}
}
