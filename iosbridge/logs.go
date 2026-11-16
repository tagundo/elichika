//go:build elichika_inprocess

package iosbridge

import (
	"bytes"
	"errors"
	"io"
	standardlog "log"
	"regexp"
	"strings"
	"sync"
	"unicode/utf8"
)

const maxLogLines = 1024
const maxLogBytes = 256 * 1024
const maxLogLineBytes = 2048
const maxLogReplyBytes = 64 * 1024

type logLine struct {
	Cursor uint64 `json:"cursor"`
	Line   string `json:"line"`
}

type logReply struct {
	Schema     int       `json:"schema"`
	Logs       []logLine `json:"logs"`
	NextCursor uint64    `json:"next_cursor"`
	Truncated  bool      `json:"logs_truncated"`
	Error      *Failure  `json:"error"`
}

type logRing struct {
	mu         sync.Mutex
	lines      []logLine
	bytes      int
	cursor     uint64
	pending    []byte
	clipped    bool
	privateKey bool
	secrets    []string
}

func newLogRing() *logRing { return &logRing{} }

func init() {
	// Keep the platform console destination while providing incremental reads.
	// This build is an embedded host: no pipes, child process, or growing log file.
	standardlog.SetOutput(io.MultiWriter(standardlog.Writer(), service.logs))
}

func (r *logRing) setSecrets(values ...string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, value := range values {
		if value == "" {
			continue
		}
		found := false
		for _, previous := range r.secrets {
			if previous == value {
				found = true
				break
			}
		}
		if !found {
			r.secrets = append(r.secrets, value)
		}
	}
	// Retain a bounded history so a partial line straddling restart still
	// redacts the preceding generation's capability when it is completed.
	if len(r.secrets) > 16 {
		r.secrets = append([]string(nil), r.secrets[len(r.secrets)-16:]...)
	}
}

var logJSONSecret = regexp.MustCompile(`(?i)("(?:password|passwd|secret|ready_token|web_token|local_webui_token|sign_key)"\s*:\s*)("(?:[^"\\]|\\.)*"|[^,}\s]+)`)
var logQuerySecret = regexp.MustCompile(`(?i)((?:[?&]|\b)(?:password|passwd|secret|token|ready_token|web_token|local_webui_token|sign_key)=)[^&\s]*`)
var logAuthorization = regexp.MustCompile(`(?i)(authorization\s*[:=]\s*).*`)

func (r *logRing) appendLine(line string) {
	if strings.Contains(line, "-----BEGIN ") && strings.Contains(line, "PRIVATE KEY-----") {
		r.privateKey = true
		line = "[private key redacted]"
	} else if r.privateKey {
		if strings.Contains(line, "-----END ") && strings.Contains(line, "PRIVATE KEY-----") {
			r.privateKey = false
		}
		return
	}
	for _, secret := range r.secrets {
		if secret != "" {
			line = strings.ReplaceAll(line, secret, "[redacted]")
		}
	}
	line = logJSONSecret.ReplaceAllString(line, `${1}"[redacted]"`)
	line = logQuerySecret.ReplaceAllString(line, `${1}[redacted]`)
	line = logAuthorization.ReplaceAllString(line, `${1}[redacted]`)
	line = strings.ToValidUTF8(line, "\uFFFD")
	if len(line) > maxLogLineBytes {
		line = line[:maxLogLineBytes]
	}
	for !utf8.ValidString(line) {
		line = line[:len(line)-1]
	}
	r.cursor++
	r.lines = append(r.lines, logLine{r.cursor, line})
	r.bytes += len(line)
	for len(r.lines) > maxLogLines || r.bytes > maxLogBytes {
		r.bytes -= len(r.lines[0].Line)
		r.lines[0] = logLine{}
		r.lines = r.lines[1:]
	}
}

func (r *logRing) Write(data []byte) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	size := len(data)
	for len(data) != 0 {
		end := bytes.IndexByte(data, '\n')
		part := data
		if end >= 0 {
			part = data[:end]
		}
		available := maxLogLineBytes - 24 - len(r.pending)
		if available > 0 {
			count := len(part)
			if count > available {
				count = available
			}
			r.pending = append(r.pending, part[:count]...)
		}
		if len(part) > available {
			r.clipped = true
		}
		if end < 0 {
			break
		}
		line := string(r.pending)
		if r.clipped {
			line += " [line truncated]"
		}
		r.appendLine(line)
		r.pending = r.pending[:0]
		r.clipped = false
		data = data[end+1:]
	}
	return size, nil
}

func (r *logRing) read(after uint64, limit int) logReply {
	r.mu.Lock()
	defer r.mu.Unlock()
	reply := logReply{Schema: 1, Logs: []logLine{}, NextCursor: after}
	if limit == 0 {
		limit = 100
	}
	if limit < 1 || limit > 200 {
		reply.Error = &Failure{"INVALID_LOG_QUERY", "limit must be between 1 and 200"}
		return reply
	}
	if after > r.cursor {
		reply.Truncated, after, reply.NextCursor = true, 0, 0
	}
	if len(r.lines) != 0 && r.lines[0].Cursor > 1 && after < r.lines[0].Cursor-1 {
		reply.Truncated = true
	}
	bytes := 0
	for _, entry := range r.lines {
		if entry.Cursor <= after {
			continue
		}
		if len(reply.Logs) == limit || bytes+len(entry.Line) > maxLogReplyBytes {
			break
		}
		reply.Logs = append(reply.Logs, entry)
		reply.NextCursor = entry.Cursor
		bytes += len(entry.Line)
	}
	return reply
}

func (c *controller) commandJSON(input string) string {
	var command Command
	if err := decodeJSON(input, &command); err != nil {
		return encode(failed(c.status(), "INVALID_COMMAND", err))
	}
	if command.Command == "logs" {
		if command.Schema != 0 && command.Schema != 1 {
			reply := logReply{Schema: 1, Logs: []logLine{}, Error: &Failure{"INVALID_LOG_QUERY", errors.New("unsupported schema").Error()}}
			return encode(reply)
		}
		return encode(c.logs.read(command.After, command.Limit))
	}
	return encode(c.command(input))
}
