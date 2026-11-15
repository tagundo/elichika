//go:build elichika_inprocess

package iosbridge

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"
)

type Failure struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type Job struct {
	ID      uint64   `json:"id"`
	Command string   `json:"command"`
	State   string   `json:"state"`
	Error   *Failure `json:"error"`
	Result  any      `json:"result,omitempty"`
}

type State struct {
	Schema          int      `json:"schema"`
	State           string   `json:"state"`
	Phase           string   `json:"phase"`
	Detail          string   `json:"detail,omitempty"`
	Ready           bool     `json:"ready"`
	Endpoint        *string  `json:"endpoint"`
	URL             string   `json:"url"`
	Error           *Failure `json:"error"`
	Generation      uint64   `json:"generation"`
	DataRoot        string   `json:"data_root,omitempty"`
	ReadyToken      string   `json:"ready_token,omitempty"`
	WebToken        string   `json:"web_token,omitempty"`
	LocalWebUIToken string   `json:"local_webui_token,omitempty"`
	Job             *Job     `json:"job,omitempty"`
}

type prepareFunc func(Options, func(string)) (http.Handler, func() error, error)

type controller struct {
	mu        sync.Mutex
	operation sync.Mutex
	state     State
	options   Options
	server    *http.Server
	cleanup   func() error
	prepare   prepareFunc
}

func newController(prepare prepareFunc) *controller {
	return &controller{state: State{Schema: 1, State: "stopped", Phase: "stopped"}, prepare: prepare}
}

var service = newController(prepareServer)

func encode(value State) string { data, _ := json.Marshal(value); return string(data) }

func StatusJSON() string            { return encode(service.status()) }
func StartJSON(input string) string { return encode(service.start(input)) }
func StopJSON() string              { return encode(service.stop()) }

func (c *controller) status() State {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state
}

func failed(state State, code string, err error) State {
	state.Error = &Failure{code, err.Error()}
	return state
}

func (c *controller) start(input string) State {
	options, err := parseOptions(input)
	if err != nil {
		return failed(c.status(), "INVALID_OPTIONS", err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if (c.state.State == "starting" || c.state.State == "ready") &&
		options.DataRoot == c.options.DataRoot && options.ListenAddress == c.options.ListenAddress &&
		options.PacksRoot == c.options.PacksRoot && options.Language == c.options.Language && options.Region == c.options.Region {
		return c.state
	}
	if c.state.State == "starting" || c.state.State == "ready" || c.state.State == "stopping" || (c.state.Job != nil && c.state.Job.State == "running") {
		return failed(c.state, "SERVICE_BUSY", errors.New("stop the current server/job and wait for stopped before starting"))
	}
	generation := c.state.Generation + 1
	c.options = options
	c.state = State{Schema: 1, State: "starting", Phase: "starting", Generation: generation, DataRoot: options.DataRoot,
		ReadyToken: options.ReadyToken, WebToken: options.WebToken, LocalWebUIToken: options.WebToken}
	go c.launch()
	return c.state
}

func (c *controller) progress(detail string) {
	c.mu.Lock()
	c.state.Detail = detail
	c.mu.Unlock()
}

func (c *controller) launch() {
	c.operation.Lock()
	defer c.operation.Unlock()
	c.mu.Lock()
	options := c.options
	stopping := c.state.State == "stopping"
	c.mu.Unlock()
	if stopping {
		c.finishStopped(nil)
		return
	}
	handler, cleanup, err := c.prepare(options, c.progress)
	c.cleanup = cleanup
	if err != nil {
		c.finishFailed("INITIALIZATION_FAILED", err)
		return
	}
	c.mu.Lock()
	stopping = c.state.State == "stopping"
	c.mu.Unlock()
	if stopping {
		c.finishStopped(c.closePrepared())
		return
	}
	listener, err := net.Listen("tcp", options.ListenAddress)
	if err != nil {
		c.finishFailed("LISTEN_FAILED", err)
		return
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/__elichika/health", func(w http.ResponseWriter, r *http.Request) {
		expected := "Bearer " + options.ReadyToken
		if r.Method != http.MethodGet || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte(expected)) != 1 {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(map[string]any{"ready": true, "schema": 1})
	})
	mux.Handle("/", handler)
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second}
	c.server = server
	endpoint := "http://" + listener.Addr().String()
	serveError := make(chan error, 1)
	go func() { serveError <- server.Serve(listener) }()
	if err := probe(endpoint, options.ReadyToken); err != nil {
		_ = server.Close()
		c.server = nil
		c.finishFailed("READINESS_FAILED", err)
		return
	}
	c.mu.Lock()
	if c.state.State == "stopping" {
		c.mu.Unlock()
		c.finishStopped(c.closePrepared())
		return
	}
	c.state.State, c.state.Phase, c.state.Detail = "ready", "running", "serving real game routes"
	c.state.Ready, c.state.Endpoint, c.state.URL, c.state.Error = true, &endpoint, endpoint, nil
	c.mu.Unlock()
	go func() {
		if err := <-serveError; err != nil && !errors.Is(err, http.ErrServerClosed) {
			c.operation.Lock()
			defer c.operation.Unlock()
			if c.server == server {
				c.finishFailed("HTTP_SERVER_FAILED", err)
			}
		}
	}()
}

func probe(endpoint, token string) error {
	request, err := http.NewRequest(http.MethodGet, endpoint+"/__elichika/health", nil)
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{Proxy: nil}}
	defer client.CloseIdleConnections()
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("owned health endpoint returned %d", response.StatusCode)
	}
	return nil
}

func (c *controller) stop() State {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state.Generation++
	if c.state.Job != nil && c.state.Job.State == "running" {
		return failed(c.state, "JOB_RUNNING", errors.New("wait for the current maintenance job to finish"))
	}
	if c.state.State == "stopped" {
		return c.state
	}
	if c.state.State == "stopping" {
		return c.state
	}
	c.state.State, c.state.Phase, c.state.Ready = "stopping", "stopping", false
	go func() {
		c.operation.Lock()
		defer c.operation.Unlock()
		c.finishStopped(c.closePrepared())
	}()
	return c.state
}

func (c *controller) closePrepared() error {
	if c.server != nil {
		// Shutdown closes admission and waits for every handler to return before
		// any database is closed. The API remains asynchronous during this wait.
		err := c.server.Shutdown(context.Background())
		if err != nil {
			return err
		}
		c.server = nil
	}
	if c.cleanup != nil {
		cleanup := c.cleanup
		c.cleanup = nil
		return cleanup()
	}
	return nil
}

func (c *controller) finishStopped(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state.State, c.state.Phase, c.state.Detail = "stopped", "stopped", ""
	c.state.Ready, c.state.Endpoint, c.state.URL = false, nil, ""
	c.state.Error = nil
	if err != nil {
		c.state = failed(c.state, "CLOSE_FAILED", err)
		c.state.State, c.state.Phase = "error", "error"
	}
}

func (c *controller) finishFailed(code string, err error) {
	closeError := c.closePrepared()
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state.State, c.state.Phase, c.state.Ready = "error", "error", false
	c.state.Endpoint, c.state.URL = nil, ""
	c.state = failed(c.state, code, errors.Join(err, closeError))
}
