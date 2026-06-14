package asset

// Acting as a caching CDN: when cdn_cache is enabled, elichika serves the packs itself instead of
// redirecting the game to the upstream CDN. Any pack that isn't already on disk is downloaded from
// the upstream (cdn_server) into the cache directory on first request, and reused from there afterwards.
//
// The cache directory is cdn_cache_dir. When it's empty it defaults to the static/ folder, so on
// PC/Docker no extra folder is needed. On termux/Android, set cdn_cache_dir to the shared sukusta
// folder (e.g. ~/storage/downloads/sukusta/packs) so the cache is shared with the game and the
// llas_asset_extractor.py tooling.

import (
	"elichika/config"
	"elichika/log"
	"elichika/utils"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// one lock per pack name so concurrent requests for the same pack download it only once
var cacheLocks sync.Map // string -> *sync.Mutex

func cacheLockFor(name string) *sync.Mutex {
	lock, _ := cacheLocks.LoadOrStore(name, &sync.Mutex{})
	return lock.(*sync.Mutex)
}

// cacheEnabled reports whether elichika should act as a caching CDN.
func cacheEnabled() bool {
	return config.Conf.CdnCache != nil && *config.Conf.CdnCache
}

// cacheDir returns the directory (with a trailing slash) where cached packs are stored and looked up.
// It's cdn_cache_dir, with ~ expanded; when unset it falls back to the static/ folder.
func cacheDir() string {
	dir := ""
	if config.Conf.CdnCacheDir != nil {
		dir = *config.Conf.CdnCacheDir
	}
	if dir == "" {
		return config.StaticDataPath
	}
	if strings.HasPrefix(dir, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			dir = home + dir[1:]
		}
	}
	if !strings.HasSuffix(dir, "/") {
		dir += "/"
	}
	return dir
}

// ensureLocalFile returns a local filesystem path to the given whole pack/metapack file.
// Lookup order:
//  1. <cdn_cache_dir>/<fileName>
//  2. static/<fileName>
//  3. if cdn_cache is enabled, download from the upstream CDN (cdn_server) into <cdn_cache_dir>.
//
// If the file can't be found nor cached, the static/ path is returned so the caller fails the same
// way it would for any missing file.
func ensureLocalFile(fileName string) string {
	cachePath := cacheDir() + fileName
	if utils.PathExists(cachePath) {
		return cachePath
	}
	staticPath := config.StaticDataPath + fileName
	if (cacheDir() != config.StaticDataPath) && utils.PathExists(staticPath) {
		return staticPath
	}
	if !cacheEnabled() {
		// not a caching CDN: behave as before and let the caller fail on the (missing) static file
		return staticPath
	}

	lock := cacheLockFor(fileName)
	lock.Lock()
	defer lock.Unlock()
	// another request may have downloaded it while we waited for the lock
	if utils.PathExists(cachePath) {
		return cachePath
	}
	if err := downloadPack(fileName, cachePath); err != nil {
		log.Printf("failed to cache pack %s from cdn: %v\n", fileName, err)
	}
	return cachePath
}

// cdnURL builds the upstream CDN url for a pack/metapack file.
func cdnURL(fileName string) string {
	return strings.TrimSuffix(*config.Conf.CdnServer, "/") + "/" + fileName
}

// downloadPack downloads a whole pack/metapack file from the upstream CDN into dest atomically.
func downloadPack(fileName, dest string) error {
	url := cdnURL(fileName)
	log.Printf("caching pack from cdn: %s\n", url)
	res, err := http.Get(url)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status %d for %s", res.StatusCode, url)
	}

	dir := filepath.Dir(dest)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	// download to a temp file then rename so a partial download is never served
	tmp, err := os.CreateTemp(dir, ".tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	_, err = io.Copy(tmp, res.Body)
	tmp.Close()
	if err != nil {
		os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, dest); err != nil {
		os.Remove(tmpName)
		return err
	}
	return nil
}
}

// cacheDir returns the directory (with a trailing slash) where cached packs are stored and looked up.
// It's cdn_cache_dir, with ~ expanded; when unset it falls back to the static/ folder.
func cacheDir() string {
	dir := ""
	if config.Conf.CdnCacheDir != nil {
		dir = *config.Conf.CdnCacheDir
	}
	if dir == "" {
		return config.StaticDataPath
	}
	if strings.HasPrefix(dir, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			dir = home + dir[1:]
		}
	}
	if !strings.HasSuffix(dir, "/") {
		dir += "/"
	}
	return dir
}

// ensureLocalFile returns a local filesystem path to the given whole pack/metapack file.
// Lookup order:
//  1. <cdn_cache_dir>/<fileName>
//  2. static/<fileName>
//  3. if cdn_cache is enabled, download from the upstream CDN (cdn_server) into <cdn_cache_dir>.
//
// If the file can't be found nor cached, the static/ path is returned so the caller fails the same
// way it would for any missing file.
func ensureLocalFile(fileName string) string {
	cachePath := cacheDir() + fileName
	if utils.PathExists(cachePath) {
		return cachePath
	}
	staticPath := config.StaticDataPath + fileName
	if (cacheDir() != config.StaticDataPath) && utils.PathExists(staticPath) {
		return staticPath
	}
	if !cacheEnabled() {
		// not a caching CDN: behave as before and let the caller fail on the (missing) static file
		return staticPath
	}

	lock := cacheLockFor(fileName)
	lock.Lock()
	defer lock.Unlock()
	// another request may have downloaded it while we waited for the lock
	if utils.PathExists(cachePath) {
		return cachePath
	}
	if err := downloadPack(fileName, cachePath); err != nil {
		log.Printf("failed to cache pack %s from cdn: %v\n", fileName, err)
	}
	return cachePath
}

// downloadPack downloads a whole pack/metapack file from the upstream CDN into dest atomically.
func downloadPack(fileName, dest string) error {
	url := strings.TrimSuffix(*config.Conf.CdnServer, "/") + "/" + fileName
	log.Printf("caching pack from cdn: %s\n", url)
	res, err := http.Get(url)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status %d for %s", res.StatusCode, url)
	}

	dir := filepath.Dir(dest)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	// download to a temp file then rename so a partial download is never served
	tmp, err := os.CreateTemp(dir, ".tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	_, err = io.Copy(tmp, res.Body)
	tmp.Close()
	if err != nil {
		os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, dest); err != nil {
		os.Remove(tmpName)
		return err
	}
	return nil
}
