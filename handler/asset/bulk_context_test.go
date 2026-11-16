package asset

import (
	"context"
	"elichika/assetdata"
	"elichika/config"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestBulkContextUsesAtomicCacheAndResumesWithoutRedownloading(t *testing.T) {
	root := isolatedPackLookup(t)
	var requests atomic.Int32
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path == "/redirect" {
			http.Redirect(w, r, "/redirected", http.StatusFound)
			return
		}
		_, _ = io.WriteString(w, "pack:"+r.URL.Path)
	}))
	defer source.Close()
	*config.Conf.CdnServer = source.URL
	writePack(t, filepath.Join(*root, "cached"), "existing")
	names := map[string]struct{}{"cached": {}, "new": {}, "redirect": {}}
	var events []DownloadProgress
	if err := downloadMissingFilesContext(context.Background(), 4, names, func(p DownloadProgress) { events = append(events, p) }); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 3 {
		t.Fatalf("cache/redirect requests=%d", requests.Load())
	}
	for name, want := range map[string]string{"cached": "existing", "new": "pack:/new", "redirect": "pack:/redirected"} {
		data, err := os.ReadFile(filepath.Join(*root, name))
		if err != nil || string(data) != want {
			t.Fatalf("%s=%q %v", name, data, err)
		}
	}
	last := events[len(events)-1]
	if last.Stage != "finished" || last.TotalFiles != 2 || last.CompletedFiles != 2 || last.CompletedBytes == 0 {
		t.Fatalf("missing final real progress: %+v", events)
	}
	if err := downloadMissingFilesContext(context.Background(), 4, names, nil); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 3 {
		t.Fatal("resumed command redownloaded cached files")
	}
	if temporary, _ := filepath.Glob(filepath.Join(*root, ".tmp-*")); len(temporary) != 0 {
		t.Fatalf("temporary files remain: %v", temporary)
	}
}

func TestBulkContextCancellationClosesActiveResponseAndRemovesPartialFile(t *testing.T) {
	root := isolatedPackLookup(t)
	entered, disconnected := make(chan struct{}), make(chan struct{})
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "partial-pack")
		w.(http.Flusher).Flush()
		close(entered)
		select {
		case <-r.Context().Done():
		case <-time.After(3 * time.Second):
		}
		close(disconnected)
	}))
	defer source.Close()
	*config.Conf.CdnServer = source.URL
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	var final DownloadProgress
	go func() {
		done <- downloadMissingFilesContext(ctx, 4, map[string]struct{}{"blocked": {}}, func(p DownloadProgress) { final = p })
	}()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("HTTP body never started")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("cancel returned %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("cancel did not interrupt active body")
	}
	select {
	case <-disconnected:
	case <-time.After(time.Second):
		t.Fatal("HTTP request context stayed alive")
	}
	if final.Stage != "cancelled" {
		t.Fatalf("final progress=%+v", final)
	}
	if _, err := os.Stat(filepath.Join(*root, "blocked")); !os.IsNotExist(err) {
		t.Fatalf("partial canonical pack exists: %v", err)
	}
	if temporary, _ := filepath.Glob(filepath.Join(*root, ".tmp-*")); len(temporary) != 0 {
		t.Fatalf("partial temps remain: %v", temporary)
	}
}

func TestBulkContextBoundsStalledBodyAndReportsFailure(t *testing.T) {
	root := isolatedPackLookup(t)
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "partial")
		w.(http.Flusher).Flush()
		select {
		case <-r.Context().Done():
		case <-time.After(3 * time.Second):
		}
	}))
	defer source.Close()
	*config.Conf.CdnServer = source.URL
	var final DownloadProgress
	err := downloadMissingFilesWithTimeout(context.Background(), 1, map[string]struct{}{"timeout": {}}, func(p DownloadProgress) { final = p }, 40*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "1 of 1 downloads failed") || final.Stage != "failed" {
		t.Fatalf("error=%v progress=%+v", err, final)
	}
	if _, err := os.Stat(filepath.Join(*root, "timeout")); !os.IsNotExist(err) {
		t.Fatal("timed-out body was cached")
	}
}

func TestBulkRetryBackoffHonorsCancellation(t *testing.T) {
	isolatedPackLookup(t)
	entered := make(chan struct{}, 1)
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case entered <- struct{}{}:
		default:
		}
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer source.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { _, err := cdnGetWithContext(ctx, source.URL, nil); done <- err }()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("retry request never started")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("backoff cancel=%v", err)
		}
	case <-time.After(200 * time.Millisecond):
		t.Fatal("cancel waited through retry backoff")
	}
	if err := DownloadMissingContext(context.Background(), 4, assetdata.DownloadSelection{Region: "invalid"}, nil); err == nil {
		t.Fatal("invalid scope accepted")
	}
}
