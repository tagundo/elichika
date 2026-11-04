package clientdb

import (
	"bytes"
	"compress/flate"
	"compress/zlib"
	"crypto/md5"
	"crypto/sha1"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"elichika/config"
	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

func rekeyTestSHA(data []byte) string {
	hash := sha1.Sum(data)
	return hex.EncodeToString(hash[:])
}

func rekeyTestWrite(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func rekeyTestRead(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func rekeyTestManifest(t *testing.T, path string) *manifest {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	return newManifest(file)
}

func rekeyTestFixture(t *testing.T) (string, string, string, []byte, []byte, FileReference) {
	t.Helper()
	root := t.TempDir()
	base := filepath.Join(root, "db") + "/"
	static := filepath.Join(root, "static") + "/"
	// The codec reads bytes, not SQLite tables. Include the required SQLite
	// signature and non-empty payload; the integration repro uses a real DB.
	plain := append([]byte("SQLite format 3\x00"), bytes.Repeat([]byte("synthetic database payload"), 400)...)
	for value := 0; value < 256; value++ {
		plain = append(plain, byte(value))
	}
	rekeyTestWrite(t, base+"masterdata.db", plain)
	clearSHA := rekeyTestSHA(plain)
	hash := md5.Sum([]byte(clearSHA + clearSHA + clearSHA))
	version := versionString(hex.EncodeToString(hash[:]))
	ref := makeFileReference(version, "masterdata.db", clearSHA)
	oracle := filepath.Join(root, "oracle/output")
	if err := os.MkdirAll(filepath.Dir(oracle), 0700); err != nil {
		t.Fatal(err)
	}
	rekey(base+"masterdata.db", oracle, &ref, keySpec)
	return base, static, version, plain, rekeyTestRead(t, oracle), ref
}

func rekeyTestManifests(t *testing.T, base, version string, ref FileReference) []string {
	t.Helper()
	var paths []string
	for _, language := range []string{"en", "ko", "zh"} {
		path := "masterdata_a_" + language
		m := manifest{Version: version, Lang: language, Files: []FileReference{ref}}
		rekeyTestWrite(t, base+path, m.serialize())
		paths = append(paths, path)
	}
	return paths
}

func TestUpdateClientDBRejectsExistingCorruptOutput(t *testing.T) {
	for _, sameVersion := range []bool{false, true} {
		for _, truncated := range []bool{false, true} {
			t.Run(map[bool]string{false: "new-version", true: "previously-adopted-same-version"}[sameVersion]+"/"+map[bool]string{false: "bitflip", true: "truncated"}[truncated], func(t *testing.T) {
				base, static, version, _, expected, ref := rekeyTestFixture(t)
				previousPath := config.StaticDataPath
				config.StaticDataPath = static
				t.Cleanup(func() { config.StaticDataPath = previousPath })
				bad := append([]byte(nil), expected...)
				if truncated {
					bad = bad[:len(bad)-1]
				} else {
					bad[0] ^= 0x80
				}
				output := static + version + "/masterdata.db"
				rekeyTestWrite(t, output, bad)
				oldVersion := "0000000000000000"
				if sameVersion {
					oldVersion = version
				} else {
					ref.SHA = "0000000000000000000000000000000000000000"
				}
				// Recreate a legacy manifest which already trusts the bad bytes.
				ref.EncryptedSHA, ref.Size = rekeyTestSHA(bad), len(bad)
				paths := rekeyTestManifests(t, base, oldVersion, ref)
				updateClientDb(base, paths)
				if !bytes.Equal(rekeyTestRead(t, output), expected) {
					t.Fatal("existing corrupt output survived authoritative validation")
				}
				for _, path := range paths {
					m := rekeyTestManifest(t, base+path)
					if m.Version != version || m.Files[0].EncryptedSHA != rekeyTestSHA(expected) || m.Files[0].Size != len(expected) {
						t.Fatal("shared manifest did not reference the repaired output")
					}
				}
				// Loading manifests again must keep the repaired version and bytes.
				updateClientDb(base, paths)
				if !bytes.Equal(rekeyTestRead(t, output), expected) {
					t.Fatal("repaired output changed on restart")
				}
			})
		}
	}
}

func TestUpdateClientDBReusesVerifiedSharedOutputWithoutWriting(t *testing.T) {
	for _, sameVersion := range []bool{false, true} {
		t.Run(map[bool]string{false: "new-version", true: "same-version"}[sameVersion], func(t *testing.T) {
			base, static, version, _, expected, ref := rekeyTestFixture(t)
			previousPath := config.StaticDataPath
			config.StaticDataPath = static
			t.Cleanup(func() { config.StaticDataPath = previousPath })
			output := static + version + "/masterdata.db"
			rekeyTestWrite(t, output, expected)
			stamp := time.Unix(1500000000, 0)
			if err := os.Chtimes(output, stamp, stamp); err != nil {
				t.Fatal(err)
			}
			oldVersion := version
			if !sameVersion {
				oldVersion = "0000000000000000"
				ref.SHA = "0000000000000000000000000000000000000000"
			}
			paths := rekeyTestManifests(t, base, oldVersion, ref)
			updateClientDb(base, paths)
			info, err := os.Stat(output)
			if err != nil || !info.ModTime().Equal(stamp) || !bytes.Equal(rekeyTestRead(t, output), expected) {
				t.Fatal("valid shared output was unnecessarily rewritten")
			}
		})
	}
}

func TestUpdateClientDBRestoresMissingStaticManifests(t *testing.T) {
	for _, outputExists := range []bool{false, true} {
		t.Run(map[bool]string{false: "missing-output", true: "valid-output"}[outputExists], func(t *testing.T) {
			base, static, version, _, expected, ref := rekeyTestFixture(t)
			previousPath := config.StaticDataPath
			config.StaticDataPath = static
			t.Cleanup(func() { config.StaticDataPath = previousPath })
			paths := rekeyTestManifests(t, base, version, ref)
			if outputExists {
				rekeyTestWrite(t, static+version+"/masterdata.db", expected)
			}
			updateClientDb(base, paths)
			for _, path := range paths {
				if !bytes.Equal(rekeyTestRead(t, static+version+"/"+path), rekeyTestRead(t, base+path)) {
					t.Fatal("missing static manifest was not restored")
				}
			}
			rekeyTestWrite(t, static+version+"/"+paths[0], []byte("damaged manifest"))
			updateClientDb(base, paths)
			if !bytes.Equal(rekeyTestRead(t, static+version+"/"+paths[0]), rekeyTestRead(t, base+paths[0])) {
				t.Fatal("damaged static manifest was not repaired")
			}
		})
	}
}

func TestRekeyRejectsTrailingCiphertext(t *testing.T) {
	base, static, version, _, expected, ref := rekeyTestFixture(t)
	output := static + version + "/masterdata.db"
	rekeyTestWrite(t, output, append(append([]byte(nil), expected...), 0x23, 0x87))
	if reuseRekeyed(base+"masterdata.db", output, &ref, keySpec) {
		t.Fatal("accepted trailing bytes after the complete compressed stream")
	}
	rekey(base+"masterdata.db", output, &ref, keySpec)
	if !bytes.Equal(rekeyTestRead(t, output), expected) {
		t.Fatal("trailing ciphertext was not repaired")
	}
}

func TestRekeyRejectsInflatedOutputLargerThanSource(t *testing.T) {
	base, static, version, plain, expected, ref := rekeyTestFixture(t)
	var zipped bytes.Buffer
	writer := zlib.NewWriter(&zipped)
	if _, err := writer.Write(append(append([]byte(nil), plain...), bytes.Repeat([]byte("x"), 1024*1024)...)); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	bad := append([]byte(nil), zipped.Bytes()[2:zipped.Len()-4]...)
	key := ref.getKey(keySpec)
	hwdecrypt.DecryptBuffer(&key, bad)
	output := static + version + "/masterdata.db"
	rekeyTestWrite(t, output, bad)
	if reuseRekeyed(base+"masterdata.db", output, &ref, keySpec) {
		t.Fatal("accepted an inflated payload larger than the authoritative source")
	}
	rekey(base+"masterdata.db", output, &ref, keySpec)
	if !bytes.Equal(rekeyTestRead(t, output), expected) {
		t.Fatal("oversized payload was not repaired")
	}
	decrypted := append([]byte(nil), expected...)
	key = ref.getKey(keySpec)
	hwdecrypt.DecryptBuffer(&key, decrypted)
	reader := flate.NewReader(bytes.NewReader(decrypted))
	defer reader.Close()
	decoded, err := io.ReadAll(reader)
	if err != nil || !bytes.Equal(decoded, plain) {
		t.Fatal("repaired output does not decode to the source")
	}
}

func TestWriteRekeyedRenameFailureLeavesDestinationAndNoTemp(t *testing.T) {
	root := t.TempDir()
	output := filepath.Join(root, "destination-directory")
	rekeyTestWrite(t, filepath.Join(output, "keep"), []byte("original"))
	func() {
		defer func() {
			if recover() == nil {
				t.Fatal("expected rename to a nonempty directory to fail")
			}
		}()
		writeRekeyed(output, []byte("replacement"))
	}()
	if string(rekeyTestRead(t, filepath.Join(output, "keep"))) != "original" {
		t.Fatal("failed replacement damaged the destination")
	}
	temporaries, err := filepath.Glob(filepath.Join(root, ".rekey-*"))
	if err != nil || len(temporaries) != 0 {
		t.Fatal("failed replacement left a temporary file")
	}
}
