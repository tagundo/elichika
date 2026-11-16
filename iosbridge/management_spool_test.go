//go:build elichika_inprocess

package iosbridge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

func requestSpool(t *testing.T, root string, data []byte) string {
	t.Helper()
	directory, err := managementSpoolDirectory(root, true)
	if err != nil {
		t.Fatal(err)
	}
	name := filepath.Join(directory, "request-"+fmt.Sprintf("%032x", len(data))+".body")
	if err := os.WriteFile(name, data, 0600); err != nil {
		t.Fatal(err)
	}
	return name
}

func responseSpools(t *testing.T, root string) []string {
	t.Helper()
	files, err := filepath.Glob(filepath.Join(root, managementSpoolName, "response-*.body"))
	if err != nil {
		t.Fatal(err)
	}
	return files
}

func TestManagementSpoolPreservesBinaryDBBytesWithoutJSONConversion(t *testing.T) {
	root := t.TempDir()
	binary := append([]byte("SQLite format 3\x00"), []byte{0, 0xff, 0x80, 0, 1, 0xc0, 0xfe, '\r', '\n'}...)
	path := requestSpool(t, root, binary)
	command := Command{Method: http.MethodPost, Path: "/webui/user/restore", BodyFile: path, ContentType: "application/octet-stream", SpoolResponse: true}
	called := false
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		if r.ContentLength != int64(len(binary)) || r.Header.Get("Content-Type") != "application/octet-stream" || r.Header.Get("Origin") != "http://127.0.0.1:8080" || r.Header.Get("X-Elichika-Local-Access") != "test-token" {
			t.Error("trusted request metadata changed")
		}
		got, err := io.ReadAll(r.Body)
		if err != nil || !bytes.Equal(got, binary) {
			t.Errorf("raw DB bytes changed: %x %v", got, err)
		}
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Content-Disposition", `attachment; filename="userdata.db"`)
		_, _ = w.Write(got)
	})
	response, err := serveManagementRequest(command, "test-token", root, handler, defaultManagementLimits)
	if err != nil || !called {
		t.Fatalf("response=%+v error=%v", response, err)
	}
	defer os.Remove(response.BodyFile)
	if response.Body != "" || response.BodyBytes != int64(len(binary)) || response.Status != http.StatusOK || response.BodyFile == "" {
		t.Fatalf("binary entered JSON body or size was lost: %+v", response)
	}
	got, err := os.ReadFile(response.BodyFile)
	if err != nil || !bytes.Equal(got, binary) {
		t.Fatalf("binary response changed: %x %v", got, err)
	}
	info, err := os.Lstat(response.BodyFile)
	if err != nil || info.Mode().Perm() != 0600 || !privateManagementFile(info) {
		t.Fatalf("response not private: %v %v", info, err)
	}
	encoded, _ := json.Marshal(response)
	if bytes.Contains(encoded, []byte("SQLite format")) {
		t.Fatal("raw database contents leaked into JSON result")
	}
	if original, err := os.ReadFile(path); err != nil || !bytes.Equal(original, binary) {
		t.Fatal("Go deleted/changed caller-owned request spool")
	}
}

func TestManagementSpoolKeepsMultipartBodyAndContentTypeExact(t *testing.T) {
	root := t.TempDir()
	multipartTemp := t.TempDir()
	t.Setenv("TMPDIR", multipartTemp)
	payload := []byte{'D', 'B', 0, 0xff, 0x80, 1}
	var raw bytes.Buffer
	writer := multipart.NewWriter(&raw)
	if err := writer.WriteField("user_id", "1111"); err != nil {
		t.Fatal(err)
	}
	part, err := writer.CreateFormFile("database", "userdata.db")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = part.Write(payload); err != nil {
		t.Fatal(err)
	}
	if err = writer.Close(); err != nil {
		t.Fatal(err)
	}
	command := Command{Method: http.MethodPost, Path: "/webui/user/restore", BodyFile: requestSpool(t, root, raw.Bytes()), ContentType: writer.FormDataContentType(), SpoolResponse: true}
	var multipartTemporary []string
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Content-Type") != command.ContentType {
			t.Error("multipart boundary changed")
		}
		// Force uploaded bytes onto disk to verify deferred RemoveAll as well.
		if err := r.ParseMultipartForm(1); err != nil {
			t.Error(err)
			return
		}
		if entries, err := os.ReadDir(multipartTemp); err != nil || len(entries) == 0 {
			t.Error("test did not exercise spilled multipart temporary files")
		}
		file, header, err := r.FormFile("database")
		if err != nil {
			t.Error(err)
			return
		}
		if disk, ok := file.(*os.File); ok {
			multipartTemporary = append(multipartTemporary, disk.Name())
		}
		data, err := io.ReadAll(file)
		file.Close()
		if err != nil || !bytes.Equal(data, payload) || header.Filename != "userdata.db" || r.FormValue("user_id") != "1111" {
			t.Error("multipart fields/file bytes changed")
		}
		_, _ = w.Write([]byte("restored"))
	})
	response, err := serveManagementRequest(command, "token", root, handler, defaultManagementLimits)
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(response.BodyFile)
	for _, path := range multipartTemporary {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("multipart temporary file leaked: %v", err)
		}
	}
	if entries, err := os.ReadDir(multipartTemp); err != nil || len(entries) != 0 {
		t.Fatal("multipart disk spill was not removed after handler completion")
	}
	// A raw-body echo separately proves the entire multipart encoding is
	// forwarded verbatim, in addition to being parseable with original boundary.
	echo := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.Copy(w, r.Body) })
	response, err = serveManagementRequest(command, "token", root, echo, defaultManagementLimits)
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(response.BodyFile)
	got, err := os.ReadFile(response.BodyFile)
	if err != nil || !bytes.Equal(got, raw.Bytes()) {
		t.Fatal("raw multipart stream was rebuilt or altered")
	}
}

func TestManagementSpoolRejectsOutsideSymlinkHardlinkAndOversizeBodies(t *testing.T) {
	root := t.TempDir()
	valid := requestSpool(t, root, []byte("valid"))
	outside := filepath.Join(t.TempDir(), filepath.Base(valid))
	if err := os.WriteFile(outside, []byte("outside"), 0600); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Dir(valid)
	link := filepath.Join(directory, "request-"+strings.Repeat("a", 32)+".body")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	hardlink := filepath.Join(directory, "request-"+strings.Repeat("b", 32)+".body")
	if err := os.Link(outside, hardlink); err != nil {
		t.Fatal(err)
	}
	public := filepath.Join(directory, "request-"+strings.Repeat("c", 32)+".body")
	if err := os.WriteFile(public, []byte("public"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(public, 0644); err != nil {
		t.Fatal(err)
	}
	large := filepath.Join(directory, "request-"+strings.Repeat("d", 32)+".body")
	f, err := os.OpenFile(large, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Truncate(defaultManagementLimits.request + 1); err != nil {
		f.Close()
		t.Fatal(err)
	}
	f.Close()
	called := false
	handler := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true })
	for _, path := range []string{outside, link, hardlink, public, large, filepath.Base(valid)} {
		_, err := serveManagementRequest(Command{Method: "POST", Path: "/webui/user/restore", BodyFile: path, SpoolResponse: true}, "token", root, handler, defaultManagementLimits)
		if err == nil {
			t.Errorf("accepted unsafe body_file %s", path)
		}
	}
	if called {
		t.Fatal("unsafe file reached a handler")
	}
	if len(responseSpools(t, root)) != 0 {
		t.Fatal("rejected requests created response spools")
	}
	if err := validateManagement(Command{Method: "POST", Path: "/webui/user/restore", BodyFile: valid, Body: json.RawMessage(`"ambiguous"`)}); err == nil {
		t.Fatal("both body forms accepted")
	}
	secondRoot := t.TempDir()
	if err := os.Symlink(directory, filepath.Join(secondRoot, managementSpoolName)); err != nil {
		t.Fatal(err)
	}
	if _, err := managementSpoolDirectory(secondRoot, true); err == nil {
		t.Fatal("symlinked spool directory accepted")
	}
}

func TestManagementSpoolRemovesPartialResponseOnOverflowPanicAndWriteError(t *testing.T) {
	for _, kind := range []string{"overflow", "panic", "write-error"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			request := requestSpool(t, root, []byte("input remains"))
			handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte("partial"))
				switch kind {
				case "overflow":
					_, _ = w.Write([]byte(strings.Repeat("x", 128)))
				case "panic":
					panic("specific handler error")
				case "write-error":
					spool := w.(*spooledResponse)
					_ = spool.file.Close()
					_, _ = w.Write([]byte("closed"))
				}
			})
			result, err := serveManagementRequest(Command{Method: "POST", Path: "/webui/user/restore", BodyFile: request, SpoolResponse: true}, "token", root, handler, managementLimits{request: 1024, response: 64})
			if err == nil || result.BodyFile != "" {
				t.Fatalf("failed spool was published: %+v %v", result, err)
			}
			if len(responseSpools(t, root)) != 0 {
				t.Fatal("failed response spool leaked")
			}
			if _, err := os.Stat(request); err != nil {
				t.Fatal("input spool deleted before backend reaped command")
			}
		})
	}
}

func TestManagementSpoolPreservesHTTPErrorResponsesAndLegacyTextLimit(t *testing.T) {
	root := t.TempDir()
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte("specific account validation error"))
	})
	response, err := serveManagementRequest(Command{Method: "GET", Path: "/webui/user/", SpoolResponse: true}, "token", root, handler, defaultManagementLimits)
	if err != nil || response.Status != 400 || response.BodyFile == "" {
		t.Fatalf("HTTP error body lost: %+v %v", response, err)
	}
	defer os.Remove(response.BodyFile)
	data, err := os.ReadFile(response.BodyFile)
	if err != nil || string(data) != "specific account validation error" {
		t.Fatal("HTTP validation body was not forwarded")
	}
	legacy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "old body") })
	response, err = serveManagementRequest(Command{Method: "GET", Path: "/webui/user/"}, "token", "", legacy, defaultManagementLimits)
	if err != nil || response.Body != "old body" || response.BodyFile != "" {
		t.Fatalf("legacy response changed: %+v %v", response, err)
	}
	tooLarge := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write(make([]byte, 8*1024*1024+1)) })
	if _, err := serveManagementRequest(Command{Method: "GET", Path: "/webui/user/"}, "token", "", tooLarge, defaultManagementLimits); err == nil {
		t.Fatal("legacy8MiB cap removed")
	}
	if _, err := serveManagementRequest(Command{Method: "GET", Path: "/login/login", SpoolResponse: true}, "token", root, legacy, defaultManagementLimits); err == nil {
		t.Fatal("game/external route allowlist bypassed")
	}
}

func TestManagementSpoolCleanupAfterLateJobFailureStaysInPrivateJail(t *testing.T) {
	root := t.TempDir()
	response, err := serveManagementRequest(Command{Method: "GET", Path: "/webui/user/", SpoolResponse: true}, "token", root, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "finished export") }), defaultManagementLimits)
	if err != nil {
		t.Fatal(err)
	}
	value, err := discardFailedManagementResult(root, response)
	if err != nil {
		t.Fatal(err)
	}
	if value.(managementResponse).BodyFile != "" || len(responseSpools(t, root)) != 0 {
		t.Fatal("late failed job left a completed response spool")
	}
	outside := filepath.Join(t.TempDir(), "response-must-stay.body")
	if err := os.WriteFile(outside, []byte("unrelated"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := discardFailedManagementResult(root, managementResponse{BodyFile: outside}); err == nil {
		t.Fatal("cleanup accepted an arbitrary external path")
	}
	if data, err := os.ReadFile(outside); err != nil || string(data) != "unrelated" {
		t.Fatal("cleanup touched an external file")
	}
}

func TestManagementSpoolPinnedDirectoryCannotBeRedirectedByParentSymlink(t *testing.T) {
	root := t.TempDir()
	request := requestSpool(t, root, []byte("approved inside body"))
	directory, err := openManagementDirectory(root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer directory.file.Close()
	moved := filepath.Join(root, "pinned-original-spool")
	if err = os.Rename(directory.path, moved); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	if err = os.WriteFile(filepath.Join(outside, filepath.Base(request)), []byte("outside secret must not be read"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(outside, directory.path); err != nil {
		t.Fatal(err)
	}
	if file, _, err := openManagementBodyAt(directory, filepath.Base(request), defaultManagementLimits.request); err == nil {
		file.Close()
		t.Fatal("request read accepted a replaced visible spool directory")
	}
	file, name, err := createManagementResponse(directory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = file.Write([]byte("still inside pinned directory")); err != nil {
		file.Close()
		t.Fatal(err)
	}
	file.Close()
	if _, err = os.Stat(filepath.Join(outside, name)); !os.IsNotExist(err) {
		t.Fatal("openat create followed a swapped parent symlink")
	}
	if data, err := os.ReadFile(filepath.Join(moved, name)); err != nil || string(data) != "still inside pinned directory" {
		t.Fatal("create did not stay in the approved directory inode")
	}
	if err = unix.Unlinkat(int(directory.file.Fd()), name, 0); err != nil {
		t.Fatal(err)
	}
}

func TestManagementSpoolParentSwapBeforePublicationCleansUsingPinnedDirectory(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	moved := filepath.Join(root, "original-spool")
	if err := os.WriteFile(filepath.Join(outside, "keep"), []byte("outside unchanged"), 0600); err != nil {
		t.Fatal(err)
	}
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "first inside bytes")
		if err := os.Rename(filepath.Join(root, managementSpoolName), moved); err != nil {
			t.Error(err)
			return
		}
		if err := os.Symlink(outside, filepath.Join(root, managementSpoolName)); err != nil {
			t.Error(err)
			return
		}
		_, _ = io.WriteString(w, " later inside bytes")
	})
	response, err := serveManagementRequest(Command{Method: "GET", Path: "/webui/user/", SpoolResponse: true}, "token", root, handler, defaultManagementLimits)
	if err == nil || response.BodyFile != "" {
		t.Fatal("spool with replaced visible parent was published")
	}
	inside, err := os.ReadDir(moved)
	if err != nil || len(inside) != 0 {
		t.Fatalf("failed response was not unlinked from its pinned original parent: %v %v", inside, err)
	}
	entries, err := os.ReadDir(outside)
	if err != nil || len(entries) != 1 || entries[0].Name() != "keep" {
		t.Fatal("failed cleanup touched or wrote outside the spool")
	}
}

func TestManagementSpoolLateCleanupRefusesReusedNameInReplacementDirectory(t *testing.T) {
	root := t.TempDir()
	response, err := serveManagementRequest(Command{Method: "GET", Path: "/webui/user/", SpoolResponse: true}, "token", root, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "original owned response") }), defaultManagementLimits)
	if err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(root, managementSpoolName)
	moved := filepath.Join(root, "old-response-spool")
	if err = os.Rename(directory, moved); err != nil {
		t.Fatal(err)
	}
	if err = os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	replacement := filepath.Join(directory, filepath.Base(response.BodyFile))
	if err = os.WriteFile(replacement, []byte("different file must stay"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = discardFailedManagementResult(root, response); err == nil {
		t.Fatal("late cleanup accepted a replacement directory/file identity")
	}
	if data, err := os.ReadFile(replacement); err != nil || string(data) != "different file must stay" {
		t.Fatal("late cleanup unlinked an unowned replacement")
	}
	if data, err := os.ReadFile(filepath.Join(moved, filepath.Base(response.BodyFile))); err != nil || string(data) != "original owned response" {
		t.Fatal("identity failure touched original data unexpectedly")
	}
}
