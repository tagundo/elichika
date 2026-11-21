package clientdb

import (
	"elichika/assetdata"
	"elichika/clientdb/upgrades"
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
	updateClientDbWithCatalogs(baseDir, masterdataRefs, workerLimit, nil)
}

type prepareClientCatalog func(sourcePath, destinationPath string) (int64, error)

func updateClientDbWithCatalogs(baseDir string, masterdataRefs []string, workerLimit int, loadPolicy func() (prepareClientCatalog, error)) {
	if workerLimit != 0 && workerLimit != 1 && workerLimit != 2 && workerLimit != 4 && workerLimit != 8 {
		log.Panic("client database workers must be automatic, 1, 2, 4 or 8")
	}
	type databaseFile struct {
		name       string
		sourcePath string
		path       string
		sha        string
		size       int64
		sourceSHA  string
		sourceSize int64
		reference  FileReference
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
		file := &files[index]
		file.sourcePath = filepath.Join(baseDir, file.name)
		sha, size, err := hashSQLiteFile(file.sourcePath)
		if err != nil {
			return err
		}
		file.sourceSHA, file.sourceSize = sha, size
		file.path, file.sha, file.size = file.sourcePath, sha, size
		return nil
	}))
	// The policy reads the Global master database. Building it after the first
	// source hash brings that read under the same barrier as its derived catalogs.
	var prepare prepareClientCatalog
	if _, hasMaster := indices["masterdata.db"]; loadPolicy != nil && hasMaster {
		var err error
		prepare, err = loadPolicy()
		utils.CheckErr(err)
	}
	if prepare != nil {
		staticParent := filepath.Dir(filepath.Clean(config.StaticDataPath))
		utils.CheckErr(os.MkdirAll(staticParent, 0755))
		preparedDir, err := os.MkdirTemp(staticParent, ".client-catalogs-")
		utils.CheckErr(err)
		defer os.RemoveAll(preparedDir)
		utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
			file := &files[index]
			if !isGlobalAssetCatalog(file.name) || clientDBHasPendingChanges(file.path) {
				return nil
			}
			derivedPath := filepath.Join(preparedDir, file.name)
			removed, err := prepare(file.path, derivedPath)
			if err != nil {
				return fmt.Errorf("prepare Global download catalog %s: %w", file.name, err)
			}
			if removed == 0 {
				return nil
			}
			sha, size, err := hashSQLiteFile(derivedPath)
			if err != nil {
				return err
			}
			file.path, file.sha, file.size = derivedPath, sha, size
			log.Printf("Omitted %d alternate pack mappings from the served %s\n", removed, file.name)
			return nil
		}))
	}
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
	usingDerivedCatalogs := false
	for index := range files {
		file := &files[index]
		file.reference.Version, file.reference.SHA = newVersion, file.sha
		usingDerivedCatalogs = usingDerivedCatalogs || file.path != file.sourcePath
	}
	utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
		file := &files[index]
		return rekeyFile(file.path, filepath.Join(outputDir, file.name), &file.reference, keySpec)
	}))
	// Keep both catalog reads within the final source verification barrier.
	if scopedDownloadCommand(os.Args) {
		for _, file := range files {
			if file.path == file.sourcePath {
				continue
			}
			utils.CheckErr(registerPreparedDownloadProfile(file.name, file.sourcePath, file.path))
		}
	}
	// A source changed while a different worker was preparing its file must not
	// be advertised under the earlier version. This is deliberately a content
	// hash, not a timestamp-only shortcut.
	utils.CheckErr(runClientDBJobs(len(files), workers, func(index int) error {
		file := &files[index]
		sha, size, err := hashSQLiteFile(file.sourcePath)
		if err != nil {
			return err
		}
		if sha != file.sourceSHA || size != file.sourceSize {
			return fmt.Errorf("clear database changed before client manifest publication: %s", file.name)
		}
		usesDerivedCatalog := file.path != file.sourcePath
		needsQuietSource := usesDerivedCatalog || (usingDerivedCatalogs && file.name == "masterdata.db")
		if needsQuietSource && clientDBHasPendingChanges(file.sourcePath) {
			return fmt.Errorf("clear database acquired pending changes before client manifest publication: %s", file.name)
		}
		if usesDerivedCatalog {
			sha, size, err = hashSQLiteFile(file.path)
			if err != nil {
				return err
			}
			if sha != file.sha || size != file.size {
				return fmt.Errorf("prepared catalog changed before client manifest publication: %s", file.name)
			}
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

func scopedDownloadCommand(args []string) bool {
	if len(args) < 3 {
		return false
	}
	if args[1] == "archive_required" || (args[1] == "download_archive" && args[len(args)-1] == "--missing") {
		return true
	}
	return args[1] == "download_packs" && (len(args) > 3 || strings.HasPrefix(args[2], "--"))
}

func registerPreparedDownloadProfile(name, sourcePath, servedPath string) error {
	// Preparation only supplies derived paths for the six recognized GL catalogs.
	platform := assetdata.PlatformAndroid
	if strings.HasPrefix(name, "asset_i_") {
		platform = assetdata.PlatformIOS
	}
	profile := assetdata.AssetProfile{
		Region: assetdata.RegionGL, Platform: platform,
		Language: assetdata.Language(strings.TrimSuffix(name[len("asset_a_"):], ".db")),
	}
	names, err := upgrades.PreparedGlobalDownloadFiles(sourcePath, servedPath)
	if err != nil {
		return fmt.Errorf("read served download profile %s: %w", profile, err)
	}
	return assetdata.RegisterServedDownloadProfile(profile, names)
}

func isGlobalAssetCatalog(name string) bool {
	switch name {
	case "asset_a_en.db", "asset_a_ko.db", "asset_a_zh.db", "asset_i_en.db", "asset_i_ko.db", "asset_i_zh.db":
		return true
	}
	return false
}

func clientDBHasPendingChanges(path string) bool {
	for _, suffix := range []string{"-wal", "-journal"} {
		info, err := os.Lstat(path + suffix)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil || !info.Mode().IsRegular() || info.Size() != 0 {
			return true
		}
	}
	return false
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
	updateClientDbWithCatalogs(config.GlMasterdataPath, masterdataRefGls, 0, func() (prepareClientCatalog, error) {
		policy, err := upgrades.GlobalDownloadCatalogs(config.AssetPath, config.CdnPackDirectory(), config.StaticDataPath)
		if err != nil || policy == nil {
			return nil, err
		}
		return policy.Prepare, nil
	})
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
