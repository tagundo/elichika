package asset

// Bulk-download support: fetch every pack/metapack the game needs that isn't already cached.
//
// For each missing file we try the archive.org dumps first (they don't burden the game CDN and we
// only pull the files we actually need, not the whole tar), and fall back to the game CDN only for
// files the archive doesn't have (e.g. content newer than the dump snapshot).
//
// archive.org can serve a single file out of a .tar via:
//   https://archive.org/download/<item>/<tar>/<wrapper>%2F<bucket>%2F<name>
// where <wrapper> is the tar name without ".tar" and <bucket> is "meta"+firstchar for metapacks or
// "pkg"+firstchar for packs (e.g. metapack 0a5i68 -> meta0/0a5i68, pack vq4jiw -> pkgv/vq4jiw).

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"

	"sync"
	"sync/atomic"
)

const archiveItemBase = "https://archive.org/download/ll-sifas-cdn-data/"

// the .tar dumps on archive.org and their internal wrapper folder (tar name without ".tar").
var archiveTars = []struct{ tar, wrapper string }{
	{"sifas-gl-cdn-assets-2d61e7b4e89961c7.tar", "sifas-gl-cdn-assets-2d61e7b4e89961c7"},
	{"sifas-jp-cdn-assets-b66ec2295e9a00aa.tar", "sifas-jp-cdn-assets-b66ec2295e9a00aa"},
}

type packNeed struct {
	name string
	meta bool // true: metapack (meta<c> bucket); false: pack (pkg<c> bucket)
	jp   bool // came from the jp locale: try the jp dump first
}

// fetchPack downloads one pack/metapack into dest, archive.org first then the game CDN.
// It returns "archive", "cdn", or "" (failure).
func fetchPack(n packNeed, dest string) string {
	if n.name == "" {
		return ""
	}
	bucket := "pkg"
	if n.meta {
		bucket = "meta"
	}
	bucket += n.name[:1]

	// try the more-likely region's dump first
	order := []int{0, 1}
	if n.jp {
		order = []int{1, 0}
	}
	for _, i := range order {
		t := archiveTars[i]
		url := archiveItemBase + t.tar + "/" + t.wrapper + "%2F" + bucket + "%2F" + n.name
		if err := downloadFromURL(url, dest); err == nil {
			return "archive"
		}
	}
	if err := downloadFromURL(cdnURL(n.name), dest); err == nil {
		return "cdn"
	}
	return ""
}

// DownloadAllMissing downloads, with `workers` parallel downloads, every whole pack/metapack file the
// game needs that isn't already cached. Re-running it only fetches what's still missing.
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
	items := []packNeed{}
	for name := range assetdata.Metapack {
		items = append(items, packNeed{name, true, assetdata.NameToLocale[name] == "ja"})
	}
	for _, pack := range assetdata.Pack {
		if pack.MetapackName == nil {
			items = append(items, packNeed{pack.PackName, false, assetdata.NameToLocale[pack.PackName] == "ja"})
		}
	}

	todo := make([]packNeed, 0, len(items))
	for _, it := range items {
		if _, ok := localPath(it.name); !ok {
			todo = append(todo, it)
		}
	}
	total := len(todo)
	log.Printf("download_packs: %d files, %d missing; archive.org first, game CDN as fallback, %d workers\n",
		len(items), total, workers)
	if total == 0 {
		log.Println("download_packs: nothing to do - everything is already cached")
		return
	}

	ch := make(chan packNeed)
	var wg sync.WaitGroup
	var done, fromArchive, fromCdn, failed int64
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for it := range ch {
				switch fetchPack(it, packPath(it.name)) {
				case "archive":
					atomic.AddInt64(&fromArchive, 1)
				case "cdn":
					atomic.AddInt64(&fromCdn, 1)
				default:
					atomic.AddInt64(&failed, 1)
					log.Printf("download_packs: failed %s\n", it.name)
				}
				if n := atomic.AddInt64(&done, 1); n%100 == 0 || n == int64(total) {
					log.Printf("download_packs: %d/%d (archive %d, cdn %d, failed %d)\n",
						n, total, atomic.LoadInt64(&fromArchive), atomic.LoadInt64(&fromCdn), atomic.LoadInt64(&failed))
				}
			}
		}()
	}
	for _, it := range todo {
		ch <- it
	}
	close(ch)
	wg.Wait()
	log.Printf("download_packs: finished - %d from archive.org, %d from game CDN, %d failed\n",
		fromArchive, fromCdn, failed)
}
