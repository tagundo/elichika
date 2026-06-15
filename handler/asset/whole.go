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
	"strings"

	"github.com/gin-gonic/gin"
)

// clientWriter writes to the client, but once a write fails (the client disconnected) it silently
// discards the rest. This lets the surrounding io.Copy keep reading from the CDN so the cache file
// still gets finished even when the client gave up.
type clientWriter struct {
	w      io.Writer
	broken bool
}

func (c *clientWriter) Write(p []byte) (int, error) {
	if !c.broken {
		if _, err := c.w.Write(p); err != nil {
			c.broken = true
		}
	}
	return len(p), nil
}

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
	streamWholeFromCdn(ctx, file, packPath(file))
}

// streamWholeFromCdn proxies a whole file from the upstream CDN to the client while writing it to the
// cache at the same time.
func streamWholeFromCdn(ctx *gin.Context, fileName, dest string) {
	res, err := httpClient.Get(cdnURL(fileName))
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

	// Write the temp file on internal storage (RootPath), not in the cache dir: the cache dir is
	// often slow shared storage on Android, and writing there while streaming would throttle the
	// client download to disk speed. We move it to the cache dir after the client has the bytes.
	tmpBase := config.RootPath
	if tmpBase == "" {
		tmpBase = "."
	}
	tmp, err := os.CreateTemp(tmpBase, ".cdncache-*")
	if err != nil {
		// can't make a temp file; still proxy to the client without caching
		log.Printf("warning: serving %s from cdn without caching: %v\n", fileName, err)
		io.Copy(ctx.Writer, res.Body)
		return
	}
	tmpName := tmp.Name()

	// stream to the client and the (fast) temp file at the same time. The client is wrapped so that
	// if it disconnects (e.g. the game times out on a slow CDN), we keep downloading from the CDN to
	// finish the cache file - otherwise the next retry would re-download the same slow file forever.
	cw := &clientWriter{w: ctx.Writer}
	written, copyErr := io.Copy(io.MultiWriter(cw, tmp), res.Body)
	tmp.Close()
	if copyErr != nil || written == 0 || (res.ContentLength >= 0 && written != res.ContentLength) {
		os.Remove(tmpName) // empty/incomplete: don't keep a corrupt cache file
		return
	}
	// the bytes are downloaded; persist into the cache dir (may be slow shared storage).
	if err := moveToCache(tmpName, dest); err != nil {
		log.Printf("failed to store cache for %s: %v\n", fileName, err)
		os.Remove(tmpName)
	}
}

func init() {
	router.AddHandler("/static", "GET", "/*fileName", staticWhole)
}
