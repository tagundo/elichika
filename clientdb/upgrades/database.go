package upgrades

import (
	"database/sql"
	"net/url"
	"path/filepath"

	_ "modernc.org/sqlite"
)

func openExisting(path string) (*sql.DB, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	// Never create an empty DB when an asset file is missing. Serialize competing
	// writers before checking their guards again inside the transaction.
	dsn := (&url.URL{Scheme: "file", Path: absPath, RawQuery: url.Values{
		"mode":    {"rw"},
		"_txlock": {"immediate"},
		"_pragma": {"busy_timeout(5000)"},
	}.Encode()}).String()
	database, err := sql.Open("sqlite", dsn)
	if err == nil {
		database.SetMaxOpenConns(1)
	}
	return database, err
}
