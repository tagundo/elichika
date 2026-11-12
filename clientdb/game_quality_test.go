package clientdb

import (
	"bytes"
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	"elichika/config"
	_ "modernc.org/sqlite"
)

// The admin editor changes the clear table. Normal server startup must publish
// a new client master version/ciphertext, then keep it stable on later starts.
func TestGameQualityEditsPublishNewClientMasterVersionAndPersist(t *testing.T) {
	directory := t.TempDir()
	base := filepath.Join(directory, "db") + "/"
	if err := os.MkdirAll(base, 0700); err != nil {
		t.Fatal(err)
	}
	path := base + "masterdata.db"
	write := func(statement string) {
		t.Helper()
		db, err := sql.Open("sqlite", path)
		if err != nil {
			t.Fatal(err)
		}
		defer db.Close()
		if _, err = db.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	write(`CREATE TABLE m_live_quality_setting(set_id INTEGER, quality_mode INTEGER,
		rendering_resolution INTEGER, member_swing_bone_mv INTEGER,
		PRIMARY KEY(set_id,quality_mode));
		INSERT INTO m_live_quality_setting VALUES(3,10,1080,0);
		CREATE TABLE unrelated(value TEXT); INSERT INTO unrelated VALUES('keep');`)
	before := rekeyTestRead(t, path)
	ref := makeFileReference("0000000000000000", "masterdata.db", rekeyTestSHA(before))
	ref.EncryptedSHA, ref.Size = rekeyTestSHA(nil), 1
	manifestPath := "masterdata_a_en"
	rekeyTestWrite(t, base+manifestPath, (&manifest{Version: ref.Version, Lang: "en", Files: []FileReference{ref}}).serialize())
	previousStatic := config.StaticDataPath
	config.StaticDataPath = filepath.Join(directory, "static") + "/"
	t.Cleanup(func() { config.StaticDataPath = previousStatic })
	updateClientDbWithWorkers(base, []string{manifestPath}, 1)
	first := rekeyTestManifest(t, base+manifestPath)
	firstCipher := rekeyTestRead(t, config.StaticDataPath+first.Version+"/masterdata.db")
	write("UPDATE m_live_quality_setting SET rendering_resolution=1440,member_swing_bone_mv=1 WHERE set_id=3 AND quality_mode=10")
	edited := rekeyTestRead(t, path)
	updateClientDbWithWorkers(base, []string{manifestPath}, 1)
	second := rekeyTestManifest(t, base+manifestPath)
	if second.Version == first.Version || second.Files[0].SHA == first.Files[0].SHA {
		t.Fatal("edited graphics settings must invalidate the client's masterdata cache version")
	}
	if second.Files[0].SHA != rekeyTestSHA(edited) {
		t.Fatal("published masterdata must describe the actual edited clear SQLite database")
	}
	secondCipher := rekeyTestRead(t, config.StaticDataPath+second.Version+"/masterdata.db")
	if bytes.Equal(firstCipher, secondCipher) || !bytes.Equal(secondCipher, originalRekeyOracle(t, edited, second.Files[0])) {
		t.Fatal("the client must receive new, correctly encrypted graphics settings")
	}
	updateClientDbWithWorkers(base, []string{manifestPath}, 1)
	third := rekeyTestManifest(t, base+manifestPath)
	if third.Version != second.Version || !bytes.Equal(edited, rekeyTestRead(t, path)) {
		t.Fatal("another startup must preserve the edited quality database and its version")
	}
}
