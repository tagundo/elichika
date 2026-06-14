package asset

// Acting as a caching CDN: when cdn_cache is enabled, elichika serves the packs itself instead of
// redirecting the game to the upstream CDN. Any pack that isn't already on disk is downloaded from
// the upstream (cdn_server) into the cache directory on first request, and reused from there afterwards.
//
// The cache directory is cdn_cache_dir (default ~/storage/downloads/sukusta/packs), so the cache is
// shared with the game and the llas_asset_extractor.py tooling. The static/ folder is only consulted
// as a legacy source: if an older setup left pack files there, they are migrated into the cache dir.

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
// It's cdn_cache_dir, with ~ expanded; when explicitly empty it falls back to the static/ folder.
func cacheDir() string {
	dir := ""
	if config.Conf.CdnCacheDir != nil {
		dir = *config.Conf.CdnCacheDir
	}
	if dir == "" {
		// empty falls back to the shared sukusta default, not static/
		dir = config.DefaultCdnCacheDir
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

// localPath resolves a whole pack/metapack file to an existing local path, without downloading.
// It returns (path, true) when the file is already available locally.
//
// Lookup order:
//  1. <cdn_cache_dir>/<file>
//  2. static/<file> — a legacy location. Flat pack/metapack files found here are migrated into the
//     cache dir so everything ends up in one place; nested paths (e.g. the generated
//     masterdata <version>/... files) are served from static/ as-is and never moved.
//
// When the file isn't found, it returns the cache-dir path (where it would be downloaded) and false.
func localPath(file string) (string, bool) {
	cachePath := cacheDir() + file
	if utils.PathExists(cachePath) {
		return cachePath, true
	}
	staticPath := config.StaticDataPath + file
	if (cacheDir() != config.StaticDataPath) && utils.PathExists(staticPath) {
		if !strings.Contains(file, "/") {
			// legacy pack file placed in static/ by an older setup: move it into the cache dir.
			if err := moveToCache(staticPath, cachePath); err == nil {
				log.Printf("migrated pack from static into cache: %s\n", file)
				return cachePath, true
			} else {
				log.Printf("failed to migrate %s from static (serving from static): %v\n", file, err)
			}
		}
		return staticPath, true
	}
	return cachePath, false
}

// ensureLocalFile returns a local filesystem path to the given whole pack/metapack file, downloading
// it from the upstream CDN into the cache dir when cdn_cache is enabled and it isn't already local.
// If it can't be found nor cached, the static/ path is returned so the caller fails the same way it
// would for any missing file.
func ensureLocalFile(file string) string {
	if p, ok := localPath(file); ok {
		return p
	}
	if !cacheEnabled() {
		return config.StaticDataPath + file
	}

	lock := cacheLockFor(file)
	lock.Lock()
	defer lock.Unlock()
	if p, ok := localPath(file); ok { // another request cached it while we waited
		return p
	}
	dest := cacheDir() + file
	if err := downloadPack(file, dest); err != nil {
		log.Printf("failed to cache pack %s from cdn: %v\n", file, err)
	}
	return dest
}

// moveToCache copies src to dst then removes src. It copies (instead of os.Rename) because the cache
// dir and static/ are often on different filesystems on Android (shared storage vs app data), where
// rename across filesystems fails.
func moveToCache(src, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(dst), ".tmp-*")
	if err != nil {
		in.Close()
		return err
	}
	tmpName := tmp.Name()
	_, err = io.Copy(tmp, in)
	in.Close()
	tmp.Close()
	if err != nil {
		os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, dst); err != nil {
		os.Remove(tmpName)
		return err
	}
	os.Remove(src) // best-effort: the copy is the source of truth now
	return nil
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
