package upgrades

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func managedTestWrite(t *testing.T, root, relative string, data []byte) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func managedTestState(t *testing.T) (string, managedContentState) {
	t.Helper()
	root := t.TempDir()
	state := managedContentState{
		ContractVersion: 1, PayloadVersion: "test-upgrade-2", Algorithm: "test-content-v1", Integrated: true,
		BaselineFormat: 1, BaselineIndex: ".payload-upgrade/baseline.sqlite",
		IncomingDatabases: map[string]managedContentInput{},
	}
	// This guard checks an installer's committed protocol, not SQLite contents.
	// The merge engine's integration tests use real DBs and integrity checks.
	header := append([]byte("SQLite format 3\x00"), make([]byte, 100)...)
	addDB := func(relative string) {
		managedTestWrite(t, root, relative, header)
		state.IncomingDatabases[relative] = managedContentInput{SHA256: strings.Repeat("a", 64), Bytes: 4096}
	}
	addPair := func(source, target string) {
		addDB(source)
		addDB(target)
		state.Coverage = append(state.Coverage, managedContentCoverage{Source: source, Target: target, SourceSHA: strings.Repeat("a", 64), Algorithm: state.Algorithm})
	}
	addPair("assets/db/jp/masterdata.db", "assets/db/gl/masterdata.db")
	for _, platform := range []string{"a", "i"} {
		for _, language := range []string{"en", "ko", "zh"} {
			addPair("assets/db/jp/asset_"+platform+"_ja.db", "assets/db/gl/asset_"+platform+"_"+language+".db")
		}
	}
	for _, language := range []string{"ja", "en", "ko", "zh"} {
		region := "gl"
		if language == "ja" {
			region = "jp"
		}
		addDB("assets/db/" + region + "/dictionary_" + language + "_k.db")
	}
	managedTestWrite(t, root, state.BaselineIndex, header)
	managedTestWrite(t, root, "installed_version", []byte(state.PayloadVersion))
	return root, state
}

func managedTestSave(t *testing.T, root string, state managedContentState) {
	t.Helper()
	data, err := json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	managedTestWrite(t, root, ".payload-upgrade/current.json", data)
}

func TestManagedContentAbsentPreservesStandaloneImporter(t *testing.T) {
	managed, err := managedJapaneseContent(filepath.Join(t.TempDir(), "assets"), "test-content-v1")
	if err != nil || managed {
		t.Fatalf("standalone importer was changed: managed=%v error=%v", managed, err)
	}
}

func TestManagedContentAcceptsCommittedCatalogAndLaterOwnerMods(t *testing.T) {
	root, state := managedTestState(t)
	managedTestSave(t, root, state)
	for _, phase := range []string{"committed", "owner later modified regional DB"} {
		if phase != "committed" {
			// No fingerprint equality with live DBs: a later JP-only mod must not
			// accidentally trigger a second JP-to-GL import on server restart.
			changed := append([]byte("SQLite format 3\x00"), []byte(strings.Repeat("owner mod", 100))...)
			managedTestWrite(t, root, "assets/db/jp/masterdata.db", changed)
		}
		managed, err := managedJapaneseContent(filepath.Join(root, "assets"), state.Algorithm)
		if err != nil || !managed {
			t.Fatalf("%s: committed catalog not recognized: %v", phase, err)
		}
	}
}

func TestManagedContentRejectsPartialOrStaleCommitBeforeImport(t *testing.T) {
	cases := []struct {
		name string
		edit func(*testing.T, string, *managedContentState)
	}{
		{"stale version", func(t *testing.T, root string, s *managedContentState) { s.PayloadVersion = "old-version" }},
		{"future contract", func(t *testing.T, root string, s *managedContentState) { s.ContractVersion++ }},
		{"wrong importer algorithm", func(t *testing.T, root string, s *managedContentState) { s.Algorithm = "old-algorithm" }},
		{"incomplete content", func(t *testing.T, root string, s *managedContentState) { s.Integrated = false }},
		{"missing coverage", func(t *testing.T, root string, s *managedContentState) { s.Coverage = s.Coverage[:6] }},
		{"duplicate coverage", func(t *testing.T, root string, s *managedContentState) { s.Coverage[6] = s.Coverage[0] }},
		{"platform mix", func(t *testing.T, root string, s *managedContentState) {
			s.Coverage[1].Source = "assets/db/jp/asset_i_ja.db"
		}},
		{"wrong source fingerprint", func(t *testing.T, root string, s *managedContentState) {
			s.Coverage[0].SourceSHA = strings.Repeat("b", 64)
		}},
		{"malformed provenance", func(t *testing.T, root string, s *managedContentState) {
			s.IncomingDatabases["assets/db/jp/masterdata.db"] = managedContentInput{SHA256: "bad", Bytes: 4096}
		}},
		{"missing dictionary provenance", func(t *testing.T, root string, s *managedContentState) {
			delete(s.IncomingDatabases, "assets/db/gl/dictionary_ko_k.db")
		}},
		{"restored databases require rebase", func(t *testing.T, root string, s *managedContentState) {
			managedTestWrite(t, root, ".payload-upgrade/needs-rebase", []byte("database_restore"))
		}},
		{"missing baseline", func(t *testing.T, root string, s *managedContentState) {
			if err := os.Remove(filepath.Join(root, s.BaselineIndex)); err != nil {
				t.Fatal(err)
			}
		}},
		{"missing retained database", func(t *testing.T, root string, s *managedContentState) {
			if err := os.Remove(filepath.Join(root, "assets/db/gl/asset_a_ko.db")); err != nil {
				t.Fatal(err)
			}
		}},
		{"corrupt retained database header", func(t *testing.T, root string, s *managedContentState) {
			managedTestWrite(t, root, "assets/db/gl/masterdata.db", []byte(strings.Repeat("broken", 30)))
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root, state := managedTestState(t)
			tc.edit(t, root, &state)
			managedTestSave(t, root, state)
			managed, err := managedJapaneseContent(filepath.Join(root, "assets"), "test-content-v1")
			if err == nil || managed {
				t.Fatal("unsafe managed state would fall through to a regional import")
			}
		})
	}
}

func TestManagedContentRejectsMalformedAndOversizedMetadata(t *testing.T) {
	for _, value := range []string{"{", "{} {}", strings.Repeat(" ", 1024*1024+1)} {
		root, state := managedTestState(t)
		managedTestWrite(t, root, ".payload-upgrade/current.json", []byte(value))
		if managed, err := managedJapaneseContent(filepath.Join(root, "assets"), state.Algorithm); managed || err == nil {
			t.Fatal("malformed state accepted")
		}
	}
}
