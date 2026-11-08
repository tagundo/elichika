package clientdb

import (
	"elichika/config"
	"elichika/log"
	"elichika/utils"

	"bytes"
	"crypto/md5"
	"encoding/hex"
	"fmt"

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

// updateClientDb treats installed clear databases as authoritative. Preparation
// jobs own independent references; no manifest is published until every worker
// has joined and all authoritative inputs have passed the final hash barrier.
func updateClientDb(baseDir string, masterdataRefs []string) {
	updateClientDbWithWorkers(baseDir, masterdataRefs, 0)
}

// A private component-test/benchmark limit. Normal startup always uses the
// resource-aware automatic policy; there is no new user configuration setting.
func updateClientDbWithWorkers(baseDir string, masterdataRefs []string, workerLimit int) {
	if workerLimit != 0 && workerLimit != 1 && workerLimit != 2 && workerLimit != 4 && workerLimit != 8 {
		log.Panic("client database workers must be automatic, 1, 2, 4 or 8")
	}
	type databaseFile struct {
		name      string
		sha       string
		size      int64
		reference FileReference
	}
	files := []databaseFile{}
	indices := map[string]int{}
	manifests := make([]*manifest, 0, len(masterdataRefs))
	oldVersion, mixedVersions := "", false
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
			if _, found := indices[file.Name]; !found {
				indices[file.Name] = len(files)
				files = append(files, databaseFile{name: file.Name, reference: file})
			}
		}
	}
	workers := clientDBWorkerCount(len(files))
	if workerLimit > 0 {
		workers = workerLimit
	}
	utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
		sha, size, err := hashSQLiteFile(baseDir + files[index].name)
		if err != nil {
			return err
		}
		files[index].sha, files[index].size = sha, size
		return nil
	}))
	// Concatenation order remains manifest/file order, including duplicate
	// references. Worker completion order must never change the regional version.
	versionBytes := []byte{}
	for _, m := range manifests {
		for _, file := range m.Files {
			versionBytes = append(versionBytes, []byte(files[indices[file.Name]].sha)...)
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
	log.Printf("Preparing %d client database files with %d worker(s)\n", len(files), workers)
	for index := range files {
		file := &files[index]
		file.reference.Version, file.reference.SHA = newVersion, file.sha
	}
	utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
		file := &files[index]
		return rekeyFile(baseDir+file.name, filepath.Join(outputDir, file.name), &file.reference, keySpec)
	}))
	// A source changed while a different worker was preparing its file must not
	// be advertised under the earlier version. This is deliberately a content
	// hash, not a timestamp-only shortcut.
	utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
		file := &files[index]
		sha, size, err := hashSQLiteFile(baseDir + file.name)
		if err != nil {
			return err
		}
		if sha != file.sha || size != file.size {
			return fmt.Errorf("clear database changed before client manifest publication: %s", file.name)
		}
		return nil
	}))
	for _, m := range manifests {
		m.Version = newVersion
		for index := range m.Files {
			file := &m.Files[index]
			prepared := files[indices[file.Name]].reference
			file.Version, file.SHA = newVersion, prepared.SHA
			file.EncryptedSHA, file.Size = prepared.EncryptedSHA, prepared.Size
		}
	}
	// CDN copies first, then installed headers. All file verification has ended
	// before even staging these manifest bytes; interrupted renames still recover.
	writes := make([]manifestWrite, 0, 2*len(manifests))
	for index, m := range manifests {
		writes = append(writes, manifestWrite{filepath.Join(outputDir, masterdataRefs[index]), m.serialize()})
	}
	for index, m := range manifests {
		writes = append(writes, manifestWrite{baseDir + masterdataRefs[index], m.serialize()})
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
