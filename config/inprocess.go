//go:build elichika_inprocess

package config

import (
	"fmt"
	"os"
	"path/filepath"
)

var hostListen, hostPacks, hostLanguage string

// ConfigureHost provides launch-scoped settings without changing persistent
// configuration or process environment shared with Unity/Python.
func ConfigureHost(listen, packs, language string) {
	hostListen, hostPacks, hostLanguage = listen, packs, language
}

func applyHostOptions() {
	if hostListen != "" {
		*Conf.ServerAddress = hostListen
	}
	if hostPacks != "" {
		*Conf.CdnCacheDir = hostPacks
	}
	if hostLanguage != "" {
		*Conf.Locales = hostLanguage
	}
}

// ConfigureRoot runs before any deferred configuration or database initializer.
func ConfigureRoot(root string) error {
	if !filepath.IsAbs(root) {
		return fmt.Errorf("data_root must be absolute")
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		return fmt.Errorf("data_root: %w", err)
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return fmt.Errorf("data_root must be an existing directory")
	}
	RootPath = filepath.Clean(resolved) + string(os.PathSeparator)
	AssetPath = RootPath + "assets/"
	GlMasterdataPath = AssetPath + "db/gl/"
	JpMasterdataPath = AssetPath + "db/jp/"
	ServerdataPath = RootPath + "serverdata.db"
	UserdataPath = RootPath + "userdata.db"
	YumemichiPath = RootPath + "yumemichi_userdata.db"
	ServerstatePath = RootPath + "serverstate.db"
	StaticDataPath = RootPath + "static/"
	ServerInitJsons = RootPath + "server init jsons/"
	UserDataBackupPath = RootPath + "backup/"
	return nil
}
