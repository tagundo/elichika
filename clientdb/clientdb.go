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

func fileSha1(fileName string) []byte {
	file, err := os.ReadFile(fileName)
	if err != nil {
		file = []byte{}
	}
	sha1 := sha1.Sum(file)
	return sha1[:]
}

func fileSha1AndSize(fileName string) ([]byte, int) {
	file, err := os.ReadFile(fileName)
	if err != nil {
		file = []byte{}
	}
	sha1 := sha1.Sum(file)
	return sha1[:], len(file)
}

func updateClientDb(baseDir string, masterdataRefs []string) {
	versionBytes := []byte{}
	oldVersion := ""
	actualFileVersions := map[string]string{}
	mMap := map[string]*manifest{}
	for _, refPath := range masterdataRefs {
		log.Println(baseDir + refPath)
		f, err := os.Open(baseDir + refPath)
		utils.CheckErr(err)
		defer f.Close()
		mMap[refPath] = newManifest(f)
		if oldVersion == "" {
			oldVersion = mMap[refPath].Version
		} else if oldVersion != mMap[refPath].Version {
			log.Panic("manifest files must come from the same version")
		}
		for _, file := range mMap[refPath].Files {
			actualFileVersion, checked := actualFileVersions[file.Name]
			if !checked {
				actualFileVersion = hex.EncodeToString(fileSha1(baseDir + file.Name))
				actualFileVersions[file.Name] = actualFileVersion
			}
			versionBytes = append(versionBytes, []byte(actualFileVersion)...)
		}
	}
	version := md5.Sum(versionBytes) // use md5 because it generate a 16 bytes string, which we can fold into 16 hex char
	newVersion := versionString(hex.EncodeToString(version[:]))
	os.MkdirAll(config.StaticDataPath+newVersion+"/", 0755)
	// A shared DB can appear in several locale/platform manifests. Reuse only
	// outputs already verified/generated in this call, with this source SHA and
	// fixed keySpec; a pre-existing disk path is never sufficient evidence.
	verified := map[string]FileReference{}
	prepare := func(inputFile, outputFile string, file *FileReference) {
		file.SHA = actualFileVersions[file.Name]
		if previous, ok := verified[outputFile]; ok && previous.SHA == file.SHA {
			file.EncryptedSHA, file.Size = previous.EncryptedSHA, previous.Size
			return
		}
		rekey(inputFile, outputFile, file, keySpec)
		verified[outputFile] = *file
	}
	if newVersion == oldVersion {
		// check for integrity  of the data
		log.Println("Performing integrity check for version: ", oldVersion)
		updated := false
		for _, m := range mMap {
			for i := range m.Files {
				inputFile := baseDir + m.Files[i].Name
				existingFile := config.StaticDataPath + oldVersion + "/" + m.Files[i].Name
				before := m.Files[i]
				prepare(inputFile, existingFile, &m.Files[i])
				if m.Files[i] != before {
					updated = true
				}
			}
		}
		// A restored output may have the same metadata as before, while the
		// corresponding static manifest is missing or damaged.
		for refPath, m := range mMap {
			existing, err := os.ReadFile(config.StaticDataPath + oldVersion + "/" + refPath)
			if err != nil || !bytes.Equal(existing, m.serialize()) {
				updated = true
			}
		}
		if updated { // update all the manifest
			for refPath, m := range mMap {
				serialized := m.serialize()
				err := os.WriteFile(config.StaticDataPath+oldVersion+"/"+refPath, serialized, 0777)
				utils.CheckErr(err)
				err = os.WriteFile(baseDir+refPath, serialized, 0777)
				utils.CheckErr(err)
			}
		}
	} else {
		log.Println("Difference detected, new version: ", newVersion)
		for refPath, m := range mMap {
			m.Version = newVersion
			for i := range m.Files {
				inputFile := baseDir + m.Files[i].Name
				outputFile := config.StaticDataPath + newVersion + "/" + m.Files[i].Name
				prepare(inputFile, outputFile, &m.Files[i])
			}
			serialized := m.serialize()
			err := os.WriteFile(config.StaticDataPath+newVersion+"/"+refPath, serialized, 0777)
			utils.CheckErr(err)
			err = os.WriteFile(baseDir+refPath, serialized, 0777)
			utils.CheckErr(err)
		}
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
	buff := make([]byte, 1024)
	count, err := file.Read(buff)
	utils.CheckErr(err)
	if count < 21 {
		log.Panic("file too short")
	}
	length := int(buff[20])
	version := string(buff[21 : 21+length])
	return version
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
