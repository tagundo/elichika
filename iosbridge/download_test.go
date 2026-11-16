//go:build elichika_inprocess

package iosbridge

import (
	"context"
	"elichika/assetdata"
	"elichika/handler/asset"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const scopedDownload = `{"schema":1,"command":"download_packs","region":"gl","platform":"ios","language":"en"}`

func maintenanceController(t *testing.T) (*controller, *atomic.Int32) {
	t.Helper()
	closes := new(atomic.Int32)
	c := newController(func(Options, func(string)) (http.Handler, func() error, error) {
		return http.NotFoundHandler(), func() error { closes.Add(1); return nil }, nil
	})
	c.options = Options{DataRoot: t.TempDir()}
	return c, closes
}

func waitJob(t *testing.T, c *controller, state string) State {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		s := c.status()
		if s.Job != nil && s.Job.State == state {
			return s
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("wanted job %s, got %+v", state, c.status())
	return State{}
}

func waitCommandEntered(t *testing.T, entered <-chan struct{}) {
	t.Helper()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("download command never entered its worker")
	}
}

func TestDownloadCommandScopeDefaultsDuplicateAndCancellation(t *testing.T) {
	c, closes := maintenanceController(t)
	entered := make(chan struct{})
	var calls atomic.Int32
	c.download = func(ctx context.Context, workers int, scope assetdata.DownloadSelection, progress func(asset.DownloadProgress)) error {
		calls.Add(1)
		if workers != 4 || scope.Region != assetdata.RegionGL || scope.Platform != assetdata.PlatformIOS || scope.Language != assetdata.LanguageEN {
			return fmt.Errorf("scope/default mismatch: %d %s", workers, scope)
		}
		progress(asset.DownloadProgress{Stage: "downloading", TotalFiles: 9, CompletedFiles: 2, CompletedBytes: 64})
		close(entered)
		<-ctx.Done()
		return ctx.Err()
	}
	started := c.command(scopedDownload)
	t.Cleanup(func() { c.stop() })
	if started.Error != nil || started.Job == nil || started.Job.State != "running" {
		t.Fatalf("%+v", started)
	}
	waitCommandEntered(t, entered)
	if started.Job.Progress.Stage != "preparing" {
		t.Fatal("old status snapshot changed after progress")
	}
	if duplicate := c.command(scopedDownload); duplicate.Error == nil || duplicate.Error.Code != "SERVICE_BUSY" {
		t.Fatalf("duplicate=%+v", duplicate)
	}
	if wrong := c.cancelJob(started.Job.ID + 1); wrong.Error == nil || wrong.Error.Code != "JOB_NOT_FOUND" {
		t.Fatalf("wrong cancellation=%+v", wrong)
	}
	if s := c.status(); s.Job.CancelRequested {
		t.Fatal("wrong job ID cancelled active job")
	}
	cancelled := c.command(fmt.Sprintf(`{"command":"cancel_job","job_id":%d}`, started.Job.ID))
	if cancelled.Error != nil || !cancelled.Job.CancelRequested {
		t.Fatalf("%+v", cancelled)
	}
	ended := waitJob(t, c, "cancelled")
	if ended.State != "stopped" || ended.Job.Progress.Stage != "cancelled" || calls.Load() != 1 || closes.Load() != 1 {
		t.Fatalf("%+v calls=%d closes=%d", ended, calls.Load(), closes.Load())
	}
	if stopped := c.stop(); stopped.Error != nil || stopped.Job.Error == nil {
		t.Fatalf("Stop retained stale top-level failure or lost history: %+v", stopped)
	}
	c.download = func(context.Context, int, assetdata.DownloadSelection, func(asset.DownloadProgress)) error {
		return nil
	}
	if next := c.command(scopedDownload); next.Error != nil || next.Job.ID <= started.Job.ID {
		t.Fatalf("retry=%+v", next)
	}
	waitJob(t, c, "succeeded")
}

func TestStopCancelsDownloadAndGenerationPreventsDeferredRestart(t *testing.T) {
	c, _ := maintenanceController(t)
	entered := make(chan struct{})
	c.download = func(ctx context.Context, _ int, _ assetdata.DownloadSelection, _ func(asset.DownloadProgress)) error {
		close(entered)
		<-ctx.Done()
		return ctx.Err()
	}
	before := c.command(scopedDownload)
	t.Cleanup(func() { c.stop() })
	waitCommandEntered(t, entered)
	stopped := c.stop()
	if stopped.Generation <= before.Generation || !stopped.Job.CancelRequested {
		t.Fatalf("%+v", stopped)
	}
	ended := waitJob(t, c, "cancelled")
	if ended.Generation != stopped.Generation || ended.Ready {
		t.Fatalf("%+v", ended)
	}
}

func TestDownloadRejectsInvalidScopeBeforeAnyPreparation(t *testing.T) {
	c, closes := maintenanceController(t)
	for _, input := range []string{
		`{"command":"download_packs"}`,
		`{"command":"download_packs","region":"jp","platform":"ios","language":"en"}`,
		`{"command":"download_packs","region":"gl","platform":"ios","language":"en","workers":17}`,
	} {
		if s := c.command(input); s.Error == nil || s.Error.Code != "INVALID_COMMAND" {
			t.Errorf("accepted %s: %+v", input, s)
		}
	}
	if closes.Load() != 0 || c.status().Job != nil {
		t.Fatal("invalid input performed maintenance")
	}
	c.mu.Lock()
	c.state.Job = &Job{ID: 8, Command: "reset_accounts", State: "running"}
	c.mu.Unlock()
	if s := c.cancelJob(8); s.Error == nil || s.Error.Code != "NOT_CANCELLABLE" {
		t.Fatalf("%+v", s)
	}
}

func TestProgressSnapshotsRemainStableDuringConcurrentJSONEncoding(t *testing.T) {
	c, _ := maintenanceController(t)
	entered := make(chan struct{})
	release := make(chan struct{})
	c.download = func(ctx context.Context, _ int, _ assetdata.DownloadSelection, progress func(asset.DownloadProgress)) error {
		close(entered)
		for i := int64(0); i < 2000; i++ {
			progress(asset.DownloadProgress{Stage: "downloading", CompletedFiles: i, TotalFiles: 2000})
		}
		select {
		case <-release:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	c.command(scopedDownload)
	t.Cleanup(func() { c.stop() })
	waitCommandEntered(t, entered)
	for i := 0; i < 2000; i++ {
		s := c.status()
		if _, err := json.Marshal(s); err != nil {
			t.Fatal(err)
		}
		if s.Job.Progress != nil && s.Job.Progress.CompletedFiles > 2000 {
			t.Fatal("invalid progress")
		}
	}
	close(release)
	waitJob(t, c, "succeeded")
}

func TestFailedMaintenanceStopClearsOnlyStaleTopLevelError(t *testing.T) {
	c, _ := maintenanceController(t)
	c.download = func(context.Context, int, assetdata.DownloadSelection, func(asset.DownloadProgress)) error {
		return errors.New("specific download error")
	}
	c.command(scopedDownload)
	failed := waitJob(t, c, "failed")
	if !strings.Contains(failed.Error.Message, "specific download error") {
		t.Fatalf("%+v", failed)
	}
	stopped := c.stop()
	if stopped.Error != nil || stopped.Job.Error == nil || !strings.Contains(stopped.Job.Error.Message, "specific download error") {
		t.Fatalf("%+v", stopped)
	}
}

func TestLANOptInKeepsReadinessLocal(t *testing.T) {
	root := t.TempDir()
	for _, address := range []string{"0.0.0.0:8080", "127.0.0.1:0", "[::1]:8080"} {
		input, _ := json.Marshal(Options{DataRoot: root, ListenAddress: address})
		if _, err := parseOptions(string(input)); err != nil {
			t.Fatalf("%s: %v", address, err)
		}
	}
	for _, address := range []string{"0.0.0.0:0", "0.0.0.0:8081", "192.0.2.5:8080", "[::]:8080"} {
		input, _ := json.Marshal(Options{DataRoot: root, ListenAddress: address})
		if _, err := parseOptions(string(input)); err == nil {
			t.Fatalf("accepted %s", address)
		}
	}
	if actual := localEndpoint("0.0.0.0:8080"); actual != "http://127.0.0.1:8080" {
		t.Fatal(actual)
	}
	token := strings.Repeat("a", 32)
	for _, peer := range []string{"127.0.0.1:4000", "192.0.2.8:4000"} {
		r := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080/__elichika/health", nil)
		r.RemoteAddr = peer
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("X-Forwarded-For", "127.0.0.1")
		w := httptest.NewRecorder()
		healthHandler(token)(w, r)
		if peer == "127.0.0.1:4000" && w.Code != http.StatusOK {
			t.Fatalf("local health=%d", w.Code)
		}
		if peer != "127.0.0.1:4000" && w.Code != http.StatusNotFound {
			t.Fatalf("LAN health leaked=%d", w.Code)
		}
	}
	called := 0
	protected := localManagementOnly(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called++; w.WriteHeader(http.StatusNoContent) }))
	for _, path := range []string{"/webui/admin/", "/webui/user/", "/webui"} {
		r := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080"+path, nil)
		r.RemoteAddr = "192.0.2.8:4000"
		r.Header.Set("X-Elichika-Local-Access", token)
		r.Header.Set("X-Forwarded-For", "127.0.0.1")
		w := httptest.NewRecorder()
		protected.ServeHTTP(w, r)
		if w.Code != http.StatusNotFound {
			t.Fatalf("LAN management %s=%d", path, w.Code)
		}
	}
	r := httptest.NewRequest(http.MethodPost, "http://192.0.2.1:8080/login/login", nil)
	r.RemoteAddr = "192.0.2.8:4000"
	w := httptest.NewRecorder()
	protected.ServeHTTP(w, r)
	if called != 1 || w.Code != http.StatusNoContent {
		t.Fatal("LAN game RPC was blocked by local-management guard")
	}
}
