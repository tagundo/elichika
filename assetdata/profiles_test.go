package assetdata

import (
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
)

func profileNames(t *testing.T, selection DownloadSelection) []string {
	t.Helper()
	names, err := SelectWholeFiles(selection)
	if err != nil {
		t.Fatal(err)
	}
	result := make([]string, 0, len(names))
	for name := range names {
		result = append(result, name)
	}
	sort.Strings(result)
	return result
}

func loadProfileFixture(t *testing.T, profile AssetProfile) {
	t.Helper()
	engine := packEngine(t, filepath.Join(t.TempDir(), "profile.db"))
	for _, query := range []string{
		`CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY,file_size INTEGER,category INTEGER)`,
		`CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER)`,
		`INSERT INTO metapack VALUES('shared-meta',200,1)`,
		`INSERT INTO m_asset_package_mapping VALUES('slice','member',100,'shared-meta',0,1),('again','member',100,'shared-meta',0,1),('common','common',10,NULL,0,1)`,
	} {
		if _, err := engine.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"lang-" + string(profile.Language), "common-" + string(profile.Platform), string(profile.Region) + "-" + string(profile.Platform)} {
		if _, err := engine.Exec(`INSERT INTO m_asset_package_mapping VALUES('fixture',?,10,NULL,0,1)`, name); err != nil {
			t.Fatal(err)
		}
	}
	if profile.Platform == PlatformAndroid {
		var meta any
		if profile.Region == RegionGL {
			meta = "shared-meta"
		}
		if _, err := engine.Exec(`INSERT INTO m_asset_package_mapping VALUES('mixed','mixed',20,?,0,1)`, meta); err != nil {
			t.Fatal(err)
		}
	}
	if err := InitProfile(profile, engine); err != nil {
		t.Fatal(err)
	}
}

func TestScopedWholeFilesSharingLanguagesAndLoadOrder(t *testing.T) {
	for _, reverse := range []bool{false, true} {
		t.Run(map[bool]string{false: "forward", true: "reverse"}[reverse], func(t *testing.T) {
			resetPackFixture(t)
			for i := range sourceProfiles {
				index := i
				if reverse {
					index = len(sourceProfiles) - 1 - i
				}
				loadProfileFixture(t, sourceProfiles[index])
			}
			cases := []struct {
				selection DownloadSelection
				want      []string
			}{
				{DownloadSelection{RegionGL, PlatformAndroid, LanguageEN}, []string{"common", "common-android", "gl-android", "lang-en", "shared-meta"}},
				{DownloadSelection{RegionGL, PlatformAndroid, LanguageAll}, []string{"common", "common-android", "gl-android", "lang-en", "lang-ko", "lang-zh", "shared-meta"}},
				{DownloadSelection{RegionJP, PlatformAndroid, LanguageJA}, []string{"common", "common-android", "jp-android", "lang-ja", "mixed", "shared-meta"}},
				{DownloadSelection{RegionBoth, PlatformIOS, LanguageAll}, []string{"common", "common-ios", "gl-ios", "jp-ios", "lang-en", "lang-ja", "lang-ko", "lang-zh", "shared-meta"}},
			}
			for _, c := range cases {
				if got := profileNames(t, c.selection); !reflect.DeepEqual(got, c.want) {
					t.Errorf("%s: got %v want %v", c.selection, got, c.want)
				}
			}
			all := profileNames(t, DownloadSelection{})
			if len(all) != 13 || ProfileWholeFileCount() != 13 {
				t.Fatalf("all-profile union not deduplicated: %v", all)
			}
			// NameToLocale retains one owner, while membership includes every source.
			if got := profileNames(t, DownloadSelection{RegionJP, PlatformIOS, LanguageJA}); len(got) != 5 {
				t.Fatalf("shared first-owner file was omitted: %v", got)
			}
		})
	}
}

func TestScopedWholeFilesRejectInvalidAndMissingProfiles(t *testing.T) {
	resetPackFixture(t)
	loadProfileFixture(t, AssetProfile{RegionGL, PlatformAndroid, LanguageEN})
	for _, selection := range []DownloadSelection{
		{Region("typo"), PlatformAndroid, LanguageEN}, {RegionGL, Platform("typo"), LanguageEN},
		{RegionGL, PlatformAndroid, Language("typo")}, {RegionGL, PlatformAndroid, LanguageJA},
		{RegionJP, PlatformAndroid, LanguageKO}, {RegionBoth, PlatformAndroid, LanguageEN},
		{RegionGL, PlatformBoth, LanguageEN}, {RegionGL, PlatformAndroid, LanguageAll}, {},
	} {
		if names, err := SelectWholeFiles(selection); err == nil || names != nil {
			t.Errorf("%s silently returned a union: %v %v", selection, names, err)
		}
	}
	if _, err := SelectWholeFiles(DownloadSelection{RegionGL, PlatformBoth, LanguageEN}); err == nil || !strings.Contains(err.Error(), "gl/ios/en") {
		t.Fatalf("missing profile not identified: %v", err)
	}
	if err := InitProfile(AssetProfile{RegionJP, PlatformAndroid, LanguageEN}, nil); err == nil {
		t.Fatal("invalid source profile accepted")
	}
}

func TestLegacyInitDoesNotInferAPlatform(t *testing.T) {
	resetPackFixture(t)
	profile := AssetProfile{RegionGL, PlatformAndroid, LanguageEN}
	loadProfileFixture(t, profile)
	// Repeat the same DB through the compatibility entrypoint with membership reset.
	loadedProfiles, wholeFileProfiles = 0, map[string]profileMask{}
	engine := packEngine(t, filepath.Join(t.TempDir(), "legacy.db"))
	for _, query := range []string{
		`CREATE TABLE metapack(metapack_name TEXT PRIMARY KEY,file_size INTEGER,category INTEGER)`,
		`CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER,category INTEGER)`,
		`INSERT INTO m_asset_package_mapping VALUES('old','legacy',11,NULL,0,1)`,
	} {
		if _, err := engine.Exec(query); err != nil {
			t.Fatal(err)
		}
	}
	Init("en", engine)
	if _, ok := AllWholeFiles()["legacy"]; !ok {
		t.Fatal("legacy whole file was lost")
	}
	if names, err := SelectWholeFiles(DownloadSelection{RegionGL, PlatformAndroid, LanguageEN}); err == nil || names != nil {
		t.Fatalf("legacy Init silently invented profile membership: %v %v", names, err)
	}
}
