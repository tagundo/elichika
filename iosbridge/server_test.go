//go:build elichika_inprocess

package iosbridge

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func startOptions(t *testing.T, root string) string {
	t.Helper()
	data, err := json.Marshal(Options{Schema: 1, DataRoot: root, ListenAddress: "127.0.0.1:0"})
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func waitState(t *testing.T, c *controller, state string) State {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		result := c.status()
		if result.State == state {
			return result
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("wanted %s, got %+v", state, c.status())
	return State{}
}

func TestOptionsRejectUnsafeHostAndAmbiguousJSON(t *testing.T) {
	root := t.TempDir()
	for _, input := range []string{
		`{"data_root":"relative"}`,
		`{"data_root":"` + root + `","listen_address":"0.0.0.0:8080"}`,
		`{"data_root":"` + root + `","ready_token":"bad"}`,
		`{"data_root":"` + root + `","region":"jp","language":"en"}`,
		`{"data_root":"` + root + `","unknown":true}`,
		`{"data_root":"` + root + `"} {}`,
	} {
		if _, err := parseOptions(input); err == nil {
			t.Errorf("accepted %s", input)
		}
	}
}

func TestLifecycleDrainsBeforeCleanupAndReloadsWithoutChangingCWD(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "generation.txt")
	if err := os.WriteFile(path, []byte("first"), 0600); err != nil {
		t.Fatal(err)
	}
	originalCWD, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	entered, release := make(chan struct{}), make(chan struct{})
	var closes atomic.Int32
	c := newController(func(options Options, progress func(string)) (http.Handler, func() error, error) {
		data, err := os.ReadFile(filepath.Join(options.DataRoot, "generation.txt"))
		if err != nil {
			return nil, nil, err
		}
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/blocked" {
				close(entered)
				<-release
			}
			_, _ = w.Write(data)
		}), func() error { closes.Add(1); return nil }, nil
	})
	if state := c.start(startOptions(t, root)); state.State != "starting" {
		t.Fatalf("%+v", state)
	}
	ready := waitState(t, c, "ready")
	if ready.Endpoint == nil || !ready.Ready {
		t.Fatalf("%+v", ready)
	}
	response, err := http.Get(ready.URL + "/feature/data")
	if err != nil {
		t.Fatal(err)
	}
	data, _ := io.ReadAll(response.Body)
	response.Body.Close()
	if string(data) != "first" {
		t.Fatalf("data=%s", data)
	}
	requestDone := make(chan error, 1)
	go func() {
		response, err := http.Get(ready.URL + "/blocked")
		if err == nil {
			response.Body.Close()
		}
		requestDone <- err
	}()
	<-entered
	stopping := c.stop()
	if stopping.State != "stopping" || stopping.Generation <= ready.Generation {
		t.Fatalf("%+v", stopping)
	}
	if closes.Load() != 0 {
		t.Fatal("closed databases with active handler")
	}
	if state := c.start(startOptions(t, root)); state.Error == nil || state.Error.Code != "SERVICE_BUSY" {
		t.Fatal("start accepted during drain")
	}
	close(release)
	if err := <-requestDone; err != nil {
		t.Fatal(err)
	}
	waitState(t, c, "stopped")
	if closes.Load() != 1 {
		t.Fatalf("cleanup count=%d", closes.Load())
	}
	if err := os.WriteFile(path, []byte("second"), 0600); err != nil {
		t.Fatal(err)
	}
	c.start(startOptions(t, root))
	ready = waitState(t, c, "ready")
	response, err = http.Get(ready.URL + "/feature/data")
	if err != nil {
		t.Fatal(err)
	}
	data, _ = io.ReadAll(response.Body)
	response.Body.Close()
	if string(data) != "second" {
		t.Fatalf("stale data=%s", data)
	}
	c.stop()
	waitState(t, c, "stopped")
	currentCWD, _ := os.Getwd()
	if currentCWD != originalCWD {
		t.Fatalf("cwd changed from %s to %s", originalCWD, currentCWD)
	}
}

func TestStopDuringInitializationNeverPublishesReady(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	var closes atomic.Int32
	c := newController(func(Options, func(string)) (http.Handler, func() error, error) {
		close(entered)
		<-release
		return http.NotFoundHandler(), func() error { closes.Add(1); return nil }, nil
	})
	c.start(startOptions(t, t.TempDir()))
	<-entered
	c.stop()
	if state := c.status(); state.State != "stopping" || state.Ready {
		t.Fatalf("%+v", state)
	}
	close(release)
	state := waitState(t, c, "stopped")
	if state.Endpoint != nil || closes.Load() != 1 {
		t.Fatalf("%+v; closes=%d", state, closes.Load())
	}
}

func TestInitializationFailureIsReturnedAndCleansUp(t *testing.T) {
	var closes atomic.Int32
	c := newController(func(Options, func(string)) (http.Handler, func() error, error) {
		return nil, func() error { closes.Add(1); return nil }, errors.New("missing required table")
	})
	c.start(startOptions(t, t.TempDir()))
	state := waitState(t, c, "error")
	if state.Ready || state.Error == nil || !strings.Contains(state.Error.Message, "missing required table") || closes.Load() != 1 {
		t.Fatalf("%+v; closes=%d", state, closes.Load())
	}
}

func TestActualBootstrapRejectsIncompletePayloadBeforeDatabaseCreation(t *testing.T) {
	root := t.TempDir()
	c := newController(prepareServer)
	c.start(startOptions(t, root))
	state := waitState(t, c, "error")
	if state.Error == nil || !strings.Contains(state.Error.Message, "serverdata.db") {
		t.Fatalf("%+v", state)
	}
	files, err := os.ReadDir(root)
	if err != nil || len(files) != 0 {
		t.Fatalf("incomplete payload was mutated: %v, %v", files, err)
	}
}

func TestManagementBridgeRejectsGameAndExecutableRoutes(t *testing.T) {
	for _, path := range []string{"http://example.com/webui/admin/", "/login/login", "//example.com/webui/admin/", "/webui/admin/../run_alisa"} {
		if validateManagement(Command{Method: "GET", Path: path}) == nil {
			t.Errorf("accepted %s", path)
		}
	}
	if err := validateManagement(Command{Method: "POST", Path: "/webui/admin/edit_config"}); err != nil {
		t.Fatal(err)
	}
	state := newController(nil).command(`{"command":"spawn","path":"/bin/sh"}`)
	if state.Error == nil || state.Error.Code != "UNSUPPORTED_COMMAND" {
		t.Fatalf("%+v", state)
	}
}
