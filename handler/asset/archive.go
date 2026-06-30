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

// archiveVersions mirrors the per-region master versions the Termux menu uses to
// build the archive.org URL (download_all_archive in elichika_utility.sh).
var archiveVersions = map[string]string{
	"gl": "2d61e7b4e89961c7",
	"jp": "b66ec2295e9a00aa",
}

// DownloadArchive downloads the bulk CDN asset tarball(s) from archive.org for the
// given regions ("gl"/"jp") and extracts them into the cache dir — the same thing
// as the Termux menu's "Download ALL game files (from archive.org)". It does not
// touch the game CDN. Existing files are kept, so it is incremental/resumable at
// the file level. Restart the server afterwards so the new files get indexed.
func DownloadArchive(regions []string) {
	dir := cacheDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		log.Println("download_archive: cannot create cache dir:", err)
		return
	}
	for _, r := range regions {
		ver, ok := archiveVersions[r]
		if !ok {
			log.Println("download_archive: unknown region:", r)
			continue
		}
		url := fmt.Sprintf("https://archive.org/download/ll-sifas-cdn-data/sifas-%s-cdn-assets-%s.tar", r, ver)
		log.Printf("download_archive: %s -> %s (into %s)\n", r, url, dir)
		if err := downloadAndExtractTar(url, dir); err != nil {
			log.Printf("download_archive: %s FAILED: %v\n", r, err)
		} else {
			log.Printf("download_archive: %s done\n", r)
		}
	}
	log.Println("download_archive: all done. Restart the server so it indexes the new files.")
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
