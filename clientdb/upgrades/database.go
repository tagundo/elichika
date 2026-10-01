package upgrades

import (
	"database/sql"
	"net/url"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

func openExisting(path string) (*sql.DB, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	// Never create an empty DB when an asset file is missing. Serialize competing
	// writers before checking their guards again inside the transaction.
	uri := databaseFileURL(filepath.ToSlash(absPath))
	uri.RawQuery = url.Values{
		"mode":    {"rw"},
		"_txlock": {"immediate"},
		"_pragma": {"busy_timeout(5000)"},
	}.Encode()
	database, err := sql.Open("sqlite", uri.String())
	if err == nil {
		database.SetMaxOpenConns(1)
	}
	return database, err
}

// databaseFileURL takes an absolute path with slash separators. A Windows drive
// must be a URI path, not an authority. SQLite accepts only an empty authority or
// localhost; keep a UNC server/share in the path behind that allowed authority.
func databaseFileURL(path string) *url.URL {
	// Normalize Windows extended drive/UNC prefixes before encoding the URI.
	if len(path) >= 8 && strings.EqualFold(path[:8], "//?/UNC/") {
		path = "//" + path[8:]
	} else if len(path) >= 7 && strings.HasPrefix(path, "//?/") && path[5] == ':' && path[6] == '/' {
		path = strings.TrimPrefix(path, "//?/")
	}
	uri := &url.URL{Scheme: "file", Path: path}
	if strings.HasPrefix(path, "//") {
		uri.Host = "localhost"
	} else if !strings.HasPrefix(path, "/") {
		uri.Path = "/" + path
	}
	return uri
}
