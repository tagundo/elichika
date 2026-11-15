//go:build elichika_inprocess

package clientdb

// The signed application ships a prepared, migrated payload. Runtime upgrades
// have their own transactional guards; invoking Git in the game is prohibited.
func isNotChanged(_ string) bool { return false }
