package clientdb

import (
	"bytes"
	"elichika/log"
	"elichika/utils"
	"io"
	"regexp"

	"crypto/sha1"
	"encoding/hex"
	"os"
)

type manifest struct {
	Version string
	Lang    string
	Files   []FileReference
}

func serializeUbyte(b byte) []byte {
	bytes := make([]byte, 1)
	bytes[0] = b
	return bytes
}

func serializeUint(i int) []byte {
	b := make([]byte, 4)
	b[0] = byte(i & 0xff)
	b[0] |= 0x80
	i -= int(b[0])
	b[1] = byte((i >> 7) & 0xff)
	i = (i >> 7) - int(b[1])
	b[2] = byte((i >> 8) & 0xff)
	b[3] = byte((i >> 16) & 0xff)
	return b
}

func serializePrefixString(s string) []byte {
	b := []byte{}
	b = append(b, byte(len(s)))
	b = append(b, []byte(s)...)
	return b
}

func (m *manifest) serialize() []byte {
	buf := []byte{}

	buf = append(buf, serializePrefixString(m.Version)...)
	buf = append(buf, serializePrefixString(m.Lang)...)
	buf = append(buf, serializeUbyte(byte(len(m.Files)))...)

	for _, f := range m.Files {
		buf = append(buf, serializePrefixString(f.Name)...)
		buf = append(buf, serializePrefixString(f.SHA)...)
	}
	for _, f := range m.Files {
		bytes, err := hex.DecodeString(f.EncryptedSHA)
		utils.CheckErr(err)
		buf = append(buf, bytes...)
		buf = append(buf, serializeUint(f.Size)...)
	}
	sha1 := sha1.Sum(buf)
	buf = append(sha1[:], buf...)
	return buf
}

var (
	manifestVersion = regexp.MustCompile(`^[0-9a-f]{16}$`)
	manifestLocale  = regexp.MustCompile(`^[a-z]{2}$`)
	manifestDBName  = regexp.MustCompile(`^[A-Za-z0-9_.-]+\.db$`)
	manifestHash    = regexp.MustCompile(`^[0-9a-f]{40}$`)
)

func newManifest(file *os.File) *manifest {
	// Refuse corrupt/truncated manifests instead of treating a partial read as
	// usable metadata during recovery. No installed DB is replaced by this path.
	data, err := io.ReadAll(io.LimitReader(file, 256*1024+1))
	utils.CheckErr(err)
	if len(data) < 23 || len(data) > 256*1024 {
		log.Panic("invalid client manifest length: " + file.Name())
	}
	hash := sha1.Sum(data[20:])
	if !bytes.Equal(hash[:], data[:20]) {
		log.Panic("invalid client manifest checksum: " + file.Name())
	}
	body := bytes.NewReader(data[20:])
	read := func(size int) []byte {
		value := make([]byte, size)
		_, err := io.ReadFull(body, value)
		utils.CheckErr(err)
		return value
	}
	prefix := func() string { return string(read(int(read(1)[0]))) }
	m := &manifest{Version: prefix(), Lang: prefix()}
	if !manifestVersion.MatchString(m.Version) || !manifestLocale.MatchString(m.Lang) {
		log.Panic("invalid client manifest version or locale: " + file.Name())
	}
	count := int(read(1)[0])
	seen := map[string]bool{}
	for i := 0; i < count; i++ {
		name, sha := prefix(), prefix()
		if !manifestDBName.MatchString(name) || name == ".db" || seen[name] || !manifestHash.MatchString(sha) {
			log.Panic("invalid client manifest database reference: " + file.Name())
		}
		seen[name] = true
		m.Files = append(m.Files, makeFileReference(m.Version, name, sha))
	}
	if count == 0 || body.Len() != count*24 {
		log.Panic("invalid client manifest file metadata: " + file.Name())
	}
	for i := range m.Files {
		m.Files[i].EncryptedSHA = hex.EncodeToString(read(20))
		b := read(4)
		size := (int(b[3]) << 8) + int(b[2])
		size = (size << 8) + int(b[1])
		m.Files[i].Size = (size << 7) + int(b[0])
	}
	return m
}
