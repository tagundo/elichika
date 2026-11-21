package clientdb

import (
	"bytes"
	"crypto/md5"
	"database/sql"
	"encoding/hex"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"elichika/assetdata"
	"elichika/config"
)

func catalogManifestFixture(t *testing.T) (string, string, map[string][]byte) {
	t.Helper()
	root := t.TempDir()
	base := filepath.Join(root, "db") + "/"
	previousStaticPath := config.StaticDataPath
	t.Cleanup(func() { config.StaticDataPath = previousStaticPath })
	config.StaticDataPath = filepath.Join(root, "static") + "/"
	plain := map[string][]byte{}
	m := &manifest{Version: "0000000000000000", Lang: "en"}
	for index, name := range []string{"asset_a_en.db", "asset_i_en.db", "asset_a_ja.db", "masterdata.db"} {
		data := make([]byte, 4096)
		copy(data, sqliteSignature)
		rand.New(rand.NewSource(int64(index))).Read(data[len(sqliteSignature):])
		plain[name] = data
		rekeyTestWrite(t, base+name, data)
		ref := makeFileReference(m.Version, name, rekeyTestSHA(data))
		ref.EncryptedSHA, ref.Size = rekeyTestSHA(nil), 128
		m.Files = append(m.Files, ref)
	}
	manifestName := "masterdata_a_en"
	rekeyTestWrite(t, base+manifestName, m.serialize())
	return base, manifestName, plain
}

func assertCatalogStageClean(t *testing.T) {
	t.Helper()
	paths, err := filepath.Glob(filepath.Join(filepath.Dir(filepath.Clean(config.StaticDataPath)), ".client-catalogs-*"))
	if err != nil || len(paths) != 0 {
		t.Fatalf("prepared catalogs remain on disk: %v, %v", paths, err)
	}
}

func TestClientDBPublishesDerivedGlobalCatalogWithoutChangingOriginal(t *testing.T) {
	base, manifestName, plain := catalogManifestFixture(t)
	// Existing sidecar changes bypass preparation even for a matching database name.
	rekeyTestWrite(t, base+"asset_i_en.db-wal", []byte("uncheckpointed changes"))
	derived := append(bytes.Clone(plain["asset_a_en.db"]), "filtered mapping"...)
	updateClientDbWithCatalogs(base, []string{manifestName}, 4, func() (prepareClientCatalog, error) {
		return func(source, destination string) (int64, error) {
			if source != filepath.Join(base, "asset_a_en.db") || filepath.Base(destination) != "asset_a_en.db" {
				return 0, fmt.Errorf("unexpected prepared catalog %q to %q", source, destination)
			}
			return 1, os.WriteFile(destination, derived, 0600)
		}, nil
	})
	m := rekeyTestManifest(t, base+manifestName)
	if m.Version == "0000000000000000" {
		t.Fatal("served catalog did not receive a new version")
	}
	outputDir := filepath.Join(config.StaticDataPath, m.Version)
	if !bytes.Equal(rekeyTestRead(t, base+manifestName), rekeyTestRead(t, filepath.Join(outputDir, manifestName))) {
		t.Fatal("installed and served headers differ")
	}
	var versionBytes []byte
	for _, ref := range m.Files {
		if !bytes.Equal(plain[ref.Name], rekeyTestRead(t, base+ref.Name)) {
			t.Fatalf("original clear database changed: %s", ref.Name)
		}
		data := plain[ref.Name]
		if ref.Name == "asset_a_en.db" {
			data = derived
		}
		versionBytes = append(versionBytes, rekeyTestSHA(data)...)
		expected := originalRekeyOracle(t, data, ref)
		if ref.SHA != rekeyTestSHA(data) || ref.EncryptedSHA != rekeyTestSHA(expected) || ref.Size != len(expected) ||
			!bytes.Equal(expected, rekeyTestRead(t, filepath.Join(outputDir, ref.Name))) {
			t.Fatalf("served file and manifest did not use the same input: %s", ref.Name)
		}
	}
	expectedVersion := md5.Sum(versionBytes)
	if m.Version != versionString(hex.EncodeToString(expectedVersion[:])) {
		t.Fatal("regional version did not use the derived catalog hash")
	}
	assertCatalogStageClean(t)
}

func TestClientDBRejectsChangesToDerivedCatalogInputs(t *testing.T) {
	for _, name := range []string{"asset_a_en.db", "asset_a_en.db-journal", "masterdata.db", "masterdata.db-wal"} {
		t.Run(name, func(t *testing.T) {
			base, manifestName, _ := catalogManifestFixture(t)
			before := rekeyTestRead(t, base+manifestName)
			change := func() error {
				return os.WriteFile(filepath.Join(base, name), append([]byte(sqliteSignature), []byte("owner edit")...), 0600)
			}
			expectManifestPanic(t, func() {
				updateClientDbWithCatalogs(base, []string{manifestName}, 1, func() (prepareClientCatalog, error) {
					masterChanged := name == "masterdata.db" || name == "masterdata.db-wal"
					if masterChanged {
						if err := change(); err != nil {
							return nil, err
						}
					}
					return func(source, destination string) (int64, error) {
						if filepath.Base(source) != "asset_a_en.db" {
							return 0, nil
						}
						if err := os.WriteFile(destination, append([]byte(sqliteSignature), []byte("derived")...), 0600); err != nil {
							return 0, err
						}
						if !masterChanged {
							return 1, change()
						}
						return 1, nil
					}, nil
				})
			})
			if !bytes.Equal(before, rekeyTestRead(t, base+manifestName)) {
				t.Fatal("an original source change published a manifest")
			}
			matches, err := filepath.Glob(filepath.Join(config.StaticDataPath, "*", manifestName))
			if err != nil || len(matches) != 0 {
				t.Fatalf("an original source change published a CDN manifest: %v, %v", matches, err)
			}
			assertCatalogStageClean(t)
		})
	}
}

func TestScopedDownloadUsesPreparedGlobalCatalog(t *testing.T) {
	base, manifestName, _ := catalogManifestFixture(t)
	source := filepath.Join(base, "asset_a_en.db")
	if err := os.Remove(source); err != nil {
		t.Fatal(err)
	}
	writeCatalog := func(path, mappings string) error {
		database, err := sql.Open("sqlite", path)
		if err != nil {
			return err
		}
		defer database.Close()
		_, err = database.Exec(`CREATE TABLE metapack (metapack_name TEXT PRIMARY KEY);
			CREATE TABLE m_asset_package_mapping (pack_name TEXT, metapack_name TEXT);
			INSERT INTO metapack VALUES ('ind001'), ('keep01'), ('drop01');
			INSERT INTO m_asset_package_mapping VALUES ` + mappings)
		return err
	}
	const kept = `('gl0001', NULL), ('gl0002', 'keep01')`
	if err := writeCatalog(source, kept+`, ('jp0001', NULL), ('jp0002', 'drop01')`); err != nil {
		t.Fatal(err)
	}
	previousArgs := os.Args
	t.Cleanup(func() { os.Args = previousArgs })
	os.Args = []string{os.Args[0], "download_packs", "4", "--region", "gl"}
	updateClientDbWithCatalogs(base, []string{manifestName}, 1, func() (prepareClientCatalog, error) {
		return func(path, destination string) (int64, error) {
			if path != source {
				return 0, nil
			}
			return 2, writeCatalog(destination, kept)
		}, nil
	})
	selection := assetdata.DownloadSelection{
		Region: assetdata.RegionGL, Platform: assetdata.PlatformAndroid, Language: assetdata.LanguageEN,
	}
	names, err := assetdata.SelectWholeFilesWithFallback(selection, func(assetdata.AssetProfile, map[string]struct{}) error {
		return fmt.Errorf("the original profile was selected")
	})
	want := map[string]struct{}{"gl0001": {}, "keep01": {}, "ind001": {}}
	if err != nil || !reflect.DeepEqual(names, want) {
		t.Fatalf("scoped names = %v, %v; want %v", names, err, want)
	}
	assertCatalogStageClean(t)
}
