package asset

import (
	"bytes"
	"crypto/sha256"
	"elichika/config"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"github.com/gin-gonic/gin"
)

func privateDownloadTemp(t *testing.T, directory string, data []byte) string {
	t.Helper()
	file, err := os.CreateTemp(directory, ".cdncache-*")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.Write(data); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	return file.Name()
}

func checkPromotedDownload(t *testing.T, source, dest string, expected []byte) {
	t.Helper()
	if err := promoteDownloadedTemp(source, dest); err != nil {
		t.Fatal(err)
	}
	actual, err := os.ReadFile(dest)
	if err != nil || sha256.Sum256(actual) != sha256.Sum256(expected) {
		t.Fatalf("promoted bytes differ: %v", err)
	}
	info, err := os.Stat(dest)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("private temp permissions changed: %v", err)
	}
	if _, err := os.Stat(source); !os.IsNotExist(err) {
		t.Fatal("completed source temp was retained")
	}
	entries, err := os.ReadDir(filepath.Dir(dest))
	if err != nil || len(entries) != 1 || entries[0].Name() != filepath.Base(dest) {
		t.Fatalf("promotion left temporary files: %v", err)
	}
}

func TestPromoteDownloadedTempSameFilesystemKeepsCompletedPrivateFile(t *testing.T) {
	root := t.TempDir()
	data := bytes.Repeat([]byte("synthetic complete pack\x00"), 4096)
	source := privateDownloadTemp(t, root, data)
	before, err := os.Stat(source)
	if err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(root, "nested-cache", "pack")
	if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dest, []byte("old complete destination"), 0600); err != nil {
		t.Fatal(err)
	}
	checkPromotedDownload(t, source, dest, data)
	after, err := os.Stat(dest)
	if err != nil || !os.SameFile(before, after) {
		t.Fatal("same-filesystem promotion copied the pack instead of renaming its completed temp")
	}
}

func TestPromoteDownloadedTempCrossFilesystemUsesAtomicCopyFallback(t *testing.T) {
	root := t.TempDir()
	other, err := os.MkdirTemp("/dev/shm", "elichika-promotion-test-")
	if err != nil {
		t.Skip("no second writable filesystem for cross-volume contract")
	}
	defer os.RemoveAll(other)
	probe := privateDownloadTemp(t, root, []byte("filesystem probe"))
	err = os.Rename(probe, filepath.Join(other, "probe"))
	if !errors.Is(err, syscall.EXDEV) {
		t.Skip("temporary directory and shared memory are not separate rename domains")
	}
	os.Remove(probe)
	data := bytes.Repeat([]byte("cross-volume complete pack\x00"), 4096)
	source := privateDownloadTemp(t, root, data)
	dest := filepath.Join(other, "cache", "pack")
	if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dest, []byte("old complete destination"), 0600); err != nil {
		t.Fatal(err)
	}
	checkPromotedDownload(t, source, dest, data)
}

func TestPromoteDownloadedTempFailurePreservesSourceAndDestination(t *testing.T) {
	root := t.TempDir()
	source := privateDownloadTemp(t, root, []byte("complete source"))
	blocked := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(blocked, []byte("existing file"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := promoteDownloadedTemp(source, filepath.Join(blocked, "pack")); err == nil {
		t.Fatal("obstructed destination was accepted")
	}
	if raw, err := os.ReadFile(source); err != nil || string(raw) != "complete source" {
		t.Fatal("destination preparation failure discarded source")
	}
	dest := filepath.Join(root, "old-pack")
	if err := os.WriteFile(dest, []byte("keep old destination"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := promoteDownloadedTemp(filepath.Join(root, "missing"), dest); err == nil {
		t.Fatal("missing source was accepted")
	}
	if raw, err := os.ReadFile(dest); err != nil || string(raw) != "keep old destination" {
		t.Fatal("source failure discarded complete destination")
	}
	badSource := filepath.Join(root, "unreadable-as-file")
	if err := os.Mkdir(badSource, 0700); err != nil {
		t.Fatal(err)
	}
	if err := promoteDownloadedTemp(badSource, dest); err == nil {
		t.Fatal("copy-stage directory read error was accepted")
	}
	if info, err := os.Stat(badSource); err != nil || !info.IsDir() {
		t.Fatal("failed copy stage discarded source")
	}
	if raw, err := os.ReadFile(dest); err != nil || string(raw) != "keep old destination" {
		t.Fatal("failed copy stage replaced complete destination")
	}
	// A failed final replacement must clean its own copy temp and retain the
	// complete source. This also exercises the rename-failure fallback path.
	directory := filepath.Join(root, "nonempty-destination")
	if err := os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "keep"), []byte("old"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := promoteDownloadedTemp(source, directory); err == nil {
		t.Fatal("nonempty directory was replaced")
	}
	if raw, err := os.ReadFile(source); err != nil || string(raw) != "complete source" {
		t.Fatal("copy replacement failure discarded source")
	}
	if matches, _ := filepath.Glob(filepath.Join(root, ".tmp-*")); len(matches) != 0 {
		t.Fatal("failed copy left an incomplete destination temp")
	}
}

func TestStreamWholePromotesOnlyCompleteBytesAndKeepsCacheOnDisconnect(t *testing.T) {
	previousConfig, previousRoot, previousClient := config.Conf, config.RootPath, httpClient
	t.Cleanup(func() { config.Conf, config.RootPath, httpClient = previousConfig, previousRoot, previousClient })
	root, cache := t.TempDir(), t.TempDir()
	config.RootPath = root + "/"
	data := bytes.Repeat([]byte("neighbor-free synthetic pack\x00"), 4096)
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/empty":
			return
		case "/truncated":
			w.Header().Set("Content-Length", "999999")
		}
		w.Write(data)
	}))
	defer upstream.Close()
	httpClient = upstream.Client()
	cdn, enabled, listen := upstream.URL, true, "127.0.0.1:1"
	config.Conf = &config.RuntimeConfig{CdnServer: &cdn, CdnCache: &enabled, CdnCacheDir: &cache, ServerAddress: &listen}
	for _, name := range []string{"complete", "disconnected", "empty", "truncated"} {
		dest := filepath.Join(cache, name)
		if err := os.WriteFile(dest, []byte("keep existing complete pack"), 0600); err != nil {
			t.Fatal(err)
		}
		writer := &rangeSink{header: make(http.Header)}
		if name == "disconnected" {
			writer.err = errors.New("client disconnected")
		}
		ctx, _ := gin.CreateTestContext(writer)
		ctx.Request = httptest.NewRequest("GET", "http://127.0.0.1:2/static/"+name, nil)
		streamWholeFromCdn(ctx, name, dest)
		actual, err := os.ReadFile(dest)
		if err != nil {
			t.Fatal(err)
		}
		if name == "empty" || name == "truncated" {
			if string(actual) != "keep existing complete pack" {
				t.Fatal("incomplete upstream replaced a complete cache file")
			}
		} else if sha256.Sum256(actual) != sha256.Sum256(data) {
			t.Fatal("complete upstream bytes did not reach cache")
		}
		if info, err := os.Stat(dest); err != nil || info.Mode().Perm() != 0600 {
			t.Fatal("streamed cache file lost private mode")
		}
		if name == "disconnected" && writer.writes != 1 {
			t.Fatal("client disconnect caused repeated client writes")
		}
	}
	if matches, _ := filepath.Glob(filepath.Join(root, ".cdncache-*")); len(matches) != 0 {
		t.Fatal("stream left incomplete or promoted internal download temps")
	}
	engine := gin.New()
	engine.GET("/static/*fileName", staticWhole)
	request := httptest.NewRequest("GET", "/static/complete", nil)
	request.Header.Set("Range", "bytes=17-1055")
	recorder := httptest.NewRecorder()
	engine.ServeHTTP(recorder, request)
	response := recorder.Result()
	body, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil || response.StatusCode != http.StatusPartialContent || !bytes.Equal(body, data[17:1056]) {
		t.Fatal("promoted pack no longer serves the exact requested partial range")
	}
}
