package asset

import (
	"database/sql"
	"elichika/assetdata"
	"elichika/config"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestParseDownloadOptionsPreservesLegacyAndScopes(t *testing.T) {
	for _, c := range []struct {
		args      []string
		workers   int
		scoped    bool
		selection assetdata.DownloadSelection
	}{
		{nil, 8, false, assetdata.DownloadSelection{Region: assetdata.RegionBoth, Platform: assetdata.PlatformBoth, Language: assetdata.LanguageAll}},
		{[]string{"4"}, 4, false, assetdata.DownloadSelection{Region: assetdata.RegionBoth, Platform: assetdata.PlatformBoth, Language: assetdata.LanguageAll}},
		{[]string{"4", "--region", "gl", "--platform", "android", "--language", "ko"}, 4, true, assetdata.DownloadSelection{Region: assetdata.RegionGL, Platform: assetdata.PlatformAndroid, Language: assetdata.LanguageKO}},
		{[]string{"--region=jp", "--platform=ios", "--language=ja"}, 8, true, assetdata.DownloadSelection{Region: assetdata.RegionJP, Platform: assetdata.PlatformIOS, Language: assetdata.LanguageJA}},
		{[]string{"--region", "both"}, 8, true, assetdata.DownloadSelection{Region: assetdata.RegionBoth, Platform: assetdata.PlatformBoth, Language: assetdata.LanguageAll}},
	} {
		got, err := ParseDownloadOptions(c.args)
		if err != nil || got.Workers != c.workers || got.Scoped != c.scoped || !reflect.DeepEqual(got.Selection, c.selection) {
			t.Errorf("%v: got %+v %v", c.args, got, err)
		}
	}
}

func TestInstalledDownloadProfileReadsOnlyItsCatalog(t *testing.T) {
	root := filepath.Join(t.TempDir(), "assets # test %")
	for _, entry := range []struct {
		directory, filename, exclusive string
		profile                        assetdata.AssetProfile
	}{
		{"gl", "asset_a_ko.db", "glandroid", assetdata.AssetProfile{Region: assetdata.RegionGL, Platform: assetdata.PlatformAndroid, Language: assetdata.LanguageKO}},
		{"gl", "asset_i_ko.db", "glios", assetdata.AssetProfile{Region: assetdata.RegionGL, Platform: assetdata.PlatformIOS, Language: assetdata.LanguageKO}},
		{"jp", "asset_a_ja.db", "jpandroid", assetdata.AssetProfile{Region: assetdata.RegionJP, Platform: assetdata.PlatformAndroid, Language: assetdata.LanguageJA}},
		{"jp", "asset_i_ja.db", "jpios", assetdata.AssetProfile{Region: assetdata.RegionJP, Platform: assetdata.PlatformIOS, Language: assetdata.LanguageJA}},
	} {
		directory := filepath.Join(root, "db", entry.directory)
		if err := os.MkdirAll(directory, 0755); err != nil {
			t.Fatal(err)
		}
		database, err := sql.Open("sqlite", filepath.Join(directory, entry.filename))
		if err != nil {
			t.Fatal(err)
		}
		defer database.Close()
		for _, command := range []string{
			`CREATE TABLE metapack(metapack_name TEXT)`,
			`CREATE TABLE m_asset_package_mapping(pack_name TEXT, metapack_name TEXT)`,
			`INSERT INTO metapack VALUES ('shared-meta')`,
			`INSERT INTO m_asset_package_mapping VALUES ('slice','shared-meta'),('common',NULL),('common',NULL)`,
		} {
			if _, err := database.Exec(command); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := database.Exec(`INSERT INTO m_asset_package_mapping VALUES (?,NULL)`, entry.exclusive); err != nil {
			t.Fatal(err)
		}
		files := map[string]struct{}{}
		if err := readInstalledDownloadProfile(root, entry.profile, files); err != nil {
			t.Fatal(err)
		}
		if want := (map[string]struct{}{entry.exclusive: {}, "common": {}, "shared-meta": {}}); !reflect.DeepEqual(files, want) {
			t.Fatalf("%s files = %v, want %v", entry.profile, files, want)
		}
	}
	profile := assetdata.AssetProfile{Region: assetdata.RegionGL, Platform: assetdata.PlatformIOS, Language: assetdata.LanguageZH}
	if err := readInstalledDownloadProfile(root, profile, map[string]struct{}{}); err == nil {
		t.Fatal("missing catalog was admitted")
	}
	if _, err := os.Stat(filepath.Join(root, "db", "gl", "asset_i_zh.db")); !os.IsNotExist(err) {
		t.Fatalf("missing catalog must stay absent, got %v", err)
	}
}

func TestParseDownloadOptionsRejectsBadArguments(t *testing.T) {
	for _, args := range [][]string{
		{"0"}, {"-1"}, {"not-a-worker"}, {"--region", "xx"}, {"--platform", "a"},
		{"--language", "de"}, {"--region", "gl", "--language", "ja"},
		{"--region", "jp", "--language", "en"}, {"--region", "both", "--language", "ko"},
		{"--region="}, {"--language="}, {"--platform="}, {"--region"}, {"--unknown", "gl"},
		{"8", "2"}, {"--region", "gl", "4"},
	} {
		if _, err := ParseDownloadOptions(args); err == nil {
			t.Errorf("invalid args accepted: %v", args)
		}
	}
}

func TestDownloadMissingRejectsScopeBeforeReadingCDNConfig(t *testing.T) {
	// An invalid selection must fail before reading CDN configuration or starting workers.
	previous := config.Conf
	config.Conf = nil
	t.Cleanup(func() { config.Conf = previous })
	if err := DownloadMissing(2, assetdata.DownloadSelection{Region: assetdata.Region("bad")}); err == nil {
		t.Fatal("invalid selection accepted")
	}
}
