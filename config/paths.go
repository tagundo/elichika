package config

import "path/filepath"

// DataPath preserves standalone relative paths while resolving embedded paths
// without changing the process working directory shared with the game.
func DataPath(path string) string {
	if RootPath == "" || filepath.IsAbs(path) {
		return path
	}
	return filepath.Join(RootPath, path)
}
