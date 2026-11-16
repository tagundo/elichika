//go:build elichika_inprocess

package iosbridge

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
)

func TestLogsReadIncrementallyWithoutGrowingReplies(t *testing.T) {
	r := newLogRing()
	_, _ = r.Write([]byte("first\nsecond\npartial"))
	first := r.read(0, 1)
	if len(first.Logs) != 1 || first.Logs[0].Line != "first" || first.NextCursor != 1 || first.Truncated {
		t.Fatalf("%+v", first)
	}
	second := r.read(first.NextCursor, 100)
	if len(second.Logs) != 1 || second.Logs[0].Line != "second" || second.NextCursor != 2 {
		t.Fatalf("%+v", second)
	}
	_, _ = r.Write([]byte(" end\n"))
	last := r.read(second.NextCursor, 100)
	if len(last.Logs) != 1 || last.Logs[0].Line != "partial end" {
		t.Fatalf("%+v", last)
	}
	if empty := r.read(last.NextCursor, 100); len(empty.Logs) != 0 || empty.NextCursor != last.NextCursor {
		t.Fatalf("%+v", empty)
	}
	if invalid := r.read(0, 201); invalid.Error == nil {
		t.Fatal("unbounded log query accepted")
	}
}

func TestLogRingBoundsHugeLinesAndReportsDiscardedHistory(t *testing.T) {
	r := newLogRing()
	_, _ = r.Write([]byte(strings.Repeat("x", 500*1024) + "\n"))
	if first := r.read(0, 1); len(first.Logs) != 1 || len(first.Logs[0].Line) > maxLogLineBytes || !strings.Contains(first.Logs[0].Line, "truncated") {
		t.Fatalf("huge line was not bounded: %+v", first)
	}
	for i := 0; i < 1500; i++ {
		_, _ = r.Write([]byte(fmt.Sprintf("%04d:%s\n", i, strings.Repeat("a", 1500))))
	}
	if len(r.lines) > maxLogLines || r.bytes > maxLogBytes || len(r.pending) > maxLogLineBytes {
		t.Fatal("ring grew past fixed capacity")
	}
	page := r.read(0, 200)
	if !page.Truncated {
		t.Fatal("evicted history was not reported")
	}
	bytes := 0
	for _, entry := range page.Logs {
		bytes += len(entry.Line)
	}
	if bytes > maxLogReplyBytes {
		t.Fatal("log reply exceeded byte budget")
	}
	reset := r.read(r.cursor+100, 200)
	if !reset.Truncated || len(reset.Logs) == 0 || reset.NextCursor > r.cursor {
		t.Fatalf("future/stale-process cursor did not reset: %+v", reset)
	}
}

func TestLogCaptureRedactsCapabilitiesCredentialsAndPrivateKeys(t *testing.T) {
	r := newLogRing()
	secret := strings.Repeat("c", 32)
	r.setSecrets(secret)
	_, _ = r.Write([]byte("capability=" + secret + "\n" +
		`{"password":"s e c r e t","web_token":"different-token"}` + "\n" +
		"GET /?password=another-secret&token=query-token&safe=yes\n" +
		"Authorization: Bearer bearer-secret\n" +
		"-----BEGIN RSA PRIVATE KEY-----\nsensitive-base64\n-----END RSA PRIVATE KEY-----\nvisible\n"))
	encoded, _ := json.Marshal(r.read(0, 100))
	for _, value := range []string{secret, "s e c r e t", "different-token", "another-secret", "query-token", "bearer-secret", "sensitive-base64"} {
		if strings.Contains(string(encoded), value) {
			t.Fatalf("log leaked credential %q", value)
		}
	}
	if !strings.Contains(string(encoded), "visible") || !strings.Contains(string(encoded), "safe=yes") {
		t.Fatal("redaction lost ordinary diagnostics")
	}
}

func TestLogCapabilityRotationRedactsPendingPreviousGeneration(t *testing.T) {
	r := newLogRing()
	previous := strings.Repeat("a", 32)
	r.setSecrets(previous)
	_, _ = r.Write([]byte("old capability=" + previous[:16]))
	r.setSecrets(strings.Repeat("b", 32))
	_, _ = r.Write([]byte(previous[16:] + "\n"))
	encoded, _ := json.Marshal(r.read(0, 100))
	if strings.Contains(string(encoded), previous) || !strings.Contains(string(encoded), "redacted") {
		t.Fatal("rotated capability leaked from a partial line")
	}
}

func TestLogsCommandContainsNoStatusCapabilitiesAndAcceptsNoMaintenance(t *testing.T) {
	c := newController(nil)
	c.state.ReadyToken = strings.Repeat("a", 32)
	c.state.WebToken = strings.Repeat("b", 32)
	_, _ = c.logs.Write([]byte("only fresh text\n"))
	var reply logReply
	if err := json.Unmarshal([]byte(c.commandJSON(`{"schema":1,"command":"logs","after":0,"limit":10}`)), &reply); err != nil {
		t.Fatal(err)
	}
	if len(reply.Logs) != 1 || reply.Error != nil || c.status().Job != nil {
		t.Fatalf("%+v", reply)
	}
	encoded := c.commandJSON(`{"command":"logs","after":1}`)
	if strings.Contains(encoded, c.state.ReadyToken) || strings.Contains(encoded, c.state.WebToken) || strings.Contains(encoded, "data_root") {
		t.Fatal("incremental log read exposed status/config capabilities")
	}
}

func TestConcurrentLogWritersAndCursorPagesRemainOrdered(t *testing.T) {
	r := newLogRing()
	var wg sync.WaitGroup
	for worker := 0; worker < 4; worker++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			for i := 0; i < 400; i++ {
				_, _ = r.Write([]byte(fmt.Sprintf("worker%d-line%d\n", worker, i)))
			}
		}(worker)
	}
	for i := 0; i < 200; i++ {
		_, _ = json.Marshal(r.read(0, 20))
	}
	wg.Wait()
	after := uint64(0)
	for {
		page := r.read(after, 50)
		if len(page.Logs) == 0 {
			break
		}
		for _, entry := range page.Logs {
			if entry.Cursor <= after {
				t.Fatal("duplicate/out-of-order cursor")
			}
			after = entry.Cursor
		}
		if page.NextCursor != after {
			t.Fatal("cursor skipped a visible page")
		}
	}
	if after != 1600 {
		t.Fatalf("final cursor=%d", after)
	}
}
