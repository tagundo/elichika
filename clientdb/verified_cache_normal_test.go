//go:build !elichika_inprocess

package clientdb

import "testing"

func TestVerifiedCipherProofCacheIsDisabledOutsideInProcessHost(t *testing.T) {
	if newVerifiedCipherDigest() != nil {
		t.Fatal("standalone producer unexpectedly computes/seeds iOS runtime proof hashes")
	}
	if reuseVerifiedCipher(nil, "", nil, keySpec, 0, nil, nil) {
		t.Fatal("standalone producer unexpectedly bypasses full decode")
	}
	// No-op even for an empty proof: legacy producers have no process cache.
	rememberVerifiedCipher("", nil, keySpec, rekeyVerifiedProof{})
}
