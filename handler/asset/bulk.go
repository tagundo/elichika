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
	"time"
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
	log.Printf("download_packs: %d missing of %d; downloading %d at a time\n", total, len(names), workers)
	if total == 0 {
		log.Println("download_packs: nothing to do - everything is already cached")
		return
	}

	var done, failed, bytesTotal int64

	// live progress: print files done / MB downloaded / speed every few seconds so it's clearly
	// working. bytesTotal updates as data arrives (countWriter), so speed is shown even mid-file.
	stop := make(chan struct{})
	var repWg sync.WaitGroup
	repWg.Add(1)
	go func() {
		defer repWg.Done()
		t := time.NewTicker(3 * time.Second)
		defer t.Stop()
		lastBytes := int64(0)
		lastTime := time.Now()
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				b := atomic.LoadInt64(&bytesTotal)
				now := time.Now()
				mbps := float64(b-lastBytes) / now.Sub(lastTime).Seconds() / 1e6
				lastBytes, lastTime = b, now
				log.Printf("download_packs: %d/%d files, %.1f MB so far, %.1f MB/s\n",
					atomic.LoadInt64(&done), total, float64(b)/1e6, mbps)
			}
		}
	}()

	ch := make(chan string)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for name := range ch {
				if err := downloadFromURLProgress(cdnURL(name), packPath(name), &bytesTotal); err != nil {
					atomic.AddInt64(&failed, 1)
					log.Printf("download_packs: failed %s: %v\n", name, err)
				}
				atomic.AddInt64(&done, 1)
			}
		}()
	}
	for _, name := range todo {
		ch <- name
	}
	close(ch)
	wg.Wait()
	close(stop)
	repWg.Wait()
	log.Printf("download_packs: finished - %d downloaded, %d failed, %.1f MB total\n",
		total-int(failed), failed, float64(atomic.LoadInt64(&bytesTotal))/1e6)
}
