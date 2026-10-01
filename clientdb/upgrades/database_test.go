package upgrades

import (
	"database/sql"
	"net/url"
	"testing"
)

func TestDatabaseFileURLAcceptsAbsolutePaths(t *testing.T) {
	for _, tc := range []struct {
		name, path, host, uriPath string
	}{
		{"Unix", "/tmp/server 漢字 # ? %.db", "", "/tmp/server 漢字 # ? %.db"},
		{"Unix literal backslash", `/tmp/literal\name.db`, "", `/tmp/literal\name.db`},
		{"Windows drive", "C:/Users/owner/server 漢字 # %.db", "", "/C:/Users/owner/server 漢字 # %.db"},
		{"Windows UNC", "//server/share/server 漢字 # %.db", "localhost", "//server/share/server 漢字 # %.db"},
		{"Windows extended drive", "//?/C:/server 漢字 # %.db", "", "/C:/server 漢字 # %.db"},
		{"Windows extended UNC", "//?/UNC/server/share/server 漢字 # %.db", "localhost", "//server/share/server 漢字 # %.db"},
		{"Windows lowercase extended UNC", "//?/unc/server/share/server 漢字 # %.db", "localhost", "//server/share/server 漢字 # %.db"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			uri := databaseFileURL(tc.path)
			parsed, err := url.Parse(uri.String())
			if err != nil || parsed.Scheme != "file" || parsed.Host != tc.host || parsed.Path != tc.uriPath || parsed.RawQuery != "" || parsed.Fragment != "" {
				t.Fatalf("path was not preserved as a file URI: uri=%s parsed=%#v err=%v", uri, parsed, err)
			}
			// Exercise SQLite's real URI parser on every host without requiring a
			// remote UNC share. Native on-disk upgrades run separately on Windows CI.
			uri.RawQuery = "mode=memory"
			database, err := sql.Open("sqlite", uri.String())
			if err != nil {
				t.Fatal(err)
			}
			defer database.Close()
			var got int
			if err = database.QueryRow("SELECT 1").Scan(&got); err != nil || got != 1 {
				t.Fatalf("SQLite rejected the file URI: uri=%s value=%d err=%v", uri, got, err)
			}
		})
	}
}
