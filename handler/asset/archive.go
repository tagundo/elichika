package asset

import (
	"archive/tar"
	"elichika/log"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// archiveItem is the archive.org item that hosts the bulk CDN asset tars. It is split
// into several complete tars per region ("parts") so they can be uploaded/downloaded in
// parallel; a per-region ".manifest" file lists the parts (see pack_ia_tars.py).
const archiveItem = "llsifas-elichika-static-data"

// legacyArchiveItem + legacyArchiveVersions are the older single-tar-per-region dump.
// They are used as a fallback when archiveItem has no manifest for a region yet (e.g.
// during migration, before the parts have been uploaded), so downloads keep working.
const legacyArchiveItem = "ll-sifas-cdn-data"

var legacyArchiveVersions = map[string]string{
	"gl": "2d61e7b4e89961c7",
	"jp": "b66ec2295e9a00aa",
}

func archiveDownloadBase(item string) string {
	return "https://archive.org/download/" + item
}

// regionParts fetches the parts manifest for a region from archiveItem and returns the
// tar filenames it lists. It returns (nil, nil) when there is no manifest yet (404) so
// the caller can fall back to the legacy single tar.
func regionParts(region string) ([]string, error) {
	url := fmt.Sprintf("%s/sifas-%s-cdn-assets.manifest", archiveDownloadBase(archiveItem), region)
	res, err := cdnGet(url) // retries transient failures; returns 404 without retrying
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	if res.StatusCode == http.StatusNotFound {
		return nil, nil // no manifest for this region yet
	}
	if res.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("manifest status %d for %s", res.StatusCode, url)
	}
	data, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, err
	}
	var parts []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue // blank line / comment
		}
		parts = append(parts, line)
	}
	return parts, nil
}

// DownloadArchive downloads the bulk CDN asset tars from archive.org for the given
// regions ("gl"/"jp") and extracts them into the cache dir — the same thing as the
// Termux menu's "Download ALL game files (from archive.org)". Each region is several
// tar parts listed by its manifest; if a region has no manifest yet it falls back to
// the legacy single tar. It does not touch the game CDN. Existing files are kept, so it
// is incremental/resumable at the file level. Restart the server afterwards so the new
// files get indexed.
func DownloadArchive(regions []string) {
	dir := cacheDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		log.Println("download_archive: cannot create cache dir:", err)
		return
	}
	for _, r := range regions {
		parts, err := regionParts(r)
		if err != nil {
			log.Printf("download_archive: %s manifest error: %v (falling back to legacy tar)\n", r, err)
		}
		if len(parts) == 0 {
			downloadLegacyRegion(r, dir)
			continue
		}
		log.Printf("download_archive: %s -> %d part(s) from %s (into %s)\n", r, len(parts), archiveItem, dir)
		ok := 0
		for i, part := range parts {
			url := archiveDownloadBase(archiveItem) + "/" + part
			log.Printf("download_archive: %s part %d/%d: %s\n", r, i+1, len(parts), part)
			if err := downloadAndExtractTar(url, dir); err != nil {
				log.Printf("download_archive: %s part %s FAILED: %v\n", r, part, err)
			} else {
				ok++
			}
		}
		log.Printf("download_archive: %s done (%d/%d parts)\n", r, ok, len(parts))
	}
	log.Println("download_archive: all done. Restart the server so it indexes the new files.")
}

// downloadLegacyRegion downloads the older single-tar-per-region dump. Used only when
// archiveItem has no manifest for the region yet.
func downloadLegacyRegion(region, dir string) {
	ver, ok := legacyArchiveVersions[region]
	if !ok {
		log.Println("download_archive: unknown region:", region)
		return
	}
	url := fmt.Sprintf("%s/sifas-%s-cdn-assets-%s.tar", archiveDownloadBase(legacyArchiveItem), region, ver)
	log.Printf("download_archive: %s -> %s (legacy single tar, into %s)\n", region, url, dir)
	if err := downloadAndExtractTar(url, dir); err != nil {
		log.Printf("download_archive: %s FAILED: %v\n", region, err)
	} else {
		log.Printf("download_archive: %s done\n", region)
	}
}

// downloadAndExtractTar streams a tar from url and extracts it into destDir,
// dropping the leading path component (the "sifas-..-<hash>/" wrapper, like tar
// --strip-components=1) and skipping files that already exist (--skip-old-files).
func downloadAndExtractTar(url, destDir string) error {
	resp, err := http.Get(url)
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
			f, err := os.Create(target)
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				f.Close()
				return err
			}
			f.Close()
			extracted++
			if extracted%500 == 0 {
				log.Printf("download_archive: %d extracted, %d skipped, %s\n",
					extracted, skipped, counted.human())
			}
		}
	}
	log.Printf("download_archive: extracted %d, skipped %d (%s)\n", extracted, skipped, counted.human())
	return nil
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
