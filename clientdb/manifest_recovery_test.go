package clientdb

import (
	"bytes"
	"crypto/sha1"
	"os"
	"path/filepath"
	"testing"
	"time"

	"elichika/config"
)

func expectManifestPanic(t *testing.T, action func()) {
	t.Helper()
	defer func() {
		if recover() == nil {
			t.Fatal("expected invalid input/publication to fail")
		}
	}()
	action()
}

func TestUpdateClientDBRecoversInterruptedManifestPublication(t *testing.T) {
	for _, alreadyCurrent := range []int{0, 1, 2} {
		t.Run([]string{"first-current", "middle-current", "last-current"}[alreadyCurrent], func(t *testing.T) {
			base, static, version, plain, expected, ref := rekeyTestFixture(t)
			previousPath := config.StaticDataPath
			config.StaticDataPath = static
			t.Cleanup(func() { config.StaticDataPath = previousPath })
			paths := rekeyTestManifests(t, base, "0000000000000000", ref)
			current := rekeyTestManifest(t, base+paths[alreadyCurrent])
			current.Version = version
			rekeyTestWrite(t, base+paths[alreadyCurrent], current.serialize())
			updateClientDb(base, paths)
			for _, path := range paths {
				m := rekeyTestManifest(t, base+path)
				if m.Version != version || m.Lang != path[len(path)-2:] || m.Files[0].SHA != rekeyTestSHA(plain) || m.Files[0].EncryptedSHA != rekeyTestSHA(expected) {
					t.Fatal("recovered manifest lost its locale or current DB reference")
				}
				if !bytes.Equal(rekeyTestRead(t, base+path), rekeyTestRead(t, static+version+"/"+path)) {
					t.Fatal("installed/CDN manifest mismatch after recovery")
				}
			}
			if !bytes.Equal(rekeyTestRead(t, base+"masterdata.db"), plain) {
				t.Fatal("recovery replaced the installed clear database")
			}
			stamp := time.Unix(1500000000, 0)
			for _, path := range paths {
				if err := os.Chtimes(base+path, stamp, stamp); err != nil {
					t.Fatal(err)
				}
			}
			updateClientDb(base, paths)
			for _, path := range paths {
				info, err := os.Stat(base + path)
				if err != nil || !info.ModTime().Equal(stamp) {
					t.Fatal("healthy restart unnecessarily rewrote a manifest")
				}
			}
		})
	}
}

func TestUpdateClientDBPreservesAdditionalModDatabaseReference(t *testing.T) {
	base, static, _, _, _, ref := rekeyTestFixture(t)
	previousPath := config.StaticDataPath
	config.StaticDataPath = static
	t.Cleanup(func() { config.StaticDataPath = previousPath })
	paths := rekeyTestManifests(t, base, "0000000000000000", ref)
	mod := append([]byte("SQLite format 3\x00"), []byte("mod-owned installed DB bytes")...)
	rekeyTestWrite(t, base+"custom_mod.db", mod)
	m := rekeyTestManifest(t, base+paths[1])
	custom := makeFileReference("1111111111111111", "custom_mod.db", rekeyTestSHA(mod))
	custom.EncryptedSHA, custom.Size = ref.EncryptedSHA, ref.Size
	m.Version = custom.Version
	m.Files = append(m.Files, custom)
	rekeyTestWrite(t, base+paths[1], m.serialize())
	updateClientDb(base, paths)
	m = rekeyTestManifest(t, base+paths[1])
	if len(m.Files) != 2 || m.Files[1].Name != custom.Name || m.Files[1].SHA != custom.SHA || !bytes.Equal(rekeyTestRead(t, base+custom.Name), mod) {
		t.Fatal("recovery lost the additional mod DB or replaced its contents")
	}
	if len(rekeyTestManifest(t, base+paths[0]).Files) != 1 {
		t.Fatal("recovery copied locale-specific references into another locale")
	}
}

func TestUpdateClientDBInvalidSourceDoesNotPublishHeaders(t *testing.T) {
	for _, missing := range []bool{false, true} {
		t.Run(map[bool]string{false: "not-sqlite", true: "missing"}[missing], func(t *testing.T) {
			base, static, _, _, _, ref := rekeyTestFixture(t)
			previousPath := config.StaticDataPath
			config.StaticDataPath = static
			t.Cleanup(func() { config.StaticDataPath = previousPath })
			paths := rekeyTestManifests(t, base, "0000000000000000", ref)
			before := rekeyTestRead(t, base+paths[0])
			if missing {
				if err := os.Remove(base + "masterdata.db"); err != nil {
					t.Fatal(err)
				}
			} else {
				rekeyTestWrite(t, base+"masterdata.db", []byte("not a SQLite database"))
			}
			expectManifestPanic(t, func() { updateClientDb(base, paths) })
			for _, path := range paths {
				after := rekeyTestManifest(t, base+path)
				if after.Version != "0000000000000000" || (path == paths[0] && !bytes.Equal(rekeyTestRead(t, base+path), before)) {
					t.Fatal("failed source validation published a new header")
				}
			}
		})
	}
}

func TestManifestParserRejectsCorruptionAndUnsafeReferences(t *testing.T) {
	base, _, version, _, _, ref := rekeyTestFixture(t)
	valid := (&manifest{Version: version, Lang: "ko", Files: []FileReference{ref}}).serialize()
	cases := map[string][]byte{
		"truncated": valid[:len(valid)-1],
		"checksum":  append([]byte(nil), valid...),
		"trailing":  append(append([]byte(nil), valid...), 0),
	}
	cases["checksum"][21] ^= 1
	for _, name := range []string{"../masterdata.db", "sub/file.db", "", ".db"} {
		bad := ref
		bad.Name = name
		cases["path-"+name] = (&manifest{Version: version, Lang: "ko", Files: []FileReference{bad}}).serialize()
	}
	cases["duplicate"] = (&manifest{Version: version, Lang: "ko", Files: []FileReference{ref, ref}}).serialize()
	cases["bad-version"] = (&manifest{Version: "not-a-version", Lang: "ko", Files: []FileReference{ref}}).serialize()
	// Even an intact outer checksum cannot make a truncated body valid.
	short := append([]byte(nil), valid[:len(valid)-5]...)
	hash := sha1.Sum(short[20:])
	for i, value := range hash {
		short[i] = value
	}
	cases["truncated-valid-checksum"] = short
	for name, data := range cases {
		t.Run(name, func(t *testing.T) {
			path := base + "invalid-manifest"
			rekeyTestWrite(t, path, data)
			expectManifestPanic(t, func() { rekeyTestManifest(t, path) })
		})
	}
}

func TestPublishManifestsStagesAllBytesBeforeReplacing(t *testing.T) {
	root := t.TempDir()
	first := filepath.Join(root, "first")
	rekeyTestWrite(t, first, []byte("original"))
	expectManifestPanic(t, func() {
		publishManifests([]manifestWrite{{first, []byte("replacement")}, {filepath.Join(root, "missing", "second"), []byte("new")}})
	})
	if string(rekeyTestRead(t, first)) != "original" {
		t.Fatal("staging failure replaced an earlier manifest")
	}
	temporaries, err := filepath.Glob(filepath.Join(root, ".manifest-*"))
	if err != nil || len(temporaries) != 0 {
		t.Fatal("failed staging left a temporary manifest")
	}
}

func TestPublishManifestRenameFailurePreservesDestination(t *testing.T) {
	root := t.TempDir()
	destination := filepath.Join(root, "directory")
	rekeyTestWrite(t, filepath.Join(destination, "keep"), []byte("original"))
	expectManifestPanic(t, func() { publishManifests([]manifestWrite{{destination, []byte("replacement")}}) })
	if string(rekeyTestRead(t, filepath.Join(destination, "keep"))) != "original" {
		t.Fatal("failed rename damaged the existing destination")
	}
	temporaries, err := filepath.Glob(filepath.Join(root, ".manifest-*"))
	if err != nil || len(temporaries) != 0 {
		t.Fatal("failed rename left a temporary manifest")
	}
}
