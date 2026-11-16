//go:build elichika_inprocess

package iosbridge

import (
	"bytes"
	"context"
	"elichika/assetdata"
	"elichika/config"
	"elichika/handler/asset"
	"elichika/locale"
	"elichika/router"
	"elichika/runtimeinit"
	"elichika/subsystem/user_account"
	"elichika/subsystem/user_training_tree"
	"elichika/userdata"
	"elichika/userdata/database"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

type Command struct {
	Schema      int             `json:"schema"`
	Command     string          `json:"command"`
	Options     *Options        `json:"options,omitempty"`
	Enabled     *bool           `json:"enabled,omitempty"`
	Config      json.RawMessage `json:"config,omitempty"`
	Method      string          `json:"method,omitempty"`
	Path        string          `json:"path,omitempty"`
	Body        json.RawMessage `json:"body,omitempty"`
	ContentType string          `json:"content_type,omitempty"`
	Region      string          `json:"region,omitempty"`
	Platform    string          `json:"platform,omitempty"`
	Language    string          `json:"language,omitempty"`
	Workers     int             `json:"workers,omitempty"`
	JobID       uint64          `json:"job_id,omitempty"`
	After       uint64          `json:"after,omitempty"`
	Limit       int             `json:"limit,omitempty"`
}

func CommandJSON(input string) string { return service.commandJSON(input) }

func (c *controller) command(input string) State {
	var command Command
	if err := decodeJSON(input, &command); err != nil {
		return failed(c.status(), "INVALID_COMMAND", err)
	}
	if command.Schema != 0 && command.Schema != 1 {
		return failed(c.status(), "INVALID_COMMAND", errors.New("unsupported schema"))
	}
	switch command.Command {
	case "status":
		return c.status()
	case "stop":
		return c.stop()
	case "cancel_job":
		return c.cancelJob(command.JobID)
	case "start":
		if command.Options == nil {
			return failed(c.status(), "INVALID_COMMAND", errors.New("start requires options"))
		}
		options, _ := json.Marshal(command.Options)
		return c.start(string(options))
	case "management_request", "config_read", "config_save", "reload", "rebuild_assets", "fix_training_trees", "reset_accounts", "cdn_cache", "download_packs":
	default:
		return failed(c.status(), "UNSUPPORTED_COMMAND", fmt.Errorf("unsupported command %q", command.Command))
	}
	if command.Command == "cdn_cache" && command.Enabled == nil {
		return failed(c.status(), "INVALID_COMMAND", errors.New("cdn_cache requires enabled boolean"))
	}
	if command.Command == "management_request" {
		if err := validateManagement(command); err != nil {
			return failed(c.status(), "INVALID_COMMAND", err)
		}
	}
	if command.Command == "download_packs" {
		if command.Region == "" || command.Platform == "" || command.Language == "" {
			return failed(c.status(), "INVALID_COMMAND", errors.New("download_packs requires explicit region, platform and language"))
		}
		if command.Workers == 0 {
			command.Workers = 4
		}
		if command.Workers < 1 || command.Workers > 16 {
			return failed(c.status(), "INVALID_COMMAND", errors.New("workers must be between 1 and 16"))
		}
		if err := downloadSelection(command).Validate(); err != nil {
			return failed(c.status(), "INVALID_COMMAND", err)
		}
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state.State != "stopped" && c.state.State != "error" || c.state.Job != nil && c.state.Job.State == "running" {
		return failed(c.state, "SERVICE_BUSY", errors.New("stop the server and wait for stopped before maintenance"))
	}
	if c.options.DataRoot == "" {
		return failed(c.state, "NOT_INITIALIZED", errors.New("start with prepared data_root before maintenance"))
	}
	c.state.Generation++
	c.epoch++
	c.state.Error, c.state.Ready, c.state.Endpoint, c.state.URL = nil, false, nil, ""
	c.state.Phase, c.state.Detail = "maintenance", command.Command
	c.state.Job = &Job{ID: c.state.Generation, Command: command.Command, State: "running"}
	ctx := context.Background()
	if command.Command == "download_packs" {
		ctx, c.commandCancel = context.WithCancel(ctx)
		c.state.Job.Progress = &asset.DownloadProgress{Stage: "preparing"}
	}
	go c.runCommand(ctx, command, c.state.Job.ID, c.epoch)
	return snapshot(c.state)
}

func downloadSelection(command Command) assetdata.DownloadSelection {
	return assetdata.DownloadSelection{Region: assetdata.Region(command.Region), Platform: assetdata.Platform(command.Platform), Language: assetdata.Language(command.Language)}
}

func (c *controller) cancelJob(id uint64) State {
	c.mu.Lock()
	defer c.mu.Unlock()
	if id == 0 || c.state.Job == nil || c.state.Job.ID != id {
		return failed(snapshot(c.state), "JOB_NOT_FOUND", errors.New("job_id does not match the current job"))
	}
	if c.state.Job.Command != "download_packs" {
		return failed(snapshot(c.state), "NOT_CANCELLABLE", errors.New("only download_packs supports cancellation"))
	}
	if c.state.Job.State == "running" && c.commandCancel != nil {
		c.commandCancel()
		job := *c.state.Job
		job.CancelRequested = true
		c.state.Job = &job
	}
	return snapshot(c.state)
}

func (c *controller) runCommand(ctx context.Context, command Command, id, epoch uint64) {
	c.operation.Lock()
	defer c.operation.Unlock()
	c.mu.Lock()
	current := c.epoch == epoch && c.state.Job != nil && c.state.Job.ID == id && c.state.Job.State == "running"
	c.mu.Unlock()
	if !current {
		return
	}
	var result any
	var err error
	defer func() {
		if failure := recover(); failure != nil {
			err = fmt.Errorf("%s: %v", command.Command, failure)
		}
		runtimeinit.RebuildAssets = false
		err = errors.Join(err, c.closePrepared())
		c.mu.Lock()
		defer c.mu.Unlock()
		if c.epoch != epoch || c.state.Job == nil || c.state.Job.ID != id {
			return
		}
		if c.commandCancel != nil {
			c.commandCancel()
			c.commandCancel = nil
		}
		job := Job{ID: id, Command: command.Command, State: "succeeded", Result: result, Progress: c.state.Job.Progress, CancelRequested: c.state.Job.CancelRequested}
		c.state.State, c.state.Phase, c.state.Detail = "stopped", "stopped", ""
		if err != nil {
			job.State, job.Error = "failed", &Failure{"COMMAND_FAILED", err.Error()}
			if errors.Is(err, context.Canceled) {
				job.State, job.Error = "cancelled", &Failure{"COMMAND_CANCELLED", "Download cancelled; completed files remain cached."}
			}
			c.state.Error = job.Error
		}
		if job.Progress != nil && job.State != "succeeded" {
			progress := *job.Progress
			progress.Stage = job.State
			job.Progress = &progress
		}
		c.state.Job = &job
	}()
	if err = ctx.Err(); err != nil {
		return
	}
	runtimeinit.RebuildAssets = command.Command == "rebuild_assets"
	_, cleanup, prepareError := c.prepare(c.options, c.progress)
	c.cleanup = cleanup
	if prepareError != nil {
		err = prepareError
		return
	}
	if err = ctx.Err(); err != nil {
		return
	}
	switch command.Command {
	case "download_packs":
		err = c.download(ctx, command.Workers, downloadSelection(command), func(progress asset.DownloadProgress) {
			c.mu.Lock()
			defer c.mu.Unlock()
			if c.epoch != epoch || c.state.Job == nil || c.state.Job.ID != id {
				return
			}
			job := *c.state.Job
			job.Progress = &progress
			c.state.Job = &job
		})
	case "management_request":
		result, err = managementRequest(command, c.options.WebToken)
	case "config_read":
		result = config.Conf
	case "config_save":
		if len(command.Config) == 0 {
			err = errors.New("config_save requires config object")
			return
		}
		currentJSON, marshalError := json.Marshal(config.Conf)
		if marshalError != nil {
			err = marshalError
			return
		}
		current := map[string]json.RawMessage{}
		edits := map[string]json.RawMessage{}
		if err = json.Unmarshal(currentJSON, &current); err != nil {
			return
		}
		if err = json.Unmarshal(command.Config, &edits); err != nil {
			return
		}
		if edits == nil {
			err = errors.New("config_save requires config object")
			return
		}
		for key, value := range edits {
			if _, known := current[key]; !known {
				err = fmt.Errorf("unknown config field %q", key)
				return
			}
			if string(value) == "null" {
				err = fmt.Errorf("config field %q cannot be null", key)
				return
			}
			current[key] = value
		}
		mergedJSON, marshalError := json.Marshal(current)
		if marshalError != nil {
			err = marshalError
			return
		}
		var updated config.RuntimeConfig
		err = json.Unmarshal(mergedJSON, &updated)
		if err == nil {
			err = updated.Save(config.DataPath("config.json"))
		}
	case "cdn_cache":
		*config.Conf.CdnCache = *command.Enabled
		err = config.Conf.Save(config.DataPath("config.json"))
	case "fix_training_trees":
		user_training_tree.FixUsersTrainingTrees()
	case "reset_accounts":
		err = resetAccounts()
	case "reload", "rebuild_assets": // initialization above performs the real reload/rebuild
	}
}

func validateManagement(command Command) error {
	if command.Method != http.MethodGet && command.Method != http.MethodPost {
		return errors.New("management method must be GET or POST")
	}
	parsed, err := url.ParseRequestURI(command.Path)
	if err != nil || parsed.IsAbs() || parsed.Host != "" || parsed.Fragment != "" {
		return errors.New("management path must be a local WebUI path")
	}
	if !strings.HasPrefix(parsed.Path, "/webui/admin/") && !strings.HasPrefix(parsed.Path, "/webui/user/") {
		return errors.New("management is limited to existing admin/user WebUI routes")
	}
	if strings.Contains(parsed.Path, "..") || strings.Contains(parsed.Path, "\\") || strings.Contains(parsed.Path, "\x00") {
		return errors.New("invalid management path")
	}
	return nil
}

type managementResponse struct {
	Status  int         `json:"status"`
	Headers http.Header `json:"headers"`
	Body    string      `json:"body"`
}

type boundedResponse struct {
	header   http.Header
	status   int
	body     bytes.Buffer
	overflow bool
}

func (w *boundedResponse) Header() http.Header { return w.header }
func (w *boundedResponse) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
	}
}
func (w *boundedResponse) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	if w.body.Len()+len(data) > 8*1024*1024 {
		w.overflow = true
		return 0, errors.New("management response exceeds 8 MiB")
	}
	return w.body.Write(data)
}

func managementRequest(command Command, token string) (managementResponse, error) {
	var body bytes.Buffer
	contentType := command.ContentType
	if len(command.Body) != 0 && string(command.Body) != "null" {
		var text string
		if json.Unmarshal(command.Body, &text) == nil {
			body.WriteString(text)
		} else {
			var fields map[string]string
			if err := json.Unmarshal(command.Body, &fields); err != nil {
				return managementResponse{}, errors.New("management body must be text or an object of string form fields")
			}
			writer := multipart.NewWriter(&body)
			for name, value := range fields {
				if err := writer.WriteField(name, value); err != nil {
					return managementResponse{}, err
				}
			}
			if err := writer.Close(); err != nil {
				return managementResponse{}, err
			}
			contentType = writer.FormDataContentType()
		}
	}
	request, err := http.NewRequest(command.Method, "http://127.0.0.1:8080"+command.Path, &body)
	if err != nil {
		return managementResponse{}, err
	}
	request.RemoteAddr = "127.0.0.1:1"
	request.Header.Set("X-Elichika-Local-Access", token)
	if command.Method == http.MethodPost {
		request.Header.Set("Origin", "http://127.0.0.1:8080")
	}
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	engine := gin.New()
	engine.Use(gin.RecoveryWithWriter(io.Discard))
	router.ManagementRouterWithCredentials(engine, token)
	response := &boundedResponse{header: make(http.Header)}
	engine.ServeHTTP(response, request)
	if response.overflow {
		return managementResponse{}, errors.New("management response exceeds 8 MiB")
	}
	if response.status == 0 {
		response.status = http.StatusOK
	}
	return managementResponse{response.status, response.header, response.body.String()}, nil
}

func resetAccounts() error {
	ids := []int32{}
	session := userdata.Engine.NewSession()
	defer session.Close()
	if err := session.Begin(); err != nil {
		return err
	}
	rows, err := session.QueryString("SELECT user_id FROM u_authentication")
	if err != nil {
		return err
	}
	for _, row := range rows {
		id, err := strconv.ParseInt(row["user_id"], 10, 32)
		if err != nil {
			return err
		}
		ids = append(ids, int32(id))
	}
	for table := range database.UserDataTableNameToInterface {
		if table == "u_authentication" {
			continue
		}
		if _, err := session.Exec("DELETE FROM \"" + table + "\""); err != nil {
			return err
		}
	}
	if err := session.Commit(); err != nil {
		return err
	}
	session.Close()
	ctx := &gin.Context{}
	ctx.Set("gamedata", locale.Locales["en"].Gamedata)
	ctx.Set("dictionary", locale.Locales["en"].Dictionary)
	for _, id := range ids {
		user_account.CreateNewAccount(ctx, id, "")
	}
	return nil
}
