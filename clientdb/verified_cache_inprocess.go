//go:build elichika_inprocess

package clientdb

import (
	"crypto/sha256"
	"hash"
	"io"
	"os"
	"path/filepath"
	"sync"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

const verifiedCipherCacheCapacity = 256

type verifiedCipherKey struct {
	path, clearSHA string
	clearSize      int64
	key            hwdecrypt.HwdKeyset
}

type verifiedCipherCache struct {
	mu       sync.Mutex
	capacity int
	proofs   map[verifiedCipherKey]rekeyVerifiedProof
	order    []verifiedCipherKey
}

func newVerifiedCipherCache(capacity int) *verifiedCipherCache {
	return &verifiedCipherCache{capacity: capacity, proofs: make(map[verifiedCipherKey]rekeyVerifiedProof)}
}

var verifiedCipherProofs = newVerifiedCipherCache(verifiedCipherCacheCapacity)

func (c *verifiedCipherCache) get(key verifiedCipherKey) (rekeyVerifiedProof, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	proof, ok := c.proofs[key]
	return proof, ok
}

func (c *verifiedCipherCache) remove(key verifiedCipherKey) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.proofs[key]; !ok {
		return
	}
	delete(c.proofs, key)
	for i, k := range c.order {
		if k == key {
			copy(c.order[i:], c.order[i+1:])
			c.order[len(c.order)-1] = verifiedCipherKey{}
			c.order = c.order[:len(c.order)-1]
			break
		}
	}
}

func (c *verifiedCipherCache) put(key verifiedCipherKey, proof rekeyVerifiedProof) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.capacity < 1 {
		return
	}
	if _, ok := c.proofs[key]; ok {
		c.proofs[key] = proof
		return
	}
	if len(c.order) == c.capacity {
		delete(c.proofs, c.order[0])
		copy(c.order, c.order[1:])
		c.order = c.order[:len(c.order)-1]
	}
	c.proofs[key] = proof
	c.order = append(c.order, key)
}

func newVerifiedCipherDigest() hash.Hash { return sha256.New() }

func cipherProofKey(path string, reference *FileReference, keySpec hwdecrypt.HwdKeyset, size int64) (verifiedCipherKey, bool) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return verifiedCipherKey{}, false
	}
	canonical, err := filepath.EvalSymlinks(absolute)
	if err != nil {
		return verifiedCipherKey{}, false
	}
	return verifiedCipherKey{path: canonical, clearSHA: reference.SHA, clearSize: size, key: reference.getKey(keySpec)}, true
}

func stableVerifiedCipher(input *os.File, path string, before os.FileInfo) bool {
	after, err := input.Stat()
	if err != nil {
		return false
	}
	current, err := os.Stat(path)
	return err == nil && current.Mode().IsRegular() && os.SameFile(before, after) && os.SameFile(before, current) && before.Size() == after.Size() && after.Size() == current.Size() && before.ModTime().Equal(after.ModTime()) && after.ModTime().Equal(current.ModTime())
}

func reuseVerifiedCipher(input *os.File, path string, reference *FileReference, keySpec hwdecrypt.HwdKeyset, clearSize int64, before os.FileInfo, output *rekeyVerifiedProof) bool {
	key, ok := cipherProofKey(path, reference, keySpec, clearSize)
	if !ok {
		return false
	}
	proof, ok := verifiedCipherProofs.get(key)
	if !ok {
		return false
	}
	valid := false
	defer func() {
		if !valid {
			verifiedCipherProofs.remove(key)
			_, _ = input.Seek(0, io.SeekStart)
		}
	}()
	if !proof.valid || proof.identity == nil || !os.SameFile(proof.identity, before) || before.Size() != proof.size {
		return false
	}
	digest := sha256.New()
	count, err := io.CopyBuffer(digest, io.LimitReader(input, before.Size()+1), make([]byte, clientDBBufferSize))
	if err != nil || count != before.Size() || !stableVerifiedCipher(input, path, before) {
		return false
	}
	var actual [32]byte
	copy(actual[:], digest.Sum(nil))
	if actual != proof.cipherSHA256 {
		return false
	}
	afterKey, ok := cipherProofKey(path, reference, keySpec, clearSize)
	if !ok || afterKey != key {
		return false
	}
	reference.EncryptedSHA, reference.Size = proof.encryptedSHA, int(proof.size)
	if output != nil {
		*output = proof
	}
	valid = true
	return true
}

func rememberVerifiedCipher(path string, reference *FileReference, keySpec hwdecrypt.HwdKeyset, proof rekeyVerifiedProof) {
	if !proof.valid || proof.identity == nil || proof.clearSHA != reference.SHA || proof.key != reference.getKey(keySpec) || proof.encryptedSHA != reference.EncryptedSHA || proof.size != int64(reference.Size) {
		return
	}
	key, ok := cipherProofKey(path, reference, keySpec, proof.clearSize)
	if !ok {
		return
	}
	current, err := os.Stat(path)
	if err != nil || !current.Mode().IsRegular() || !os.SameFile(proof.identity, current) || current.Size() != proof.size || !proof.identity.ModTime().Equal(current.ModTime()) {
		return
	}
	verifiedCipherProofs.put(key, proof)
}
