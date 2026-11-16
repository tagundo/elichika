package asset

// Bulk-download support: fetch every pack/metapack the game needs that isn't already cached, from
// the game CDN. This is meant for the files that aren't in the archive.org dumps (content newer than
// the dump snapshot) - get the bulk from the archive first (menu "Download all game files"), then
// use this for the remainder. (Those files also download automatically as you play.)

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"

	"context"
	"fmt"
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
	names, err := assetdata.SelectWholeFiles(selection)
	if err != nil {
		return err
	}
	log.Printf("download_packs: selected %d whole files (%s); all loaded profiles contain %d whole files\n",
		len(names), selection, assetdata.ProfileWholeFileCount())
	return downloadMissingFiles(workers, names)
}

// DownloadProgress is a bounded snapshot, never a growing list of file names.
// CompletedBytes counts transferred bytes, including bytes of a failed file.
// TotalBytes is zero when the source catalogs do not provide a whole-file size.
type DownloadProgress struct {
	Stage          string `json:"stage"`
	CompletedFiles int64  `json:"completed_files"`
	TotalFiles     int64  `json:"total_files"`
	CompletedBytes int64  `json:"completed_bytes"`
	TotalBytes     int64  `json:"total_bytes"`
}

// DownloadMissingContext reuses the CLI's profile selection and atomic pack
// cache writes. Cancellation reaches active HTTP requests and body reads.
// Progress callbacks are serialized and run at most once per second plus the
// initial/final snapshots, rather than once per byte or downloaded file.
func DownloadMissingContext(ctx context.Context, workers int, selection assetdata.DownloadSelection, progress func(DownloadProgress)) error {
	names, err := assetdata.SelectWholeFiles(selection)
	if err != nil {
		return err
	}
	log.Printf("download_packs: selected %d whole files (%s); all loaded profiles contain %d whole files\n",
		len(names), selection, assetdata.ProfileWholeFileCount())
	return downloadMissingFilesContext(ctx, workers, names, progress)
}

func downloadMissingFiles(workers int, names map[string]struct{}) error {
	return downloadMissingFilesWithTimeout(context.Background(), workers, names, nil, 0)
}

func downloadMissingFilesContext(ctx context.Context, workers int, names map[string]struct{}, progress func(DownloadProgress)) error {
	return downloadMissingFilesWithTimeout(ctx, workers, names, progress, 10*time.Minute)
}

func downloadMissingFilesWithTimeout(ctx context.Context, workers int, names map[string]struct{}, progress func(DownloadProgress), fileTimeout time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
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
		if err := ctx.Err(); err != nil {
			return err
		}
		if _, ok := localPath(name); !ok {
			todo = append(todo, name)
		}
	}
	total := len(todo)
	log.Printf("download_packs: %d missing of %d; downloading %d at a time\n", total, len(names), workers)
	if progress != nil {
		progress(DownloadProgress{Stage: "downloading", TotalFiles: int64(total)})
	}
	if total == 0 {
		log.Println("download_packs: nothing to do - everything is already cached")
		if progress != nil {
			progress(DownloadProgress{Stage: "finished"})
		}
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
		t := time.NewTicker(time.Second)
		defer t.Stop()
		lastBytes := int64(0)
		lastTime := time.Now()
		lastLog := lastTime
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				b := atomic.LoadInt64(&bytesTotal)
				now := time.Now()
				mbps := float64(b-lastBytes) / now.Sub(lastTime).Seconds() / 1e6
				lastBytes, lastTime = b, now
				if progress != nil {
					progress(DownloadProgress{Stage: "downloading", CompletedFiles: atomic.LoadInt64(&done), TotalFiles: int64(total), CompletedBytes: b})
				}
				if now.Sub(lastLog) >= 3*time.Second {
					log.Printf("download_packs: %d/%d files, %.1f MB so far, %.1f MB/s\n",
						atomic.LoadInt64(&done), total, float64(b)/1e6, mbps)
					lastLog = now
				}
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
				if ctx.Err() != nil {
					return
				}
				source, err := sourceCDNURL(host, name, nil)
				if err == nil {
					// A stalled body cannot retain a worker forever. The shared
					// client keeps its connect/TLS/header timeout behavior.
					fileContext, cancel := context.WithCancel(ctx)
					if fileTimeout > 0 {
						cancel()
						fileContext, cancel = context.WithTimeout(ctx, fileTimeout)
					}
					err = downloadFromURLProgressWithContext(fileContext, source, packPath(name), &bytesTotal, nil)
					cancel()
				}
				if err != nil {
					if ctx.Err() != nil {
						return
					}
					atomic.AddInt64(&failed, 1)
					log.Printf("download_packs: failed %s: %v\n", name, err)
				}
				atomic.AddInt64(&done, 1)
			}
		}()
	}
queue:
	for _, name := range todo {
		select {
		case <-ctx.Done():
			break queue
		case ch <- name:
		}
	}
	close(ch)
	wg.Wait()
	close(stop)
	repWg.Wait()
	stage := "finished"
	if ctx.Err() != nil {
		stage = "cancelled"
	} else if failed != 0 {
		stage = "failed"
	}
	if progress != nil {
		progress(DownloadProgress{Stage: stage, CompletedFiles: atomic.LoadInt64(&done), TotalFiles: int64(total), CompletedBytes: atomic.LoadInt64(&bytesTotal)})
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	log.Printf("download_packs: finished - %d downloaded, %d failed, %.1f MB total\n",
		total-int(failed), failed, float64(atomic.LoadInt64(&bytesTotal))/1e6)
	if failed != 0 {
		return fmt.Errorf("%d of %d downloads failed", failed, total)
	}
	return nil
}
