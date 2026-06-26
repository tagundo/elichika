package asset

// Acting as a caching CDN: when cdn_cache is enabled, elichika serves the packs itself instead of
// redirecting the game to the upstream CDN. Any pack that isn't already on disk is downloaded from
// the upstream (cdn_server) into the cache directory on first request, and reused from there afterwards.
//
// The cache directory is cdn_cache_dir; when empty (the PC default) it is the local static/ folder
// sitting next to the server, so nothing extra is needed on PC/Docker. On Android cdn_cache_dir is
// the shared sukusta folder, so the cache lines up with the game and the llas_asset_extractor.py
// tooling; there, static/ is consulted only as a legacy source and any pack files left in it are
// migrated into the cache dir.

import (
	"elichika/config"
	"elichika/log"
	"elichika/utils"

	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// httpClient is used for all CDN/archive downloads. It bounds connect and response-header time so a
// hung/unresponsive server (archive.org sometimes stalls) fails quickly and the caller can try the
// next source, instead of blocking a worker forever. It does NOT bound total time, so slow-but-
// progressing downloads of large files still complete.
var httpClient = &http.Client{
	Transport: &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		DialContext:           (&net.Dialer{Timeout: 15 * time.Second}).DialContext,
		TLSHandshakeTimeout:   15 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
		IdleConnTimeout:       90 * time.Second,
	},
}

// one lock per pack name so concurrent requests for the same pack download it only once
var cacheLocks sync.Map // string -> *sync.Mutex

func cacheLockFor(name string) *sync.Mutex {
	lock, _ := cacheLocks.LoadOrStore(name, &sync.Mutex{})
	return lock.(*sync.Mutex)
}

// Pack files can live at any depth under the cache dir: flat (files/<name>), or in buckets like the
// archive.org dumps (files/pac0/<name>, ...). We index every file by basename once so a pack can be
// found by name regardless of how the cache is organised, like llas_asset_extractor.py does.
// The index is built lazily and reflects on-disk files at that moment; files added later (e.g. a
// fresh tar extract) are picked up after a server restart.
var (
	packIndex     map[string]string
	packIndexOnce sync.Once
	packIndexMu   sync.RWMutex
)

func buildPackIndex() {
	idx := map[string]string{}
	root := cacheDir()
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // skip unreadable dirs/files
		}
		if d.IsDir() {
			return nil
		}
		name := d.Name()
		if strings.HasPrefix(name, ".") {
			return nil // skip temp/hidden files (.cdncache-*, .tmp-*)
		}
		idx[name] = path
		return nil
	})
	packIndexMu.Lock()
	packIndex = idx
	packIndexMu.Unlock()
	log.Printf("cdn cache: indexed %d files under %s\n", len(idx), root)
}

// indexLookup finds a pack file by name anywhere under the cache dir.
func indexLookup(name string) (string, bool) {
	packIndexOnce.Do(buildPackIndex)
	packIndexMu.RLock()
	p, ok := packIndex[name]
	packIndexMu.RUnlock()
	if ok && utils.PathExists(p) {
		return p, true
	}
	return "", false
}

// cacheEnabled reports whether elichika should act as a caching CDN.
func cacheEnabled() bool {
	return config.Conf.CdnCache != nil && *config.Conf.CdnCache
}

// cacheDir returns the directory (with a trailing slash) where cached packs are stored and looked up.
// It's cdn_cache_dir, with ~ expanded; when empty (the PC default) it is the local static/ folder.
func cacheDir() string {
	dir := ""
	if config.Conf.CdnCacheDir != nil {
		dir = *config.Conf.CdnCacheDir
	}
	if dir == "" {
		// empty (the PC default) means the local static/ folder next to the server.
		// StaticDataPath already ends in "/", so return it directly.
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

// packPath returns the canonical cache path for a pack/metapack file: directly under the cache dir.
// Bulk dumps may instead place packs in bucket subdirs (e.g. pac0/<name>); those are still found by
// the recursive index (see localPath).
func packPath(file string) string {
	return cacheDir() + file
}

// localPath resolves a whole pack/metapack file to an existing local path, without downloading.
// It returns (path, true) when the file is already available locally.
//
// Lookup order:
//  1. <cdn_cache_dir>/<file>
//  2. by name anywhere under <cdn_cache_dir> (the recursive index) — handles bucketed dumps like
//     <cdn_cache_dir>/pac0/<name>
//  3. static/<file> — a legacy source. Flat pack/metapack files found here are migrated into the
//     cache; nested paths (the generated masterdata <version>/... files) are served from static/
//     as-is and never moved.
//
// When the file isn't found, it returns the canonical path (where it would be downloaded) and false.
func localPath(file string) (string, bool) {
	canonical := packPath(file)
	if utils.PathExists(canonical) {
		return canonical, true
	}
	// bucketed dumps (e.g. pac0/<name>): find it by name via the recursive index.
	if !strings.Contains(file, "/") {
		if p, ok := indexLookup(file); ok {
			return p, true
		}
	}
	staticPath := config.StaticDataPath + file
	if (cacheDir() != config.StaticDataPath) && utils.PathExists(staticPath) {
		if !strings.Contains(file, "/") {
			// legacy pack file placed in static/ by an older setup: move it into the cache.
			if err := moveToCache(staticPath, canonical); err == nil {
				log.Printf("migrated pack from static into cache: %s\n", file)
				return canonical, true
			} else {
				log.Printf("failed to migrate %s from static (serving from static): %v\n", file, err)
			}
		}
		return staticPath, true
	}
	return canonical, false
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
	dest := packPath(file)
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
	return downloadFromURL(url, dest)
}

// countWriter atomically adds the number of bytes written to *n, for a live download total/speed.
type countWriter struct{ n *int64 }

func (c countWriter) Write(p []byte) (int, error) {
	atomic.AddInt64(c.n, int64(len(p)))
	return len(p), nil
}

// downloadFromURL downloads url into dest atomically (temp file + rename). It returns an error for
// any non-200 response (e.g. 404) without writing anything, so callers can try another source.
func downloadFromURL(url, dest string) error {
	return downloadFromURLProgress(url, dest, nil)
}

// downloadFromURLProgress is downloadFromURL but, when progress != nil, adds bytes to it as they
// arrive so a caller can show live progress.
func downloadFromURLProgress(url, dest string, progress *int64) error {
	res, err := httpClient.Get(url)
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
	var w io.Writer = tmp
	if progress != nil {
		w = io.MultiWriter(tmp, countWriter{progress})
	}
	written, err := io.Copy(w, res.Body)
	tmp.Close()
	if err != nil {
		os.Remove(tmpName)
		return err
	}
	// reject empty or truncated responses so we never cache a 0-byte / partial pack
	if written == 0 || (res.ContentLength >= 0 && written != res.ContentLength) {
		os.Remove(tmpName)
		return fmt.Errorf("incomplete download for %s (%d of %d bytes)", url, written, res.ContentLength)
	}
	if err := os.Rename(tmpName, dest); err != nil {
		os.Remove(tmpName)
		return err
	}
	return nil
}
