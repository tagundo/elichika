//go:build !elichika_inprocess

package clientdb

import (
	"hash"
	"os"

	hwdecrypt "gitlab.com/tatara_hisoka/gohwdecrypt"
)

// Standalone/Android behavior stays full-decode; no persistent proof cache or
// change to the official prepared data producer is introduced by the iOS host.
func newVerifiedCipherDigest() hash.Hash { return nil }
func reuseVerifiedCipher(*os.File, string, *FileReference, hwdecrypt.HwdKeyset, int64, os.FileInfo, *rekeyVerifiedProof) bool {
	return false
}
func rememberVerifiedCipher(string, *FileReference, hwdecrypt.HwdKeyset, rekeyVerifiedProof) {}
