//go:build elichika_inprocess

package clientdb

import (
	"bytes"
	"crypto/sha256"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

func verifiedCacheFixture(t *testing.T) (string, string, []byte, FileReference) {
	t.Helper()
	root := t.TempDir()
	plain := make([]byte, 2*clientDBBufferSize+37)
	copy(plain, sqliteSignature)
	_, _ = rand.New(rand.NewSource(71)).Read(plain[len(sqliteSignature):])
	input, output := filepath.Join(root, "source.db"), filepath.Join(root, "encrypted.db")
	rekeyTestWrite(t, input, plain)
	ref := makeFileReference("0123456789abcdef", "source.db", rekeyTestSHA(plain))
	if err := rekeyFile(input, output, &ref, keySpec); err != nil {
		t.Fatal(err)
	}
	return input, output, plain, ref
}

func tryWarmCipher(t *testing.T, path string, ref *FileReference, clearSize int64, key hwdecrypt.HwdKeyset) (bool, rekeyVerifiedProof) {
	t.Helper()
	input, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	info, err := input.Stat()
	if err != nil {
		t.Fatal(err)
	}
	var proof rekeyVerifiedProof
	return reuseVerifiedCipher(input, path, ref, key, clearSize, info, &proof), proof
}

func TestVerifiedCipherWarmHitHashesCompleteCipherAndRestoresVerifiedMetadata(t *testing.T) {
	_, output, plain, ref := verifiedCacheFixture(t)
	key, ok := cipherProofKey(output, &ref, keySpec, int64(len(plain)))
	if !ok {
		t.Fatal("key missing")
	}
	proof, ok := verifiedCipherProofs.get(key)
	if !ok || !proof.valid {
		t.Fatal("successful atomic publication did not seed a proof")
	}
	ciphertext := rekeyTestRead(t, output)
	if proof.cipherSHA256 != sha256.Sum256(ciphertext) || proof.size != int64(len(ciphertext)) {
		t.Fatal("cold proof did not cover every ciphertext byte")
	}
	ref.EncryptedSHA, ref.Size = "caller metadata is not trusted", 1
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); !hit {
		t.Fatal("validated unchanged output did not use warm proof")
	}
	if ref.EncryptedSHA != rekeyTestSHA(ciphertext) || ref.Size != len(ciphertext) {
		t.Fatal("warm proof did not restore independently verified metadata")
	}
	proof.cipherSHA256[0] ^= 1
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); !hit {
		t.Fatal("caller mutated cache through a returned proof copy")
	}
}

func TestVerifiedCipherTamperWithRestoredSizeAndTimeMustMissAndRevalidate(t *testing.T) {
	for _, where := range []string{"first", "middle", "last"} {
		t.Run(where, func(t *testing.T) {
			input, output, plain, ref := verifiedCacheFixture(t)
			expected := rekeyTestRead(t, output)
			before, err := os.Stat(output)
			if err != nil {
				t.Fatal(err)
			}
			tampered := append([]byte(nil), expected...)
			index := 0
			if where == "middle" {
				index = len(tampered) / 2
			}
			if where == "last" {
				index = len(tampered) - 1
			}
			tampered[index] ^= 0x80
			rekeyTestWrite(t, output, tampered)
			if err = os.Chtimes(output, before.ModTime(), before.ModTime()); err != nil {
				t.Fatal(err)
			}
			if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); hit {
				t.Fatal("content changed under identical size/timestamp was trusted")
			}
			key, _ := cipherProofKey(output, &ref, keySpec, int64(len(plain)))
			if _, ok := verifiedCipherProofs.get(key); ok {
				t.Fatal("bad proof was not invalidated")
			}
			if err = rekeyFile(input, output, &ref, keySpec); err != nil {
				t.Fatal(err)
			}
			// A changed unused DEFLATE padding bit may still decode to exactly
			// the authoritative bytes. Preserve that legacy acceptance policy;
			// either a repair or a fresh full decode must establish validity.
			if !reuseRekeyed(input, output, &ref, keySpec) {
				t.Fatal("changed output was neither repaired nor independently revalidated")
			}
			actual := rekeyTestRead(t, output)
			if ref.EncryptedSHA != rekeyTestSHA(actual) || ref.Size != len(actual) {
				t.Fatal("revalidated metadata did not match actual ciphertext")
			}
			if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); !hit {
				t.Fatal("verified repair did not seed the newly published inode")
			}
		})
	}
}

func TestVerifiedCipherExpectedClearKeySizeCanonicalPathAndInodeAreBound(t *testing.T) {
	input, output, plain, ref := verifiedCacheFixture(t)
	wrongSHA := ref
	wrongSHA.SHA = strings.Repeat("0", 40)
	if hit, _ := tryWarmCipher(t, output, &wrongSHA, int64(len(plain)), keySpec); hit {
		t.Fatal("different expected clear hash reused proof")
	}
	wrongKey := keySpec
	wrongKey.Key1 ^= 1
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), wrongKey); hit {
		t.Fatal("different derived HWD key reused proof")
	}
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)+1), keySpec); hit {
		t.Fatal("different clear size reused proof")
	}
	clone := filepath.Join(t.TempDir(), "same-bytes-different-output.db")
	rekeyTestWrite(t, clone, rekeyTestRead(t, output))
	if hit, _ := tryWarmCipher(t, clone, &ref, int64(len(plain)), keySpec); hit {
		t.Fatal("different canonical output path reused proof")
	}
	alias := filepath.Join(filepath.Dir(output), "output-alias.db")
	if err := os.Symlink(output, alias); err != nil {
		t.Fatal(err)
	}
	if hit, _ := tryWarmCipher(t, alias, &ref, int64(len(plain)), keySpec); !hit {
		t.Fatal("same canonical file alias lost its validated proof")
	}
	replacement := filepath.Join(filepath.Dir(output), "replacement.db")
	rekeyTestWrite(t, replacement, rekeyTestRead(t, output))
	if err := os.Rename(replacement, output); err != nil {
		t.Fatal(err)
	}
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); hit {
		t.Fatal("replaced output inode reused old proof")
	}
	if err := rekeyFile(input, output, &ref, keySpec); err != nil {
		t.Fatal(err)
	}
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); !hit {
		t.Fatal("full revalidation did not adopt the replacement")
	}
}

func TestVerifiedCipherUnpublishedAndFailedGenerationCannotSeedCache(t *testing.T) {
	input, output, plain, ref := verifiedCacheFixture(t)
	unpublished := filepath.Join(t.TempDir(), "unpublished.db")
	rekeyTestWrite(t, unpublished, rekeyTestRead(t, output))
	var proof rekeyVerifiedProof
	copyRef := ref
	if !verifyRekeyed(input, unpublished, &copyRef, keySpec, &proof) || !proof.valid {
		t.Fatal("full verification fixture failed")
	}
	key, _ := cipherProofKey(unpublished, &copyRef, keySpec, int64(len(plain)))
	if _, ok := verifiedCipherProofs.get(key); ok {
		t.Fatal("verification alone published a reusable proof")
	}
	wrong := ref
	wrong.SHA = strings.Repeat("0", 40)
	if err := rekeyFile(input, unpublished, &wrong, keySpec); err == nil {
		t.Fatal("mismatching authoritative source hash was accepted")
	}
	wrongCacheKey, _ := cipherProofKey(unpublished, &wrong, keySpec, int64(len(plain)))
	if _, ok := verifiedCipherProofs.get(wrongCacheKey); ok {
		t.Fatal("failed source validation seeded a proof")
	}
	targetDir := filepath.Join(t.TempDir(), "cannot-replace-directory.db")
	if err := os.Mkdir(targetDir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := rekeyFile(input, targetDir, &copyRef, keySpec); err == nil {
		t.Fatal("failed atomic output rename was accepted")
	}
	dirKey, _ := cipherProofKey(targetDir, &copyRef, keySpec, int64(len(plain)))
	if _, ok := verifiedCipherProofs.get(dirKey); ok {
		t.Fatal("failed atomic publish seeded a proof")
	}
	if temporary, _ := filepath.Glob(filepath.Join(filepath.Dir(targetDir), ".rekey-*")); len(temporary) != 0 {
		t.Fatal("failed publication left a temporary output")
	}
}

func TestVerifiedCipherTrailingBytesNeverBecomeTrustedProof(t *testing.T) {
	input, output, plain, ref := verifiedCacheFixture(t)
	expected := rekeyTestRead(t, output)
	rekeyTestWrite(t, output, append(append([]byte(nil), expected...), 0))
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(plain)), keySpec); hit {
		t.Fatal("trailing cipher byte reused a warm proof")
	}
	if reuseRekeyed(input, output, &ref, keySpec) {
		t.Fatal("trailing bytes passed full DEFLATE boundary verification")
	}
	if err := rekeyFile(input, output, &ref, keySpec); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(expected, rekeyTestRead(t, output)) {
		t.Fatal("trailing data was not repaired")
	}
}

func TestVerifiedCipherWarmOutputDoesNotBypassAuthoritativeClearHash(t *testing.T) {
	input, output, plain, ref := verifiedCacheFixture(t)
	before, err := os.Stat(input)
	if err != nil {
		t.Fatal(err)
	}
	changed := append([]byte(nil), plain...)
	changed[len(changed)-1] ^= 0x40
	rekeyTestWrite(t, input, changed)
	if err = os.Chtimes(input, before.ModTime(), before.ModTime()); err != nil {
		t.Fatal(err)
	}
	if err = rekeyFile(input, output, &ref, keySpec); err == nil {
		t.Fatal("cached cipher proof bypassed the current full clear-source hash")
	}
	ref.SHA = rekeyTestSHA(changed)
	if err = rekeyFile(input, output, &ref, keySpec); err != nil {
		t.Fatal(err)
	}
	if hit, _ := tryWarmCipher(t, output, &ref, int64(len(changed)), keySpec); !hit {
		t.Fatal("changed source was not independently rebuilt and verified")
	}
	if !bytes.Equal(rekeyTestRead(t, input), changed) {
		t.Fatal("source was mutated by cached verification")
	}
}

func TestVerifiedCipherProofFIFOAndReplacementMetadataStayBounded(t *testing.T) {
	c := newVerifiedCipherCache(2)
	one, two, three := verifiedCipherKey{path: "one"}, verifiedCipherKey{path: "two"}, verifiedCipherKey{path: "three"}
	for i := 0; i < 10000; i++ {
		c.put(one, rekeyVerifiedProof{valid: true, size: int64(i)})
	}
	if len(c.proofs) != 1 || len(c.order) != 1 {
		t.Fatal("updates grew eviction bookkeeping")
	}
	c.put(two, rekeyVerifiedProof{})
	c.put(three, rekeyVerifiedProof{})
	if _, ok := c.get(one); ok {
		t.Fatal("oldest proof was not evicted")
	}
	if len(c.proofs) != 2 || len(c.order) != 2 {
		t.Fatal("proof cache exceeded fixed capacity")
	}
	for i := 0; i < 10000; i++ {
		c.remove(two)
		c.put(two, rekeyVerifiedProof{})
	}
	if len(c.proofs) != 2 || len(c.order) != 2 {
		t.Fatal("remove/reinsert grew cache metadata")
	}
}

func TestVerifiedCipherProofCacheConcurrentWorkersRemainBounded(t *testing.T) {
	c := newVerifiedCipherCache(8)
	var group sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		group.Add(1)
		go func(worker int) {
			defer group.Done()
			for i := 0; i < 2000; i++ {
				key := verifiedCipherKey{path: string(rune('a' + (i+worker)%16))}
				c.put(key, rekeyVerifiedProof{valid: true, size: int64(i)})
				_, _ = c.get(key)
				if i%3 == 0 {
					c.remove(key)
				}
			}
		}(worker)
	}
	group.Wait()
	if len(c.proofs) > 8 || len(c.order) > 8 || len(c.proofs) != len(c.order) {
		t.Fatal("concurrent proof cache grew past fixed bounds")
	}
	seen := map[verifiedCipherKey]bool{}
	for _, key := range c.order {
		if seen[key] {
			t.Fatal("duplicate eviction key")
		}
		seen[key] = true
	}
}
