package asset

// Bulk-download support: fetch every pack/metapack the CDN serves that isn't already cached.
// Unlike the archive.org tar (one big all-or-nothing file), this downloads per-pack straight from
// the CDN and skips anything already present, so it only pulls what's missing.

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"

	"sync"
	"sync/atomic"
)

// DownloadAllMissing downloads, with `workers` parallel downloads, every whole pack/metapack file the
// CDN serves that isn't already in the cache. Re-running it only fetches what's still missing.
func DownloadAllMissing(workers int) {
	host := *config.Conf.CdnServer
	if host == "" || host == "elichika" || host == "elichika_tls" {
		log.Println("download_packs: cdn_server must be a real CDN url (not 'elichika'); aborting")
		return
	}
	if workers < 1 {
		workers = 1
	}

	// the CDN serves whole files: every metapack, plus every pack that isn't part of a metapack.
	names := map[string]struct{}{}
	for name := range assetdata.Metapack {
		names[name] = struct{}{}
	}
	for _, pack := range assetdata.Pack {
		if pack.MetapackName == nil {
			names[pack.PackName] = struct{}{}
		}
	}

	todo := make([]string, 0, len(names))
	for name := range names {
		if _, ok := localPath(name); !ok {
			todo = append(todo, name)
		}
	}
	total := len(todo)
	log.Printf("download_packs: %d cdn files, %d missing; downloading with %d workers\n",
		len(names), total, workers)
	if total == 0 {
		log.Println("download_packs: nothing to do - everything is already cached")
		return
	}

	ch := make(chan string)
	var wg sync.WaitGroup
	var done, failed int64
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for name := range ch {
				if err := downloadPack(name, packPath(name)); err != nil {
					atomic.AddInt64(&failed, 1)
					log.Printf("download_packs: failed %s: %v\n", name, err)
				}
				if n := atomic.AddInt64(&done, 1); n%100 == 0 || n == int64(total) {
					log.Printf("download_packs: %d/%d\n", n, total)
				}
			}
		}()
	}
	for _, name := range todo {
		ch <- name
	}
	close(ch)
	wg.Wait()
	log.Printf("download_packs: finished - %d downloaded, %d failed\n", total-int(failed), failed)
}
