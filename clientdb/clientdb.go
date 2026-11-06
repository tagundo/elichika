package clientdb

import (
	"elichika/config"
	"elichika/log"
	"elichika/utils"

	"bytes"
	"crypto/md5"
	"crypto/sha1"
	"encoding/hex"

	"os"
	"path/filepath"
	"strings"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

var (
	keySpec = hwdecrypt.HwdKeyset{
		Key1: 0x49e66da3,
		Key2: 0x59e1e89a,
		Key3: 0x24ebb207,
	}
)

func versionString(shaInHex string) string {
	// take the top xor with the bottom
	bytes, _ := hex.DecodeString(shaInHex)
	length := len(bytes) / 2
	return hex.EncodeToString(utils.Xor(bytes[:length], bytes[length:]))
}

func fileSha1AndSize(fileName string) ([]byte, int) {
	file, err := os.ReadFile(fileName)
	if err != nil {
		file = []byte{}
	}
	sha1 := sha1.Sum(file)
	return sha1[:], len(file)
}

// updateClientDb treats the installed clear databases as authoritative. Header
// versions can legitimately differ after a previous process stopped between
// manifest renames; each valid manifest still supplies its own locale/file list.
func updateClientDb(baseDir string, masterdataRefs []string) {
	versionBytes := []byte{}
	oldVersion := ""
	mixedVersions := false
	actualFileVersions := map[string]string{}
	manifests := make([]*manifest, 0, len(masterdataRefs))
	for _, refPath := range masterdataRefs {
		log.Println(baseDir + refPath)
		f, err := os.Open(baseDir + refPath)
		utils.CheckErr(err)
		m := newManifest(f)
		utils.CheckErr(f.Close())
		if !strings.HasSuffix(refPath, "_"+m.Lang) {
			log.Panic("manifest locale does not match its filename: " + refPath)
		}
		manifests = append(manifests, m)
		if oldVersion == "" {
			oldVersion = m.Version
		} else if oldVersion != m.Version {
			mixedVersions = true
		}
		for _, file := range m.Files {
			actualFileVersion, checked := actualFileVersions[file.Name]
			if !checked {
				// Do not turn a missing/unreadable DB into an empty-file hash.
				source, err := os.ReadFile(baseDir + file.Name)
				utils.CheckErr(err)
				if len(source) < 16 || string(source[:16]) != "SQLite format 3\x00" {
					log.Panic("Missing SQLite file signature: " + file.Name)
				}
				hash := sha1.Sum(source)
				actualFileVersion = hex.EncodeToString(hash[:])
				actualFileVersions[file.Name] = actualFileVersion
			}
			versionBytes = append(versionBytes, []byte(actualFileVersion)...)
		}
	}
	version := md5.Sum(versionBytes)
	newVersion := versionString(hex.EncodeToString(version[:]))
	outputDir := filepath.Join(config.StaticDataPath, newVersion)
	utils.CheckErr(os.MkdirAll(outputDir, 0755))
	if mixedVersions {
		log.Println("Recovering interrupted client manifest update from installed databases: ", newVersion)
	} else if newVersion != oldVersion {
		log.Println("Difference detected, new version: ", newVersion)
	} else {
		log.Println("Performing integrity check for version: ", newVersion)
	}
	// Generate/verify every output before publishing any manifest. A failure in
	// a later locale must not advertise partially prepared client data.
	verified := map[string]FileReference{}
	for _, m := range manifests {
		m.Version = newVersion
		for i := range m.Files {
			file := &m.Files[i]
			file.Version = newVersion
			file.SHA = actualFileVersions[file.Name]
			outputFile := filepath.Join(outputDir, file.Name)
			if previous, ok := verified[outputFile]; ok && previous.SHA == file.SHA {
				file.EncryptedSHA, file.Size = previous.EncryptedSHA, previous.Size
				continue
			}
			rekey(baseDir+file.Name, outputFile, file, keySpec)
			verified[outputFile] = *file
		}
	}
	// Publish CDN copies first, then the installed headers used on next boot.
	// All bytes are staged before any rename; individual replacements are atomic.
	// A process kill between renames is recovered above on the next startup.
	writes := make([]manifestWrite, 0, 2*len(manifests))
	for i, m := range manifests {
		writes = append(writes, manifestWrite{filepath.Join(outputDir, masterdataRefs[i]), m.serialize()})
	}
	for i, m := range manifests {
		writes = append(writes, manifestWrite{baseDir + masterdataRefs[i], m.serialize()})
	}
	publishManifests(writes)
}

type manifestWrite struct {
	path string
	data []byte
}

func publishManifests(writes []manifestWrite) {
	type stagedManifest struct{ temporary, destination string }
	staged := make([]stagedManifest, 0, len(writes))
	defer func() {
		for _, file := range staged {
			os.Remove(file.temporary)
		}
	}()
	for _, write := range writes {
		if existing, err := os.ReadFile(write.path); err == nil && bytes.Equal(existing, write.data) {
			continue
		}
		file, err := os.CreateTemp(filepath.Dir(write.path), ".manifest-*")
		utils.CheckErr(err)
		staged = append(staged, stagedManifest{file.Name(), write.path})
		func() {
			defer file.Close()
			mode := os.FileMode(0644)
			if info, err := os.Stat(write.path); err == nil {
				mode = info.Mode().Perm()
			}
			utils.CheckErr(file.Chmod(mode))
			_, err := file.Write(write.data)
			utils.CheckErr(err)
			utils.CheckErr(file.Sync())
			utils.CheckErr(file.Close())
		}()
	}
	for _, file := range staged {
		utils.CheckErr(os.Rename(file.temporary, file.destination))
	}
}

func init() {
	databaseInit()

	// Gl
	masterdataRefGls := []string{}
	for _, p := range config.Platforms {
		for _, l := range config.GlLanguages {
			masterdataRefGls = append(masterdataRefGls, "masterdata_"+p+"_"+l)
		}
	}
	updateClientDb(config.GlMasterdataPath, masterdataRefGls)
	// Jp
	masterdataRefJps := []string{}
	for _, p := range config.Platforms {
		for _, l := range config.JpLanguages {
			masterdataRefJps = append(masterdataRefJps, "masterdata_"+p+"_"+l)
		}
	}
	updateClientDb(config.JpMasterdataPath, masterdataRefJps)

	config.MasterVersionGl = readMasterdataManinest(config.GlMasterdataPath + "masterdata_a_en")
	config.MasterVersionJp = readMasterdataManinest(config.JpMasterdataPath + "masterdata_a_ja")

	log.Println("gl master version:", config.MasterVersionGl)
	log.Println("jp master version:", config.MasterVersionJp)
}

func readMasterdataManinest(path string) string {
	file, err := os.Open(path)
	utils.CheckErr(err)
	defer file.Close()
	return newManifest(file).Version
}

func copy(in, out string) error {
	file, err := os.ReadFile(in)
	if err != nil {
		return err
	}
	err = os.WriteFile(out, file, 0777)
	utils.CheckErr(err)
	return nil
}
