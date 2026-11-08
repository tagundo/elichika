package clientdb

import (
	"bufio"
	"bytes"
	"compress/flate"
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"

	"elichika/utils"
	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

const clientDBBufferSize = 64 * 1024
const sqliteSignature = "SQLite format 3\x00"

func fileExist(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// Hash the entire authoritative input without a database-sized allocation.
// Missing, short, replaced or growing inputs never become empty-file hashes.
func hashSQLiteFile(name string) (string, int64, error) {
	file, err := os.Open(name)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil {
		return "", 0, err
	}
	if !before.Mode().IsRegular() || before.Size() < int64(len(sqliteSignature)) {
		return "", 0, fmt.Errorf("invalid SQLite input: %s", name)
	}
	header := make([]byte, len(sqliteSignature))
	if _, err = io.ReadFull(file, header); err != nil || string(header) != sqliteSignature {
		return "", 0, fmt.Errorf("missing SQLite file signature: %s", name)
	}
	digest := sha1.New()
	digest.Write(header)
	n, err := io.CopyBuffer(digest, io.LimitReader(file, before.Size()-int64(len(header))+1), make([]byte, clientDBBufferSize))
	if err != nil {
		return "", 0, err
	}
	if n+int64(len(header)) != before.Size() {
		return "", 0, fmt.Errorf("SQLite input size changed while hashing: %s", name)
	}
	after, err := file.Stat()
	if err != nil {
		return "", 0, err
	}
	current, err := os.Stat(name)
	if err != nil || !os.SameFile(before, current) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) || after.Size() != current.Size() || !after.ModTime().Equal(current.ModTime()) {
		return "", 0, fmt.Errorf("SQLite input changed while hashing: %s", name)
	}
	return hex.EncodeToString(digest.Sum(nil)), before.Size(), nil
}

// HWD updates its keyset after each chunk. Do not mutate a compressor's input
// buffer: the io.Writer contract reserves that buffer for its caller.
type rekeyCipherWriter struct {
	output io.Writer
	key    hwdecrypt.HwdKeyset
	buffer [clientDBBufferSize]byte
	count  int64
}

func (writer *rekeyCipherWriter) Write(input []byte) (int, error) {
	written := 0
	for len(input) > 0 {
		length := len(input)
		if length > len(writer.buffer) {
			length = len(writer.buffer)
		}
		buffer := writer.buffer[:length]
		copy(buffer, input[:length])
		hwdecrypt.DecryptBuffer(&writer.key, buffer)
		n, err := writer.output.Write(buffer)
		writer.count += int64(n)
		written += n
		if err != nil {
			return written, err
		}
		if n != length {
			return written, io.ErrShortWrite
		}
		input = input[length:]
	}
	return written, nil
}

type rekeyCipherReader struct {
	input  io.Reader
	key    hwdecrypt.HwdKeyset
	digest hash.Hash
	count  int64
}

func (reader *rekeyCipherReader) Read(output []byte) (int, error) {
	n, err := reader.input.Read(output)
	if n > 0 {
		reader.digest.Write(output[:n])
		reader.count += int64(n)
		hwdecrypt.DecryptBuffer(&reader.key, output[:n])
	}
	return n, err
}

// Always decode the full cached output against the authoritative clear hash.
// ByteReader preserves the exact DEFLATE boundary, including trailing bytes.
func reuseRekeyed(inPath, outPath string, fromFile *FileReference, keySpec hwdecrypt.HwdKeyset) bool {
	source, err := os.Stat(inPath)
	if err != nil || !source.Mode().IsRegular() || source.Size() < int64(len(sqliteSignature)) {
		return false
	}
	input, err := os.Open(outPath)
	if err != nil {
		return false
	}
	defer input.Close()
	info, err := input.Stat()
	limit := source.Size() + source.Size()/8 + 65536
	if err != nil || !info.Mode().IsRegular() || info.Size() > limit || info.Size() < 1 {
		return false
	}
	cipher := &rekeyCipherReader{input: io.LimitReader(input, limit+1), key: fromFile.getKey(keySpec), digest: sha1.New()}
	compressed := bufio.NewReaderSize(cipher, clientDBBufferSize)
	reader := flate.NewReader(compressed)
	defer reader.Close()
	header := make([]byte, len(sqliteSignature))
	if _, err = io.ReadFull(reader, header); err != nil || string(header) != sqliteSignature {
		return false
	}
	digest := sha1.New()
	digest.Write(header)
	n, err := io.CopyBuffer(digest, io.LimitReader(reader, source.Size()-int64(len(header))+1), make([]byte, clientDBBufferSize))
	if err != nil || n+int64(len(header)) != source.Size() || hex.EncodeToString(digest.Sum(nil)) != fromFile.SHA {
		return false
	}
	if _, err = compressed.ReadByte(); err != io.EOF {
		return false
	}
	after, err := input.Stat()
	if err != nil || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) || cipher.count != info.Size() {
		return false
	}
	current, err := os.Stat(outPath)
	if err != nil || !os.SameFile(info, current) || current.Size() != after.Size() || !current.ModTime().Equal(after.ModTime()) {
		return false
	}
	fromFile.EncryptedSHA = hex.EncodeToString(cipher.digest.Sum(nil))
	fromFile.Size = int(cipher.count)
	return true
}

func writeRekeyed(outPath string, output []byte) {
	file, err := os.CreateTemp(filepath.Dir(outPath), ".rekey-*")
	utils.CheckErr(err)
	defer os.Remove(file.Name())
	defer file.Close()
	_, err = io.CopyBuffer(file, bytes.NewReader(output), make([]byte, clientDBBufferSize))
	utils.CheckErr(err)
	utils.CheckErr(file.Sync())
	utils.CheckErr(file.Close())
	utils.CheckErr(os.Rename(file.Name(), outPath))
}

// Stream a new raw-DEFLATE/HWD output to a private file, fully decode and verify
// it, then atomically rename. Both clear and cipher memory stay bounded.
func rekeyFile(inPath, outPath string, fromFile *FileReference, keySpec hwdecrypt.HwdKeyset) error {
	if !manifestHash.MatchString(fromFile.SHA) {
		return fmt.Errorf("invalid SQLite source hash: %s", inPath)
	}
	verified := *fromFile
	if reuseRekeyed(inPath, outPath, &verified, keySpec) {
		current, _, err := hashSQLiteFile(inPath)
		if err != nil {
			return err
		}
		if current != fromFile.SHA {
			return fmt.Errorf("clear database changed while verifying cached client data: %s", inPath)
		}
		*fromFile = verified
		return nil
	}
	source, err := os.Open(inPath)
	if err != nil {
		return err
	}
	defer source.Close()
	info, err := source.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() < int64(len(sqliteSignature)) {
		return fmt.Errorf("invalid SQLite input: %s", inPath)
	}
	header := make([]byte, len(sqliteSignature))
	if _, err = io.ReadFull(source, header); err != nil || string(header) != sqliteSignature {
		return fmt.Errorf("missing SQLite file signature: %s", inPath)
	}
	output, err := os.CreateTemp(filepath.Dir(outPath), ".rekey-*")
	if err != nil {
		return err
	}
	defer os.Remove(output.Name())
	defer output.Close()
	cipherHash, clearHash := sha1.New(), sha1.New()
	cipher := &rekeyCipherWriter{output: io.MultiWriter(output, cipherHash), key: fromFile.getKey(keySpec)}
	compressor, err := flate.NewWriter(cipher, flate.DefaultCompression)
	if err != nil {
		return err
	}
	count, copyErr := io.CopyBuffer(io.MultiWriter(compressor, clearHash),
		io.LimitReader(io.MultiReader(bytes.NewReader(header), source), info.Size()+1), make([]byte, clientDBBufferSize))
	closeErr := compressor.Close()
	if copyErr != nil {
		return copyErr
	}
	if closeErr != nil {
		return closeErr
	}
	if count != info.Size() || hex.EncodeToString(clearHash.Sum(nil)) != fromFile.SHA {
		return fmt.Errorf("clear database changed while generating client data: %s", inPath)
	}
	if err = output.Sync(); err != nil {
		return err
	}
	if err = output.Close(); err != nil {
		return err
	}
	if !reuseRekeyed(inPath, output.Name(), &verified, keySpec) || verified.Size != int(cipher.count) || verified.EncryptedSHA != hex.EncodeToString(cipherHash.Sum(nil)) {
		return fmt.Errorf("generated client data failed full verification: %s", inPath)
	}
	if err = os.Rename(output.Name(), outPath); err != nil {
		return err
	}
	*fromFile = verified
	return nil
}

func rekey(inPath, outPath string, fromFile *FileReference, keySpec hwdecrypt.HwdKeyset) {
	utils.CheckErr(rekeyFile(inPath, outPath, fromFile, keySpec))
}
