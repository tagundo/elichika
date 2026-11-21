package asset

// Bulk-download support: fetch every pack/metapack the game needs that isn't already cached, from
// the game CDN. This is meant for the files that aren't in the archive.org dumps (content newer than
// the dump snapshot) - get the bulk from the archive first (menu "Download all game files"), then
// use this for the remainder. (Those files also download automatically as you play.)

import (
	"database/sql"
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"

	"fmt"
	"net/url"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// DownloadAllMissing downloads, with `workers` parallel downloads, every whole pack/metapack file the
// game needs that isn't already cached, from the CDN. Re-running it only fetches what's still missing.
func DownloadAllMissing(workers int) {
	if err := downloadMissingFiles(workers, assetdata.AllWholeFiles()); err != nil {
		log.Println("download_packs:", err)
	}
}

// DownloadMissing downloads only the selected profiles, including common files
// and whole metapacks. Invalid or unloaded profiles fail before any CDN request.
func DownloadMissing(workers int, selection assetdata.DownloadSelection) error {
	names, err := assetdata.SelectWholeFilesWithFallback(selection, func(profile assetdata.AssetProfile, names map[string]struct{}) error {
		return readInstalledDownloadProfile(config.AssetPath, profile, names)
	})
	if err != nil {
		return err
	}
	log.Printf("download_packs: selected %d whole files (%s)\n", len(names), selection)
	return downloadMissingFiles(workers, names)
}

func readInstalledDownloadProfile(assetRoot string, profile assetdata.AssetProfile, names map[string]struct{}) error {
	platform := "a"
	if profile.Platform == assetdata.PlatformIOS {
		platform = "i"
	}
	file := "asset_" + platform + "_" + string(profile.Language) + ".db"
	path, err := filepath.Abs(filepath.Join(assetRoot, "db", string(profile.Region), file))
	if err != nil {
		return err
	}
	uri := url.URL{Scheme: "file", Path: filepath.ToSlash(path), RawQuery: "mode=ro"}
	if strings.HasPrefix(uri.Path, "//") {
		uri.Host = "localhost"
	} else if !strings.HasPrefix(uri.Path, "/") {
		uri.Path = "/" + uri.Path
	}
	database, err := sql.Open("sqlite", uri.String())
	if err != nil {
		return err
	}
	defer database.Close()
	// Match the profile index: a metapack and its constituent slices use
	// one whole file, and rows common to multiple profiles share one key.
	rows, err := database.Query(`SELECT metapack_name FROM metapack
		UNION SELECT COALESCE(metapack_name, pack_name) FROM m_asset_package_mapping`)
	if err != nil {
		return fmt.Errorf("read installed %s: %w", file, err)
	}
	defer rows.Close()
	for rows.Next() {
		var name sql.NullString
		if err := rows.Scan(&name); err != nil {
			return err
		}
		if name.Valid && name.String != "" {
			names[name.String] = struct{}{}
		}
	}
	return rows.Err()
}

func downloadMissingFiles(workers int, names map[string]struct{}) error {
	host := *config.Conf.CdnServer
	if host == "" || host == "elichika" || host == "elichika_tls" {
		return fmt.Errorf("cdn_server must be a real CDN url (not 'elichika'); aborting")
	}
	if _, err := sourceCDNURL(host, "source-check", nil); err != nil {
		return err
	}
	if workers < 1 {
		workers = 1
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
		return nil
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
				source, err := sourceCDNURL(host, name, nil)
				if err == nil {
					err = downloadFromURLProgress(source, packPath(name), &bytesTotal)
				}
				if err != nil {
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
	if failed != 0 {
		return fmt.Errorf("%d of %d downloads failed", failed, total)
	}
	return nil
}
