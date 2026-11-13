package asset

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/gin-gonic/gin"
)

type rangeSink struct {
	header     http.Header
	bytes      int
	writes     int
	err        error
	afterWrite func()
}

func (w *rangeSink) Header() http.Header { return w.header }
func (w *rangeSink) WriteHeader(int)     {}
func (w *rangeSink) Write(p []byte) (int, error) {
	w.writes++
	if w.err != nil {
		return 0, w.err
	}
	w.bytes += len(p)
	if w.afterWrite != nil {
		w.afterWrite()
	}
	return len(p), nil
}

func openRangeDescriptors(t *testing.T, path string) int {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("explicit file descriptor ownership is inspected through Linux procfs")
	}
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, entry := range entries {
		if target, _ := os.Readlink(filepath.Join("/proc/self/fd", entry.Name())); target == path {
			count++
		}
	}
	return count
}

func TestSendRangeClosesEverySuccessfulAndDisconnectedRequest(t *testing.T) {
	path := filepath.Join(t.TempDir(), "metapack")
	if err := os.WriteFile(path, bytes.Repeat([]byte("not-another-pack"), 1000), 0600); err != nil {
		t.Fatal(err)
	}
	// File finalizers can conceal a missing Close during normal GC. Every request
	// must release its own descriptor without depending on memory pressure.
	previousGC := debug.SetGCPercent(-1)
	defer debug.SetGCPercent(previousGC)
	before := openRangeDescriptors(t, path)
	for index := 0; index < 400; index++ {
		writer := &rangeSink{header: make(http.Header)}
		if index%2 != 0 {
			writer.err = errors.New("client disconnected")
		}
		ctx, _ := gin.CreateTestContext(writer)
		ctx.Request = httptest.NewRequest("GET", "/pack", nil)
		sendRange(ctx, path, 7, 1031)
	}
	if after := openRangeDescriptors(t, path); after != before {
		t.Fatalf("400 requests retained %d pack descriptors (before=%d after=%d)", after-before, before, after)
	}
}

func TestSendRangeActualHTTPExactSliceAndShortSource(t *testing.T) {
	data := make([]byte, 80*1024+17)
	for index := range data {
		data[index] = byte((index*37 + index/251) % 256)
	}
	path := filepath.Join(t.TempDir(), "neighboring-packs")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	engine := gin.New()
	engine.Use(gin.CustomRecoveryWithWriter(io.Discard, func(ctx *gin.Context, _ any) { ctx.AbortWithStatus(500) }))
	engine.GET("/pack", func(ctx *gin.Context) {
		start, _ := strconv.Atoi(ctx.Query("start"))
		size, _ := strconv.Atoi(ctx.Query("size"))
		sendRange(ctx, path, start, size)
	})
	engine.GET("/directory", func(ctx *gin.Context) { sendRange(ctx, filepath.Dir(path), 0, 1) })
	engine.GET("/missing", func(ctx *gin.Context) { sendRange(ctx, path+".missing", 0, 1) })
	server := httptest.NewServer(engine)
	defer server.Close()
	for _, row := range []struct{ start, size int }{{0, 0}, {len(data), 0}, {0, len(data)}, {4099, 33379}, {len(data) - 1, 1}} {
		response, err := server.Client().Get(server.URL + "/pack?start=" + strconv.Itoa(row.start) + "&size=" + strconv.Itoa(row.size))
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 200 || response.ContentLength != int64(row.size) ||
			sha256.Sum256(body) != sha256.Sum256(data[row.start:row.start+row.size]) {
			t.Fatalf("wrong HTTP slice start=%d size=%d: status=%d bytes=%d err=%v", row.start, row.size, response.StatusCode, len(body), err)
		}
	}
	for _, row := range []struct{ start, size int }{{-1, 8}, {0, -1}, {len(data) + 1, 0}, {len(data) - 3, 4}, {0, len(data) + 1}, {int(^uint(0) >> 1), 1}} {
		response, err := server.Client().Get(server.URL + "/pack?start=" + strconv.Itoa(row.start) + "&size=" + strconv.Itoa(row.size))
		if err != nil {
			t.Fatalf("invalid slice broke the HTTP connection instead of rejecting before body: %v", err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 500 || len(body) != 0 {
			t.Fatalf("invalid/short slice leaked neighboring bytes: start=%d size=%d status=%d bytes=%d err=%v", row.start, row.size, response.StatusCode, len(body), err)
		}
	}
	for _, route := range []string{"/directory", "/missing"} {
		response, err := server.Client().Get(server.URL + route)
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != 500 || len(body) != 0 {
			t.Fatalf("invalid source was accepted: route=%s status=%d bytes=%d err=%v", route, response.StatusCode, len(body), err)
		}
	}
}

func TestSendRangeStopsReadingAfterCancellationOrWriteFailure(t *testing.T) {
	path := filepath.Join(t.TempDir(), "large-metapack")
	if err := os.WriteFile(path, bytes.Repeat([]byte{0x57}, 2*1024*1024), 0600); err != nil {
		t.Fatal(err)
	}
	for _, cancelled := range []bool{false, true} {
		for _, writeErr := range []error{errors.New("connection closed"), io.EOF} {
			writer := &rangeSink{header: make(http.Header), err: writeErr}
			ctx, _ := gin.CreateTestContext(writer)
			requestContext, cancel := context.WithCancel(context.Background())
			defer cancel()
			if cancelled {
				cancel()
			}
			ctx.Request = httptest.NewRequest("GET", "/pack", nil).WithContext(requestContext)
			sendRange(ctx, path, 11, 1024*1024)
			if writer.writes > 1 || cancelled && writer.writes != 0 {
				t.Fatalf("continued reading/writing after cancellation=%v: %d writes", cancelled, writer.writes)
			}
		}
	}
	requestContext, cancel := context.WithCancel(context.Background())
	defer cancel()
	writer := &rangeSink{header: make(http.Header), afterWrite: cancel}
	ctx, _ := gin.CreateTestContext(writer)
	ctx.Request = httptest.NewRequest("GET", "/pack", nil).WithContext(requestContext)
	sendRange(ctx, path, 11, 1024*1024)
	if writer.writes != 1 || writer.bytes > 64*1024 {
		t.Fatalf("continued streaming cached file after cancellation: writes=%d bytes=%d", writer.writes, writer.bytes)
	}
}

func TestSendRangeConcurrentTruncationStillClosesFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "changing-metapack")
	if err := os.WriteFile(path, bytes.Repeat([]byte{0x13}, 1024*1024), 0600); err != nil {
		t.Fatal(err)
	}
	writer := &rangeSink{header: make(http.Header), afterWrite: func() {
		if err := os.Truncate(path, 0); err != nil {
			t.Fatal(err)
		}
	}}
	ctx, _ := gin.CreateTestContext(writer)
	ctx.Request = httptest.NewRequest("GET", "/pack", nil)
	func() {
		defer func() {
			if recover() == nil {
				t.Error("concurrent truncation was accepted as a complete range")
			}
		}()
		sendRange(ctx, path, 0, 1024*1024)
	}()
	if writer.bytes == 0 || writer.bytes >= 1024*1024 || openRangeDescriptors(t, path) != 0 {
		t.Fatalf("truncated response did not release partial read: bytes=%d", writer.bytes)
	}
}

func BenchmarkSendRangeHTTP64MiBEightConcurrent(b *testing.B) {
	path := filepath.Join(b.TempDir(), "64MiB-metapack")
	file, err := os.Create(path)
	if err != nil {
		b.Fatal(err)
	}
	block := bytes.Repeat([]byte("synthetic-metapack-0123456789"), 4096)
	const size = 64 * 1024 * 1024
	for written := 0; written < size; {
		count := len(block)
		if count > size-written {
			count = size - written
		}
		n, err := file.Write(block[:count])
		if err != nil {
			b.Fatal(err)
		}
		written += n
	}
	file.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		ctx, _ := gin.CreateTestContext(w)
		ctx.Request = request
		sendRange(ctx, path, 0, size)
	}))
	defer server.Close()
	client := server.Client()
	client.Transport = &http.Transport{MaxIdleConnsPerHost: 8}
	defer client.CloseIdleConnections()
	var total atomic.Int64
	b.SetBytes(8 * size)
	b.ResetTimer()
	for iteration := 0; iteration < b.N; iteration++ {
		var workers sync.WaitGroup
		for index := 0; index < 8; index++ {
			workers.Add(1)
			go func() {
				defer workers.Done()
				response, err := client.Get(server.URL)
				if err != nil {
					b.Error(err)
					return
				}
				count, err := io.Copy(io.Discard, response.Body)
				response.Body.Close()
				if err != nil || count != size {
					b.Errorf("incomplete pack: bytes=%d err=%v", count, err)
				}
				total.Add(count)
			}()
		}
		workers.Wait()
	}
	b.StopTimer()
	if total.Load() != int64(b.N)*8*size {
		b.Fatal("workload byte count changed")
	}
}
