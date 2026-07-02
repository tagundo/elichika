package asset

import (
	"archive/tar"
	"bufio"
	"elichika/log"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

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

// downloadAndExtractTar streams a tar from url and extracts it into destDir,
// dropping the leading path component (the "packs/" wrapper, like tar
// --strip-components=1) and skipping files that already exist (--skip-old-files).
// Each file is written via a dot-prefixed temp + rename, so an interrupted run
// never leaves a truncated pack under its real name (which the skip-existing
// check — and the pack index — would otherwise trust forever).
func downloadAndExtractTar(url, destDir string) error {
	resp, err := httpClient.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("http status %d", resp.StatusCode)
	}

	counted := &progressReader{r: resp.Body, total: resp.ContentLength}
	tr := tar.NewReader(counted)
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
		// tar-slip guard: never let ".."/absolute entry names escape destDir.
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
			// temp in the same dir (dot prefix: invisible to the pack index), then
			// rename — a mid-copy failure never leaves a truncated real file.
			tmp := filepath.Join(filepath.Dir(target), ".extract-"+filepath.Base(target))
			f, err := os.Create(tmp)
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				f.Close()
				os.Remove(tmp)
				return err
			}
			if err := f.Close(); err != nil {
				os.Remove(tmp)
				return err
			}
			if err := os.Rename(tmp, target); err != nil {
				os.Remove(tmp)
				return err
			}
			extracted++
			if extracted%500 == 0 {
				log.Printf("download_archive: %d extracted, %d skipped, %s\n",
					extracted, skipped, counted.human())
			}
		}
	}
	// completeness: an empty 200 (or a body truncated exactly on a tar block
	// boundary) yields a clean EOF — don't let that mark the part as done.
	if counted.total > 0 && counted.n != counted.total {
		return fmt.Errorf("incomplete body: got %d of %d bytes", counted.n, counted.total)
	}
	if extracted+skipped == 0 {
		return fmt.Errorf("archive contained no files (empty or truncated response)")
	}
	log.Printf("download_archive: extracted %d, skipped %d (%s)\n", extracted, skipped, counted.human())
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

// progressReader counts bytes read so the long archive download isn't silent.
type progressReader struct {
	r     io.Reader
	n     int64
	total int64
}

func (p *progressReader) Read(b []byte) (int, error) {
	n, err := p.r.Read(b)
	p.n += int64(n)
	return n, err
}

func (p *progressReader) human() string {
	mb := float64(p.n) / (1024 * 1024)
	if p.total > 0 {
		return fmt.Sprintf("%.0f/%.0f MB", mb, float64(p.total)/(1024*1024))
	}
	return fmt.Sprintf("%.0f MB", mb)
}
