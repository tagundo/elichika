package clientdb

import (
	"bytes"
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"testing"

	"elichika/config"
)

func workerManifestFixture(t *testing.T) (string, []string, string, map[string][]byte) {
	t.Helper()
	base := filepath.Join(t.TempDir(), "db") + "/"
	plain := map[string][]byte{}
	refs := make([]FileReference, 10)
	for index := range refs {
		name := fmt.Sprintf("source_%02d.db", index)
		data := make([]byte, 32772+index)
		copy(data, sqliteSignature)
		rand.New(rand.NewSource(int64(index))).Read(data[len(sqliteSignature):])
		plain[name] = data
		rekeyTestWrite(t, base+name, data)
		refs[index] = makeFileReference("0000000000000000", name, rekeyTestSHA(data))
		refs[index].EncryptedSHA, refs[index].Size = rekeyTestSHA(nil), 7
	}
	var paths []string
	var versionBytes []byte
	// Shared source_00 occurs in all three headers. Their remaining order is
	// deliberately different from lexical order and must survive parallel work.
	for index, indices := range [][]int{{0, 4, 2, 1, 3}, {0, 6, 5}, {0, 9, 7, 8}} {
		locale := []string{"en", "ko", "zh"}[index]
		m := &manifest{Version: "0000000000000000", Lang: locale}
		for _, source := range indices {
			m.Files = append(m.Files, refs[source])
			versionBytes = append(versionBytes, refs[source].SHA...)
		}
		name := "masterdata_a_" + locale
		paths = append(paths, name)
		rekeyTestWrite(t, base+name, m.serialize())
	}
	version := md5.Sum(versionBytes)
	return base, paths, versionString(hex.EncodeToString(version[:])), plain
}

func TestParallelClientDBPreservesOriginalVersionOrderAndCipherBytes(t *testing.T) {
	previousPath := config.StaticDataPath
	t.Cleanup(func() { config.StaticDataPath = previousPath })
	var expectedManifests map[string][]byte
	for _, workers := range []int{1, 2, 4, 8} {
		t.Run(fmt.Sprint(workers), func(t *testing.T) {
			base, paths, version, plain := workerManifestFixture(t)
			config.StaticDataPath = filepath.Join(t.TempDir(), "static") + "/"
			updateClientDbWithWorkers(base, paths, workers)
			current := map[string][]byte{}
			for _, name := range paths {
				m := rekeyTestManifest(t, base+name)
				if m.Version != version {
					t.Fatalf("parallel version changed from original concat order: %s != %s", m.Version, version)
				}
				current[name] = rekeyTestRead(t, base+name)
				if !bytes.Equal(current[name], rekeyTestRead(t, config.StaticDataPath+version+"/"+name)) {
					t.Fatal("CDN and installed headers differ")
				}
				for _, ref := range m.Files {
					expected := originalRekeyOracle(t, plain[ref.Name], ref)
					if !bytes.Equal(expected, rekeyTestRead(t, config.StaticDataPath+version+"/"+ref.Name)) || ref.Size != len(expected) || ref.EncryptedSHA != rekeyTestSHA(expected) {
						t.Fatal("parallel client output differs from pre-streaming codec")
					}
					if !bytes.Equal(plain[ref.Name], rekeyTestRead(t, base+ref.Name)) {
						t.Fatal("clear source modified")
					}
				}
			}
			if expectedManifests == nil {
				expectedManifests = current
			}
			for name, expected := range expectedManifests {
				if !bytes.Equal(expected, current[name]) {
					t.Fatalf("worker count changed manifest bytes: %s", name)
				}
			}
		})
	}
}

func TestParallelClientDBOutputFailureNeverPublishesAnyHeader(t *testing.T) {
	base, paths, version, _ := workerManifestFixture(t)
	previousPath := config.StaticDataPath
	config.StaticDataPath = filepath.Join(t.TempDir(), "static") + "/"
	t.Cleanup(func() { config.StaticDataPath = previousPath })
	before := map[string][]byte{}
	for _, name := range paths {
		before[name] = rekeyTestRead(t, base+name)
		rekeyTestWrite(t, config.StaticDataPath+version+"/"+name, before[name])
	}
	// A worker can finish compression/verification but fail the final rename.
	// Other workers must all join without any old header being replaced.
	blocked := config.StaticDataPath + version + "/source_04.db"
	rekeyTestWrite(t, filepath.Join(blocked, "keep"), []byte("preserve destination"))
	expectManifestPanic(t, func() { updateClientDbWithWorkers(base, paths, 4) })
	for _, name := range paths {
		if !bytes.Equal(before[name], rekeyTestRead(t, base+name)) || !bytes.Equal(before[name], rekeyTestRead(t, config.StaticDataPath+version+"/"+name)) {
			t.Fatal("a failed worker published a partial regional manifest set")
		}
	}
	if string(rekeyTestRead(t, filepath.Join(blocked, "keep"))) != "preserve destination" {
		t.Fatal("failed worker changed destination")
	}
	if err := filepath.Walk(config.StaticDataPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && (bytes.HasPrefix([]byte(info.Name()), []byte(".rekey-")) || bytes.HasPrefix([]byte(info.Name()), []byte(".manifest-"))) {
			t.Fatalf("worker left unfinished output: %s", path)
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}

func TestClientDBRejectsUnsupportedExplicitWorkerLimitBeforeWriting(t *testing.T) {
	base, paths, _, _ := workerManifestFixture(t)
	before := rekeyTestRead(t, base+paths[0])
	for _, invalid := range []int{-1, 3, 9, 100} {
		expectManifestPanic(t, func() { updateClientDbWithWorkers(base, paths, invalid) })
		if !bytes.Equal(before, rekeyTestRead(t, base+paths[0])) {
			t.Fatal("invalid worker limit changed a header")
		}
	}
}
