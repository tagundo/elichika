package asset

// Bulk-download support: fetch every pack/metapack the game needs that isn't already cached, from
// the game CDN. This is meant for the files that aren't in the archive.org dumps (content newer than
// the dump snapshot) - get the bulk from the archive first (menu "Download all game files"), then
// use this for the remainder. (Those files also download automatically as you play.)

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"

	"sync"
	"sync/atomic"
)

// DownloadAllMissing downloads, with `workers` parallel downloads, every whole pack/metapack file the
// game needs that isn't already cached, from the CDN. Re-running it only fetches what's still missing.
func DownloadAllMissing(workers int) {
	host := *config.Conf.CdnServer
	if host == "" || host == "elichika" || host == "elichika_tls" {
		log.Println("download_packs: cdn_server must be a real CDN url (not 'elichika'); aborting")
		return
	}
	if workers < 1 {
		workers = 1
	}

	// whole files the game serves: every metapack, plus every pack that isn't part of a metapack.
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
	log.Printf("download_packs: %d files, %d missing; downloading from the cdn with %d workers\n",
		len(names), total, workers)
	if total == 0 {
		log.Println("download_packs: nothing to do - everything is already cached")
		return
	}

	// log progress about 50 times regardless of how many files there are (so small batches still
	// show movement instead of looking frozen until they finish).
	step := int64(total / 50)
	if step < 1 {
		step = 1
	}

	ch := make(chan string)
	var wg sync.WaitGroup
	var done, failed int64
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for name := range ch {
				if err := downloadFromURL(cdnURL(name), packPath(name)); err != nil {
					atomic.AddInt64(&failed, 1)
					log.Printf("download_packs: failed %s: %v\n", name, err)
				}
				if n := atomic.AddInt64(&done, 1); n%step == 0 || n == int64(total) {
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
