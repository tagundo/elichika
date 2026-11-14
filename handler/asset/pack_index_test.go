package asset

import (
	"elichika/config"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func isolatedPackLookup(t *testing.T) *string {
	t.Helper()
	oldConfig, oldStatic, oldClient := config.Conf, config.StaticDataPath, httpClient
	packIndexMu.Lock()
	oldIndex, oldRoot, oldDirectories := packIndex, packIndexRoot, packIndexDirectories
	packIndex, packIndexRoot, packIndexDirectories, packIndexOnce = nil, "", nil, sync.Once{}
	packIndexMu.Unlock()
	root := t.TempDir()
	cdn, cache := "https://offline-source.invalid/static", true
	config.Conf = &config.RuntimeConfig{CdnCacheDir: &root, CdnCache: &cache, CdnServer: &cdn}
	config.StaticDataPath = t.TempDir() + "/"
	t.Cleanup(func() {
		config.Conf, config.StaticDataPath, httpClient = oldConfig, oldStatic, oldClient
		packIndexMu.Lock()
		packIndex, packIndexRoot, packIndexDirectories, packIndexOnce = oldIndex, oldRoot, oldDirectories, sync.Once{}
		packIndexMu.Unlock()
	})
	return &root
}

func writePack(t *testing.T, path, data string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
}

func dirtyPackDirectory(t *testing.T, path string) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	stamp := info.ModTime().Add(2 * time.Second)
	if err := os.Chtimes(path, stamp, stamp); err != nil {
		t.Fatal(err)
	}
}

type offlinePackTransport struct{ calls int }

func (transport *offlinePackTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	transport.calls++
	return nil, fmt.Errorf("test forbids any upstream connection")
}

func TestLinkedIOSPacksServeOfflineAndMissingNameIsNotSubstituted(t *testing.T) {
	root := isolatedPackLookup(t)
	outside := t.TempDir()
	payloads := map[string]string{"ftvaa1": "ios costume animation", "4q930h": "ios dance", "m94iq4": "ios stage"}
	for name, data := range payloads {
		writePack(t, filepath.Join(outside, name), data)
	}
	// A common audio pack must not cause the entire local library to be treated
	// as a complete iOS library, nor stand in for a missing iOS bundle.
	writePack(t, filepath.Join(*root, "dni8go"), "common music")
	if err := os.Symlink(outside, filepath.Join(*root, "iOS-linked-library")); err != nil {
		t.Fatal(err)
	}
	transport := &offlinePackTransport{}
	httpClient = &http.Client{Transport: transport}
	for name, want := range payloads {
		response := httptest.NewRecorder()
		ctx, _ := gin.CreateTestContext(response)
		ctx.Request = httptest.NewRequest("GET", "http://127.0.0.1:8080/static/"+name, nil)
		ctx.Params = gin.Params{{Key: "fileName", Value: "/" + name}}
		staticWhole(ctx)
		if response.Code != http.StatusOK || response.Body.String() != want {
			t.Fatalf("linked exact local pack %s: status=%d body=%q", name, response.Code, response.Body.String())
		}
	}
	if _, found := localPath("r48wc8"); found {
		t.Fatal("an absent iOS pack was substituted with another asset")
	}
	if transport.calls != 0 {
		t.Fatalf("offline local serving contacted upstream %d times", transport.calls)
	}
}

func TestNestedPackAddedAfterFirstIndexIsVisibleWithoutRestart(t *testing.T) {
	root := isolatedPackLookup(t)
	bucket := filepath.Join(*root, "pac0")
	writePack(t, filepath.Join(bucket, "dni8go"), "common")
	if _, found := indexLookup("dni8go"); !found {
		t.Fatal("initial nested pack not indexed")
	}
	writePack(t, filepath.Join(bucket, "ftvaa1"), "new ios pack")
	dirtyPackDirectory(t, bucket)
	path, found := localPath("ftvaa1")
	if !found || path != filepath.Join(bucket, "ftvaa1") {
		t.Fatalf("new nested pack invisible: %q %v", path, found)
	}
}

func TestPackRootChangeCannotServePreviousVolumesFiles(t *testing.T) {
	root := isolatedPackLookup(t)
	previous := *root
	writePack(t, filepath.Join(previous, "pac0", "ftvaa1"), "old volume")
	if _, found := indexLookup("ftvaa1"); !found {
		t.Fatal("old volume not primed")
	}
	*root = t.TempDir()
	writePack(t, filepath.Join(*root, "pac0", "4q930h"), "new volume")
	if path, found := localPath("ftvaa1"); found {
		t.Fatalf("old volume leaked into new library: %q", path)
	}
	if path, found := localPath("4q930h"); !found || !strings.HasPrefix(path, *root+string(os.PathSeparator)) {
		t.Fatalf("new volume was not indexed: %q %v", path, found)
	}
}

func TestPackDirectoryLinkCyclesAreFinite(t *testing.T) {
	root := t.TempDir()
	writePack(t, filepath.Join(root, "pac0", "ftvaa1"), "ios")
	if err := os.Symlink(root, filepath.Join(root, "pac0", "back")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, "pac0"), filepath.Join(root, "alias")); err != nil {
		t.Fatal(err)
	}
	files, directories, problems := scanPackFiles(root)
	if len(files) != 1 || files["ftvaa1"] == "" || len(directories) != 2 || len(problems) != 0 {
		t.Fatalf("cycle/alias scan: files=%v directories=%d problems=%v", files, len(directories), problems)
	}
}

func TestPackDirectoryAndBrokenLinkAreNotFiles(t *testing.T) {
	root := isolatedPackLookup(t)
	if err := os.Mkdir(filepath.Join(*root, "ftvaa1"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(*root, "missing"), filepath.Join(*root, "4q930h")); err != nil {
		t.Fatal(err)
	}
	files, _, problems := scanPackFiles(*root)
	if len(files) != 0 {
		t.Fatalf("directory or dangling link was indexed as a game pack: %v", files)
	}
	if len(problems) != 1 || problems[0].path != filepath.Join(*root, "4q930h") {
		t.Fatalf("missing-link diagnosis lost: %v", problems)
	}
	if _, found := localPath("ftvaa1"); found {
		t.Fatal("directory accepted as a downloadable pack")
	}
}

func TestPackDirectoryChangesTrackModesAndSymlinkTargets(t *testing.T) {
	root := t.TempDir()
	target := t.TempDir()
	writePack(t, filepath.Join(target, "ftvaa1"), "ios")
	link := filepath.Join(root, "linked")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	_, directories, _ := scanPackFiles(root)
	if packDirectoriesChanged(directories) {
		t.Fatal("unchanged directory snapshot reported dirty")
	}
	if err := os.Chmod(target, 0750); err != nil {
		t.Fatal(err)
	}
	if !packDirectoriesChanged(directories) {
		t.Fatal("directory permission change ignored")
	}
	_, directories, _ = scanPackFiles(root)
	replacement := t.TempDir()
	if err := os.Remove(link); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(replacement, link); err != nil {
		t.Fatal(err)
	}
	if !packDirectoriesChanged(directories) {
		t.Fatal("linked directory retarget ignored")
	}
}

// The fake transport records attempted upstream access without making a real
// network connection; the declaration checks HTTP transport conformance.
var _ http.RoundTripper = (*offlinePackTransport)(nil)
