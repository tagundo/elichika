package asset

import (
	"archive/tar"
	"bufio"
	"elichika/config"
	"elichika/log"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// archiveConnPlan is the connection counts tried per part, high to low (like the
// Termux aria2c flow): start at the configured max (archive_connections, default
// 8, clamped 1-32) and halve on throttling down to a single stream. archive.org
// tolerates a handful of parallel range requests; too many risk 503/rate-limits.
func archiveConnPlan() []int {
	n := 8
	if config.Conf != nil && config.Conf.ArchiveConnections != nil {
		n = int(*config.Conf.ArchiveConnections)
	}
	if n < 1 {
		n = 1
	}
	if n > 32 {
		n = 32
	}
	plan := []int{}
	for c := n; c > 1; c /= 2 {
		plan = append(plan, c)
	}
	return append(plan, 1)
}

// The archive.org item holding the bulk static assets, re-split as multiple
// COMPLETE uncompressed tar parts per region (packs_GL.tar.000.., packs_JP.tar.000..).
// Every part is an independent archive split on file boundaries, so parts are
// downloaded + extracted one at a time (temp use stays ~1 part) in any order.
// All entries are "packs/<basename>" — exactly one wrapper level, which
// stripFirstComponent removes to land the flat basenames in the cache dir.
const archiveItem = "llsifas-elichika-static-data"

// var (not const) so tests can point it at a local server.
var archiveBase = "https://archive.org/download/" + archiveItem + "/"

// archiveRegionTag maps the server's region names to the item's file naming.
var archiveRegionTag = map[string]string{
	"gl": "GL",
	"jp": "JP",
}

// DownloadArchive downloads the bulk CDN asset tar parts from archive.org for the
// given regions ("gl"/"jp") and extracts them into the cache dir — the same thing
// as the Termux menu's "Download ALL game files (from archive.org)". It does not
// touch the game CDN. Fully-extracted parts are skipped via marker files and
// existing files are kept, so it is resumable at both the part and file level.
// Restart the server afterwards so the new files get indexed.
func DownloadArchive(regions []string) {
	dir := cacheDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		log.Println("download_archive: cannot create cache dir:", err)
		return
	}
	failed := 0
	for _, r := range regions {
		tag, ok := archiveRegionTag[r]
		if !ok {
			log.Println("download_archive: unknown region:", r)
			continue
		}
		parts, err := archiveParts(tag)
		if err != nil {
			log.Printf("download_archive: %s: cannot list parts: %v\n", r, err)
			failed++
			continue
		}
		log.Printf("download_archive: %s: %d part(s) (into %s)\n", r, len(parts), dir)
		for i, part := range parts {
			if strings.ContainsAny(part, "/\\") {
				log.Printf("download_archive: %s: skipping suspicious part name %q\n", r, part)
				failed++
				continue
			}
			marker := filepath.Join(dir, ".archive_done_"+part)
			if _, err := os.Stat(marker); err == nil {
				log.Printf("download_archive: %s part %d/%d (%s) already extracted, skipping\n",
					r, i+1, len(parts), part)
				continue
			}
			url := archiveBase + part
			log.Printf("download_archive: %s part %d/%d: %s\n", r, i+1, len(parts), url)
			if err := downloadAndExtractTar(url, dir); err != nil {
				// parts are independent — keep going so a rerun only redoes the failures
				log.Printf("download_archive: %s part %s FAILED: %v\n", r, part, err)
				failed++
				continue
			}
			// mark only after the whole part extracted; the leading dot keeps the
			// marker out of the pack index (see buildPackIndex). A marker that cannot
			// be written must count as a failure or the next run silently redoes the part.
			if f, err := os.Create(marker); err == nil {
				f.Close()
			} else {
				log.Printf("download_archive: %s: cannot write marker for %s: %v\n", r, part, err)
				failed++
			}
		}
	}
	if failed > 0 {
		log.Printf("download_archive: finished with %d failed part(s)/region(s) — run it again to retry just those.\n", failed)
	}
	log.Println("download_archive: all done. Restart the server so it indexes the new files.")
}

// archiveParts returns the region's ordered part file names. The item ships a
// packs_<TAG>.parts.txt (one part name per line); if that cannot be fetched,
// fall back to probing packs_<TAG>.tar.000, .001, ... until a 404.
func archiveParts(tag string) ([]string, error) {
	url := fmt.Sprintf("%spacks_%s.parts.txt", archiveBase, tag)
	// httpClient (not http.DefaultClient) so a stalled archive.org fails in bounded
	// time instead of hanging the whole run — see its comment in cache.go.
	resp, err := httpClient.Get(url)
	if err == nil {
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			var parts []string
			sc := bufio.NewScanner(resp.Body)
			for sc.Scan() {
				line := strings.TrimSpace(sc.Text())
				if line != "" {
					parts = append(parts, line)
				}
			}
			if sc.Err() == nil && len(parts) > 0 {
				return parts, nil
			}
		}
		log.Printf("download_archive: parts list unavailable (status %d), probing part files\n", resp.StatusCode)
	} else {
		log.Printf("download_archive: parts list fetch failed (%v), probing part files\n", err)
	}

	// fallback: probe sequentially numbered parts until the first 404
	var parts []string
	for n := 0; n < 100; n++ {
		name := fmt.Sprintf("packs_%s.tar.%03d", tag, n)
		head, err := httpClient.Head(archiveBase + name)
		if err != nil {
			return parts, fmt.Errorf("probing %s: %w", name, err)
		}
		head.Body.Close()
		if head.StatusCode == http.StatusNotFound {
			break
		}
		if head.StatusCode != http.StatusOK {
			return parts, fmt.Errorf("probing %s: http status %d", name, head.StatusCode)
		}
		parts = append(parts, name)
	}
	if len(parts) == 0 {
		return nil, fmt.Errorf("no parts found for %s", tag)
	}
	return parts, nil
}

// downloadAndExtractTar downloads one tar part into destDir (parallel ranged
// connections when the server supports it, so it isn't limited to one slow
// stream) and extracts it, dropping the "packs/" wrapper (--strip-components=1)
// and keeping files that already exist (--skip-old-files). The part is fetched
// to a dot-prefixed temp file first (invisible to the pack index) so extraction
// only ever runs on a fully, correctly-sized download.
func downloadAndExtractTar(url, destDir string) error {
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return err
	}
	tmp := filepath.Join(destDir, ".dl-"+urlBase(url))
	defer os.Remove(tmp)
	if err := downloadPart(url, tmp); err != nil {
		return err
	}
	return extractTarFile(tmp, destDir)
}

// downloadPart downloads url to dest, retrying with progressively fewer parallel
// connections (then a single stream) on failure — mirroring the Termux aria2c
// step-down. Each attempt starts the file fresh, so no cross-attempt corruption.
func downloadPart(url, dest string) error {
	size, ranges := probeSize(url)
	plan := archiveConnPlan()
	if size <= 0 || !ranges {
		plan = []int{1} // server won't range/size — single stream is the only option
	}
	var lastErr error
	for _, conns := range plan {
		if conns > 1 {
			log.Printf("download_archive: downloading with %d connections (%.0f MB)...\n",
				conns, float64(size)/(1024*1024))
		} else {
			log.Printf("download_archive: downloading (single connection)...\n")
		}
		err := downloadPartOnce(url, dest, size, conns)
		if err == nil {
			return nil
		}
		lastErr = err
		log.Printf("download_archive: failed (%v), retrying with fewer connections...\n", err)
		time.Sleep(2 * time.Second)
	}
	return lastErr
}

func downloadPartOnce(url, dest string, size int64, conns int) error {
	f, err := os.Create(dest) // truncates any prior attempt
	if err != nil {
		return err
	}
	pr := newDownloadProgress(size)
	var runErr error
	if conns > 1 && size > 0 {
		if err := f.Truncate(size); err != nil {
			f.Close()
			pr.stop()
			return err
		}
		runErr = downloadSegments(url, f, size, conns, pr)
	} else {
		runErr = streamInto(url, f, pr)
	}
	pr.stop()
	cerr := f.Close()
	if runErr != nil {
		return runErr
	}
	if cerr != nil {
		return cerr
	}
	got := pr.total()
	if size > 0 && got != size {
		return fmt.Errorf("incomplete body: got %d of %d bytes", got, size)
	}
	if got == 0 {
		return fmt.Errorf("empty response")
	}
	return nil
}

// downloadSegments splits [0,size) into conns ranges downloaded concurrently,
// each written at its absolute offset via WriteAt (safe for disjoint writes).
func downloadSegments(url string, f *os.File, size int64, conns int, pr *downloadProgress) error {
	segSize := (size + int64(conns) - 1) / int64(conns)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var firstErr error
	for i := 0; i < conns; i++ {
		start := int64(i) * segSize
		if start >= size {
			break
		}
		end := start + segSize - 1
		if end >= size {
			end = size - 1
		}
		wg.Add(1)
		go func(start, end int64) {
			defer wg.Done()
			if err := downloadRangeInto(url, f, start, end, pr); err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
			}
		}(start, end)
	}
	wg.Wait()
	return firstErr
}

func downloadRangeInto(url string, f *os.File, start, end int64, pr *downloadProgress) error {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end))
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusPartialContent {
		return fmt.Errorf("range %d-%d: http status %d", start, end, resp.StatusCode)
	}
	buf := make([]byte, 256*1024)
	off := start
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.WriteAt(buf[:n], off); werr != nil {
				return werr
			}
			off += int64(n)
			pr.add(int64(n))
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return rerr
		}
	}
	if off-1 != end {
		return fmt.Errorf("range %d-%d short: got %d bytes", start, end, off-start)
	}
	return nil
}

func streamInto(url string, f *os.File, pr *downloadProgress) error {
	resp, err := httpClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("http status %d", resp.StatusCode)
	}
	buf := make([]byte, 256*1024)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			pr.add(int64(n))
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return rerr
		}
	}
	return nil
}

// probeSize HEADs url for its size and whether it supports byte ranges.
func probeSize(url string) (int64, bool) {
	resp, err := httpClient.Head(url)
	if err != nil {
		return -1, false
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return -1, false
	}
	return resp.ContentLength, strings.EqualFold(resp.Header.Get("Accept-Ranges"), "bytes")
}

// extractTarFile extracts a local tar into destDir: strip the "packs/" wrapper,
// skip existing files, guard against tar-slip, and write each file via a
// dot-prefixed temp + rename so an interrupted extract leaves no truncated pack.
func extractTarFile(tarPath, destDir string) error {
	f, err := os.Open(tarPath)
	if err != nil {
		return err
	}
	defer f.Close()
	tr := tar.NewReader(f)
	extracted, skipped := 0, 0
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		name := stripFirstComponent(hdr.Name)
		if name == "" {
			continue
		}
		target := filepath.Join(destDir, filepath.FromSlash(name))
		if !pathWithin(destDir, target) {
			return fmt.Errorf("tar entry escapes destination: %q", hdr.Name)
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
		case tar.TypeReg, tar.TypeRegA:
			if _, statErr := os.Stat(target); statErr == nil {
				skipped++
				continue // keep existing file (incremental)
			}
			if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
				return err
			}
			tmp := filepath.Join(filepath.Dir(target), ".extract-"+filepath.Base(target))
			out, err := os.Create(tmp)
			if err != nil {
				return err
			}
			if _, err := io.Copy(out, tr); err != nil {
				out.Close()
				os.Remove(tmp)
				return err
			}
			if err := out.Close(); err != nil {
				os.Remove(tmp)
				return err
			}
			if err := os.Rename(tmp, target); err != nil {
				os.Remove(tmp)
				return err
			}
			extracted++
			if extracted%1000 == 0 {
				log.Printf("download_archive: extracted %d, skipped %d\n", extracted, skipped)
			}
		}
	}
	if extracted+skipped == 0 {
		return fmt.Errorf("archive contained no files (empty or truncated response)")
	}
	log.Printf("download_archive: extracted %d, skipped %d\n", extracted, skipped)
	return nil
}

// pathWithin reports whether target is destDir itself or inside it.
func pathWithin(destDir, target string) bool {
	rel, err := filepath.Rel(filepath.Clean(destDir), filepath.Clean(target))
	if err != nil {
		return false
	}
	return rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)))
}

func stripFirstComponent(p string) string {
	p = strings.TrimPrefix(p, "./")
	i := strings.IndexByte(p, '/')
	if i < 0 {
		return "" // a top-level entry with no inner path (the wrapper dir itself)
	}
	return p[i+1:]
}

// urlBase returns the last path segment of a URL (for naming the temp file).
func urlBase(url string) string {
	if i := strings.LastIndexByte(url, '/'); i >= 0 {
		url = url[i+1:]
	}
	if i := strings.IndexAny(url, "?#"); i >= 0 {
		url = url[:i]
	}
	if url == "" {
		return "part.tar"
	}
	return url
}

// downloadProgress logs live download speed + size every few seconds so the long
// multi-GB download isn't silent, then a final average-speed line.
type downloadProgress struct {
	size   int64
	n      int64 // atomic
	start  time.Time
	stopCh chan struct{}
	done   chan struct{}
}

func newDownloadProgress(size int64) *downloadProgress {
	p := &downloadProgress{size: size, start: time.Now(),
		stopCh: make(chan struct{}), done: make(chan struct{})}
	go p.loop()
	return p
}

func (p *downloadProgress) add(n int64)  { atomic.AddInt64(&p.n, n) }
func (p *downloadProgress) total() int64 { return atomic.LoadInt64(&p.n) }

func (p *downloadProgress) loop() {
	defer close(p.done)
	t := time.NewTicker(3 * time.Second)
	defer t.Stop()
	lastN, lastT := int64(0), p.start
	for {
		select {
		case <-p.stopCh:
			return
		case now := <-t.C:
			cur := p.total()
			dt := now.Sub(lastT).Seconds()
			spd := 0.0
			if dt > 0 {
				spd = float64(cur-lastN) / dt / (1024 * 1024)
			}
			lastN, lastT = cur, now
			mb := float64(cur) / (1024 * 1024)
			if p.size > 0 {
				log.Printf("download_archive: %.0f/%.0f MB (%.1f MB/s)\n",
					mb, float64(p.size)/(1024*1024), spd)
			} else {
				log.Printf("download_archive: %.0f MB (%.1f MB/s)\n", mb, spd)
			}
		}
	}
}

func (p *downloadProgress) stop() {
	close(p.stopCh)
	<-p.done
	cur := p.total()
	el := time.Since(p.start).Seconds()
	avg := 0.0
	if el > 0 {
		avg = float64(cur) / el / (1024 * 1024)
	}
	log.Printf("download_archive: downloaded %.0f MB in %.0fs (avg %.1f MB/s)\n",
		float64(cur)/(1024*1024), el, avg)
}
