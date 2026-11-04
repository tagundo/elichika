package clientdb

import (
	"elichika/log"
	"elichika/utils"

	"bytes"
	"compress/flate"
	"compress/zlib"
	"crypto/sha1"
	"encoding/hex"
	"io"

	"os"
	"path/filepath"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

func fileExist(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// reuseRekeyed verifies the contents against the authoritative clear DB, rather
// than trusting a hash previously adopted into a manifest. Bound both compressed
// input and inflated output so a damaged file cannot grow without limit.
func reuseRekeyed(inPath, outPath string, fromFile *FileReference, keySpec hwdecrypt.HwdKeyset) bool {
	source, err := os.Stat(inPath)
	if err != nil || source.Size() < 16 {
		return false
	}
	input, err := os.Open(outPath)
	if err != nil {
		return false
	}
	defer input.Close()
	limit := source.Size() + source.Size()/8 + 65536
	encoded, err := io.ReadAll(io.LimitReader(input, limit+1))
	if err != nil || int64(len(encoded)) > limit {
		return false
	}
	cipherHash := sha1.Sum(encoded)
	keyset := fromFile.getKey(keySpec)
	hwdecrypt.DecryptBuffer(&keyset, encoded)
	compressed := bytes.NewReader(encoded)
	reader := flate.NewReader(compressed)
	defer reader.Close()
	header := make([]byte, 16)
	if _, err = io.ReadFull(reader, header); err != nil || string(header) != "SQLite format 3\x00" {
		return false
	}
	hash := sha1.New()
	hash.Write(header)
	count, err := io.Copy(hash, io.LimitReader(reader, source.Size()-16+1))
	if err != nil || count+16 != source.Size() || compressed.Len() != 0 || hex.EncodeToString(hash.Sum(nil)) != fromFile.SHA {
		return false
	}
	fromFile.EncryptedSHA = hex.EncodeToString(cipherHash[:])
	fromFile.Size = len(encoded)
	return true
}

func writeRekeyed(outPath string, output []byte) {
	file, err := os.CreateTemp(filepath.Dir(outPath), ".rekey-*")
	utils.CheckErr(err)
	defer os.Remove(file.Name())
	defer file.Close()
	_, err = file.Write(output)
	utils.CheckErr(err)
	utils.CheckErr(file.Sync())
	utils.CheckErr(file.Close())
	utils.CheckErr(os.Rename(file.Name(), outPath))
}

// rekey updates the reference only after proving that the output decodes to the
// current clear DB. This also repairs old manifests that adopted a damaged file.
func rekey(inPath, outPath string, fromFile *FileReference, keySpec hwdecrypt.HwdKeyset) {
	if reuseRekeyed(inPath, outPath, fromFile, keySpec) {
		return
	}
	clear_buf, err := os.ReadFile(inPath)
	utils.CheckErr(err)
	if len(clear_buf) < 16 || string(clear_buf[:16]) != "SQLite format 3\x00" {
		log.Panic("Missing SQLite file signature. Is it already encrypted?")
	}
	clearHash := sha1.Sum(clear_buf)
	if hex.EncodeToString(clearHash[:]) != fromFile.SHA {
		log.Panic("Clear database changed while generating client data")
	}
	var crypt_buf bytes.Buffer
	zlibWriter := zlib.NewWriter(&crypt_buf)
	zlibWriter.Write(clear_buf)
	zlibWriter.Close()
	keyset := fromFile.getKey(keySpec)
	outputBytes := crypt_buf.Bytes()
	// skip the header and checksum.
	// TODO(extra): maybe write our own zlib manually using flate to have the same wbits things as python
	outputBytes = outputBytes[2 : len(outputBytes)-4]
	hwdecrypt.DecryptBuffer(&keyset, outputBytes)
	writeRekeyed(outPath, outputBytes)
	fromFile.Size = len(outputBytes)
	sha1 := sha1.Sum(outputBytes)
	fromFile.EncryptedSHA = hex.EncodeToString(sha1[:])
}
