//go:build elichika_inprocess

package iosbridge

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"golang.org/x/sys/unix"
)

const managementSpoolName = ".elichika-management-spool"

type managementLimits struct{ request, response int64 }

var defaultManagementLimits = managementLimits{256 * 1024 * 1024, 512 * 1024 * 1024}

// Directory descriptors pin the actual app-owned root and spool. All child
// opens/creates/unlinks use openat/unlinkat with O_NOFOLLOW, so swapping the
// visible directory for a symlink cannot redirect binary I/O outside the jail.
type managementDirectory struct {
	file *os.File
	path string
}

func openManagementDirectory(dataRoot string, create bool) (*managementDirectory, error) {
	if !filepath.IsAbs(dataRoot) {
		return nil, errors.New("management spool requires an absolute configured data_root")
	}
	root, err := filepath.EvalSymlinks(dataRoot)
	if err != nil {
		return nil, errors.New("configured management data_root cannot be resolved")
	}
	rootFD, err := unix.Open(root, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, errors.New("configured management data_root cannot be opened as a directory")
	}
	defer unix.Close(rootFD)
	if create {
		if err := unix.Mkdirat(rootFD, managementSpoolName, 0700); err != nil && !errors.Is(err, unix.EEXIST) {
			return nil, errors.New("private management spool directory could not be created")
		}
	}
	fd, err := unix.Openat(rootFD, managementSpoolName, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, errors.New("management spool must be a private directory, not a symlink")
	}
	directory := &managementDirectory{file: os.NewFile(uintptr(fd), filepath.Join(root, managementSpoolName)), path: filepath.Join(root, managementSpoolName)}
	info, err := directory.file.Stat()
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		directory.file.Close()
		return nil, errors.New("management spool must be a private 0700 directory")
	}
	if metadata, ok := info.Sys().(*syscall.Stat_t); !ok || metadata.Uid != uint32(os.Getuid()) {
		directory.file.Close()
		return nil, errors.New("management spool is not owned by this app")
	}
	return directory, nil
}

func (d *managementDirectory) visible() bool {
	visible, err := os.Lstat(d.path)
	if err != nil || visible.Mode()&os.ModeSymlink != 0 || !visible.IsDir() {
		return false
	}
	pinned, err := d.file.Stat()
	return err == nil && os.SameFile(visible, pinned)
}

func managementSpoolDirectory(dataRoot string, create bool) (string, error) {
	directory, err := openManagementDirectory(dataRoot, create)
	if err != nil {
		return "", err
	}
	defer directory.file.Close()
	if !directory.visible() {
		return "", errors.New("management spool directory changed while opening")
	}
	return directory.path, nil
}

func openManagementBody(dataRoot, input string, limit int64) (*os.File, int64, error) {
	directory, err := openManagementDirectory(dataRoot, false)
	if err != nil {
		return nil, 0, err
	}
	defer directory.file.Close()
	if !filepath.IsAbs(input) {
		return nil, 0, errors.New("body_file must be an absolute app-owned request spool")
	}
	clean := filepath.Clean(input)
	parent := filepath.Dir(clean)
	if parent != directory.path && parent != filepath.Join(filepath.Clean(dataRoot), managementSpoolName) {
		return nil, 0, errors.New("body_file must be a direct child of the private management spool")
	}
	name := filepath.Base(clean)
	hexName := strings.TrimSuffix(strings.TrimPrefix(name, "request-"), ".body")
	if !strings.HasPrefix(name, "request-") || !strings.HasSuffix(name, ".body") || len(hexName) < 16 || len(hexName) > 128 {
		return nil, 0, errors.New("body_file must have a request-<randomhex>.body name")
	}
	if _, err := hex.DecodeString(hexName); err != nil {
		return nil, 0, errors.New("body_file request name must contain random hexadecimal characters")
	}
	return openManagementBodyAt(directory, name, limit)
}

func openManagementBodyAt(directory *managementDirectory, name string, limit int64) (*os.File, int64, error) {
	fd, err := unix.Openat(int(directory.file.Fd()), name, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, 0, errors.New("management request spool cannot be opened; missing or symlinked files are forbidden")
	}
	file := os.NewFile(uintptr(fd), filepath.Join(directory.path, name))
	info, err := file.Stat()
	if err != nil || !privateManagementFile(info) || info.Size() < 0 || info.Size() > limit {
		file.Close()
		return nil, 0, errors.New("body_file must be an app-owned private regular file no larger than 256 MiB; links are forbidden")
	}
	if !directory.visible() {
		file.Close()
		return nil, 0, errors.New("management request spool directory changed before reading; no bytes were read")
	}
	return file, info.Size(), nil
}

func createManagementResponse(directory *managementDirectory) (*os.File, string, error) {
	for attempt := 0; attempt < 10; attempt++ {
		random := make([]byte, 16)
		if _, err := rand.Read(random); err != nil {
			return nil, "", errors.New("management response spool random name could not be generated")
		}
		name := "response-" + hex.EncodeToString(random) + ".body"
		fd, err := unix.Openat(int(directory.file.Fd()), name, unix.O_WRONLY|unix.O_CREAT|unix.O_EXCL|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0600)
		if errors.Is(err, unix.EEXIST) {
			continue
		}
		if err != nil {
			return nil, "", errors.New("private management response spool could not be created")
		}
		return os.NewFile(uintptr(fd), filepath.Join(directory.path, name)), name, nil
	}
	return nil, "", errors.New("management response spool could not acquire a unique private name")
}

func privateManagementFile(info os.FileInfo) bool {
	if info == nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Mode().Perm()&0400 == 0 {
		return false
	}
	metadata, ok := info.Sys().(*syscall.Stat_t)
	return ok && metadata.Uid == uint32(os.Getuid()) && metadata.Nlink == 1
}

// Not exported through JSON: cleanup must identify the producer's actual
// directory/file, rather than trusting a reused name in a replacement folder.
type managementSpoolIdentity struct{ directory, file os.FileInfo }

// A successful router response can still be followed by a database-close
// failure in runCommand. Do not orphan that response when the failed job will
// never be served by the Python proxy. No other path can be deleted here.
func discardFailedManagementResult(dataRoot string, value any) (any, error) {
	response, ok := value.(managementResponse)
	if !ok || response.BodyFile == "" {
		return value, nil
	}
	directory, err := openManagementDirectory(dataRoot, false)
	if err != nil {
		return value, errors.New("failed management response cleanup could not validate its private spool")
	}
	defer directory.file.Close()
	path := filepath.Clean(response.BodyFile)
	name := filepath.Base(path)
	if filepath.Dir(path) != directory.path || !strings.HasPrefix(name, "response-") || !strings.HasSuffix(name, ".body") {
		return value, errors.New("failed management response cleanup refused a non-spool path")
	}
	currentDirectory, directoryError := directory.file.Stat()
	if response.spoolIdentity == nil || directoryError != nil || !os.SameFile(currentDirectory, response.spoolIdentity.directory) {
		return value, errors.New("failed management response cleanup refused a replaced spool directory")
	}
	fd, err := unix.Openat(int(directory.file.Fd()), name, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if errors.Is(err, unix.ENOENT) {
		response.BodyFile = ""
		response.BodyBytes = 0
		return response, nil
	}
	if err != nil {
		return value, errors.New("failed management response cleanup refused a missing or linked file")
	}
	file := os.NewFile(uintptr(fd), path)
	info, statError := file.Stat()
	file.Close()
	if statError != nil || !privateManagementFile(info) || !os.SameFile(info, response.spoolIdentity.file) {
		return value, errors.New("failed management response cleanup refused a non-private or linked file")
	}
	if err = unix.Unlinkat(int(directory.file.Fd()), name, 0); err != nil {
		return value, errors.New("failed management response spool could not be removed")
	}
	response.BodyFile = ""
	response.BodyBytes = 0
	response.spoolIdentity = nil
	return response, nil
}

type spooledResponse struct {
	header       http.Header
	status       int
	file         *os.File
	bytes, limit int64
	err          error
}

func (w *spooledResponse) Header() http.Header { return w.header }
func (w *spooledResponse) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
	}
}
func (w *spooledResponse) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	if w.err != nil {
		return 0, w.err
	}
	if int64(len(data)) > w.limit-w.bytes {
		w.err = errors.New("management response exceeds the 512 MiB private spool limit")
		return 0, w.err
	}
	n, err := w.file.Write(data)
	w.bytes += int64(n)
	if err == nil && n != len(data) {
		err = io.ErrShortWrite
	}
	if err != nil {
		w.err = err
	}
	return n, err
}

// serveManagementRequest invokes the real router in-process. Spools preserve
// arbitrary DB/multipart bytes and never put a binary response into JSON.
// HTTP 4xx/5xx are completed responses and are forwarded with their body; only
// execution/write/overflow failures remove the response before publication.
func serveManagementRequest(command Command, token, dataRoot string, handler http.Handler, limits managementLimits) (result managementResponse, err error) {
	if err = validateManagement(command); err != nil {
		return
	}
	var reader io.Reader
	var memory bytes.Buffer
	var input *os.File
	var size int64
	contentType := command.ContentType
	if command.BodyFile != "" {
		input, size, err = openManagementBody(dataRoot, command.BodyFile, limits.request)
		if err != nil {
			return
		}
		defer input.Close()
		reader = io.NewSectionReader(input, 0, size)
	} else {
		if len(command.Body) != 0 && string(command.Body) != "null" {
			var text string
			if json.Unmarshal(command.Body, &text) == nil {
				memory.WriteString(text)
			} else {
				var fields map[string]string
				if err = json.Unmarshal(command.Body, &fields); err != nil {
					err = errors.New("management body must be text or an object of string form fields")
					return
				}
				writer := multipart.NewWriter(&memory)
				for name, value := range fields {
					if err = writer.WriteField(name, value); err != nil {
						return
					}
				}
				if err = writer.Close(); err != nil {
					return
				}
				contentType = writer.FormDataContentType()
			}
		}
		size = int64(memory.Len())
		reader = &memory
	}
	request, requestError := http.NewRequest(command.Method, "http://127.0.0.1:8080"+command.Path, reader)
	if requestError != nil {
		err = requestError
		return
	}
	request.ContentLength = size
	request.RemoteAddr = "127.0.0.1:1"
	request.Header.Set("X-Elichika-Local-Access", token)
	if command.Method == http.MethodPost {
		request.Header.Set("Origin", "http://127.0.0.1:8080")
	}
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	defer func() {
		if request.MultipartForm != nil {
			_ = request.MultipartForm.RemoveAll()
		}
	}()
	var spool *spooledResponse
	var outputDirectory *managementDirectory
	var outputName string
	defer func() {
		if failure := recover(); failure != nil {
			err = fmt.Errorf("management handler failed: %v", failure)
		}
		if spool != nil {
			if closeError := spool.file.Close(); err == nil && closeError != nil {
				err = fmt.Errorf("close management response spool: %w", closeError)
			}
			if err != nil {
				_ = unix.Unlinkat(int(outputDirectory.file.Fd()), outputName, 0)
				result = managementResponse{}
			}
		}
		if outputDirectory != nil {
			_ = outputDirectory.file.Close()
		}
	}()
	if command.SpoolResponse {
		var directoryError error
		outputDirectory, directoryError = openManagementDirectory(dataRoot, true)
		if directoryError != nil {
			err = directoryError
			return
		}
		file, name, createError := createManagementResponse(outputDirectory)
		if createError != nil {
			err = createError
			return
		}
		outputName = name

		spool = &spooledResponse{header: make(http.Header), file: file, limit: limits.response}
		if err = file.Chmod(0600); err != nil {
			return
		}
		handler.ServeHTTP(spool, request)
		if spool.err != nil {
			err = spool.err
			return
		}
		if !outputDirectory.visible() {
			err = errors.New("management response spool directory changed before publication")
			return
		}
		if spool.status == 0 {
			spool.status = http.StatusOK
		}
		fileInfo, fileError := file.Stat()
		directoryInfo, directoryStatError := outputDirectory.file.Stat()
		if fileError != nil || directoryStatError != nil {
			err = errors.New("management response spool identity could not be recorded")
			return
		}
		result = managementResponse{Status: spool.status, Headers: spool.header, BodyFile: file.Name(), BodyBytes: spool.bytes, spoolIdentity: &managementSpoolIdentity{directory: directoryInfo, file: fileInfo}}
		return
	}
	response := &boundedResponse{header: make(http.Header)}
	handler.ServeHTTP(response, request)
	if response.overflow {
		err = errors.New("management response exceeds 8 MiB")
		return
	}
	if response.status == 0 {
		response.status = http.StatusOK
	}
	result = managementResponse{Status: response.status, Headers: response.header, Body: response.body.String(), BodyBytes: int64(response.body.Len())}
	return
}
