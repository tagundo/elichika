package asset

// serve a whole pack/metapack file, acting as the cdn.
// this replaces gin's plain static file server so that, with cdn_cache enabled, a pack that isn't on
// disk yet is fetched from the upstream CDN and cached.
//
// the route is a catch-all (*fileName) to match gin's original r.Static behavior: besides flat pack
// names, the game also downloads nested paths like /static/<masterVersion>/masterdata_a_ko.
//
// on a cache miss the file is streamed to the client and written to the cache at the same time, so
// the first request is about as fast as downloading from the CDN directly (instead of waiting for
// elichika to fully download the file before sending the client anything).

import (
	"elichika/config"
	"elichika/log"
	"elichika/router"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

func staticWhole(ctx *gin.Context) {
	// a catch-all param keeps the leading slash, e.g. "/8d4c19e12fb304cf/masterdata_a_ko"
	file := strings.TrimPrefix(ctx.Param("fileName"), "/")

	if p, ok := localPath(file); ok { // already cached, or migrated from static
		ctx.File(p)
		return
	}
	if !cacheEnabled() {
		// not a caching cdn: serve from static (404 if missing), same as before
		ctx.File(config.StaticDataPath + file)
		return
	}

	// cache miss. range requests are uncommon for whole files; fall back to download-then-serve so
	// http.ServeFile can satisfy the range correctly.
	if ctx.GetHeader("Range") != "" {
		ctx.File(ensureLocalFile(file))
		return
	}

	lock := cacheLockFor(file)
	lock.Lock()
	defer lock.Unlock()
	if p, ok := localPath(file); ok { // another request cached it while we waited
		ctx.File(p)
		return
	}
	streamWholeFromCdn(ctx, file, cacheDir()+file)
}

// streamWholeFromCdn proxies a whole file from the upstream CDN to the client while writing it to the
// cache at the same time.
func streamWholeFromCdn(ctx *gin.Context, fileName, dest string) {
	res, err := http.Get(cdnURL(fileName))
	if err != nil {
		log.Printf("cdn fetch failed for %s: %v\n", fileName, err)
		ctx.Status(http.StatusBadGateway)
		return
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		ctx.Status(res.StatusCode)
		return
	}

	ctx.Header("Content-Type", "application/octet-stream")
	if res.ContentLength >= 0 {
		ctx.Header("Content-Length", fmt.Sprint(res.ContentLength))
	}

	dir := filepath.Dir(dest)
	var tmp *os.File
	if err := os.MkdirAll(dir, 0755); err == nil {
		tmp, err = os.CreateTemp(dir, ".tmp-*")
		if err != nil {
			tmp = nil
		}
	}
	if tmp == nil {
		// can't write the cache file; still proxy to the client without caching
		log.Printf("warning: serving %s from cdn without caching\n", fileName)
		io.Copy(ctx.Writer, res.Body)
		return
	}
	tmpName := tmp.Name()

	// write to the client and the cache file at the same time
	written, copyErr := io.Copy(io.MultiWriter(ctx.Writer, tmp), res.Body)
	tmp.Close()
	if copyErr != nil || (res.ContentLength >= 0 && written != res.ContentLength) {
		os.Remove(tmpName) // incomplete: don't keep a corrupt cache file
		return
	}
	if err := os.Rename(tmpName, dest); err != nil {
		os.Remove(tmpName)
	}
}

func init() {
	router.AddHandler("/static", "GET", "/*fileName", staticWhole)
}
