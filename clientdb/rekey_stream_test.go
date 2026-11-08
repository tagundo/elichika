package clientdb

import (
	"bytes"
	"compress/zlib"
	"crypto/sha1"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"os"
	"path/filepath"
	"testing"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

// This is the pre-streaming codec, independent of all production rekey helpers.
// Retain its zlib framing and one-shot cipher as a byte-for-byte compatibility oracle.
func originalRekeyOracle(t *testing.T, clear []byte, ref FileReference) []byte {
	t.Helper()
	var buffer bytes.Buffer
	compressor := zlib.NewWriter(&buffer)
	if _, err := compressor.Write(clear); err != nil {
		t.Fatal(err)
	}
	if err := compressor.Close(); err != nil {
		t.Fatal(err)
	}
	output := append([]byte(nil), buffer.Bytes()[2:buffer.Len()-4]...)
	key := ref.getKey(keySpec)
	hwdecrypt.DecryptBuffer(&key, output)
	return output
}

func TestStreamedRekeyMatchesOriginalCodecAtBufferBoundaries(t *testing.T) {
	for _, size := range []int{0, 1, clientDBBufferSize - 17, clientDBBufferSize - 16, clientDBBufferSize - 15, 2*clientDBBufferSize + 17, 1024 * 1024} {
		t.Run(fmt.Sprint(size), func(t *testing.T) {
			plain := make([]byte, size+len(sqliteSignature))
			copy(plain, sqliteSignature)
			if _, err := rand.New(rand.NewSource(int64(size))).Read(plain[len(sqliteSignature):]); err != nil {
				t.Fatal(err)
			}
			ref := makeFileReference("0123456789abcdef", "source.db", rekeyTestSHA(plain))
			expected := originalRekeyOracle(t, plain, ref)
			root := t.TempDir()
			input, output := filepath.Join(root, "source.db"), filepath.Join(root, "output.db")
			rekeyTestWrite(t, input, plain)
			if err := rekeyFile(input, output, &ref, keySpec); err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(expected, rekeyTestRead(t, output)) || ref.Size != len(expected) || ref.EncryptedSHA != rekeyTestSHA(expected) {
				t.Fatal("streaming codec changed encrypted client bytes or metadata")
			}
			if !bytes.Equal(plain, rekeyTestRead(t, input)) {
				t.Fatal("source bytes changed")
			}
			sha, length, err := hashSQLiteFile(input)
			if err != nil || sha != ref.SHA || length != int64(len(plain)) {
				t.Fatalf("streamed clear hash: %s %d %v", sha, length, err)
			}
		})
	}
}

func TestCipherStreamsPreserveKeyStateAndCallerBuffers(t *testing.T) {
	plain := make([]byte, 3*clientDBBufferSize+37)
	rand.New(rand.NewSource(39)).Read(plain)
	expected := append([]byte(nil), plain...)
	key := keySpec
	hwdecrypt.DecryptBuffer(&key, expected)
	var destination bytes.Buffer
	writer := &rekeyCipherWriter{output: &destination, key: keySpec}
	for position := 0; position < len(plain); {
		count := []int{1, 7, 65533, 131091}[position%4]
		if count > len(plain)-position {
			count = len(plain) - position
		}
		input := append([]byte(nil), plain[position:position+count]...)
		before := append([]byte(nil), input...)
		written, err := writer.Write(input)
		if err != nil || written != count || !bytes.Equal(input, before) {
			t.Fatalf("writer changed caller buffer: %d %v", written, err)
		}
		position += count
	}
	if !bytes.Equal(destination.Bytes(), expected) || writer.key != key || writer.count != int64(len(plain)) {
		t.Fatal("chunked encryption lost cipher state")
	}
	reader := &rekeyCipherReader{input: bytes.NewReader(expected), key: keySpec, digest: sha1.New()}
	var decoded bytes.Buffer
	buffer := make([]byte, 97)
	if _, err := io.CopyBuffer(&decoded, reader, buffer); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(decoded.Bytes(), plain) || reader.key != key || reader.count != int64(len(expected)) || !bytes.Equal(reader.digest.Sum(nil), mustSHABytes(expected)) {
		t.Fatal("chunked decryption or ciphertext hash differs")
	}
}

func mustSHABytes(data []byte) []byte { hash := sha1.Sum(data); return hash[:] }

type clientDBFailingWriter struct{ err error }

func (writer clientDBFailingWriter) Write(input []byte) (int, error) {
	return len(input) - 1, writer.err
}

func TestCipherWriterPropagatesOutputFailure(t *testing.T) {
	for _, failure := range []error{nil, errors.New("synthetic disk failure")} {
		writer := &rekeyCipherWriter{output: clientDBFailingWriter{failure}, key: keySpec}
		count, err := writer.Write([]byte("some data"))
		if err == nil || count != 8 || writer.count != 8 {
			t.Fatalf("short/error write swallowed: %d %v", count, err)
		}
		if failure == nil && err != io.ErrShortWrite {
			t.Fatalf("short write error: %v", err)
		}
		if failure != nil && !errors.Is(err, failure) {
			t.Fatalf("original write error lost: %v", err)
		}
	}
}

func TestRekeySourceChangeNeverReplacesDestinationOrReference(t *testing.T) {
	for _, cached := range []bool{false, true} {
		t.Run(fmt.Sprint(cached), func(t *testing.T) {
			root := t.TempDir()
			input, output := filepath.Join(root, "source.db"), filepath.Join(root, "output.db")
			plain := append([]byte(sqliteSignature), bytes.Repeat([]byte("original"), 1000)...)
			ref := makeFileReference("0123456789abcdef", "source.db", rekeyTestSHA(plain))
			ref.EncryptedSHA, ref.Size = "unchanged", 111
			beforeRef := ref
			destination := []byte("existing invalid destination must survive failure")
			if cached {
				destination = originalRekeyOracle(t, plain, ref)
			}
			rekeyTestWrite(t, output, destination)
			plain[len(sqliteSignature)] ^= 1
			rekeyTestWrite(t, input, plain)
			if err := rekeyFile(input, output, &ref, keySpec); err == nil {
				t.Fatal("source changed after expected SHA was acquired")
			}
			if ref != beforeRef || !bytes.Equal(destination, rekeyTestRead(t, output)) {
				t.Fatal("failure published output or metadata")
			}
			files, _ := filepath.Glob(filepath.Join(root, ".rekey-*"))
			if len(files) != 0 {
				t.Fatal("failure left temporary output")
			}
		})
	}
}

func TestSQLiteStreamRejectsInvalidSourcesAndInvalidHash(t *testing.T) {
	root := t.TempDir()
	input, output := filepath.Join(root, "source.db"), filepath.Join(root, "output.db")
	for _, clear := range [][]byte{nil, []byte("SQLite format 3"), bytes.Repeat([]byte("x"), 100)} {
		rekeyTestWrite(t, input, clear)
		if _, _, err := hashSQLiteFile(input); err == nil {
			t.Fatal("invalid source accepted by hash stage")
		}
		ref := makeFileReference("0123456789abcdef", "source.db", rekeyTestSHA(clear))
		if err := rekeyFile(input, output, &ref, keySpec); err == nil {
			t.Fatal("invalid source accepted by compression stage")
		}
		if _, err := os.Stat(output); !os.IsNotExist(err) {
			t.Fatal("invalid source published output")
		}
	}
	ref := makeFileReference("0123456789abcdef", "source.db", "bad")
	if err := rekeyFile(input, output, &ref, keySpec); err == nil {
		t.Fatal("invalid SHA accepted")
	}
	if _, _, err := hashSQLiteFile(root); err == nil {
		t.Fatal("directory accepted as database")
	}
	if _, _, err := hashSQLiteFile(filepath.Join(root, "missing")); err == nil {
		t.Fatal("missing source accepted")
	}
}
