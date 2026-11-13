package asset

import (
	"elichika/log"
	"elichika/utils"

	"context"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/gin-gonic/gin"
)

type rangeRequestReader struct {
	context context.Context
	reader  io.Reader
	readErr error
}

func (r *rangeRequestReader) Read(buffer []byte) (int, error) {
	if err := r.context.Err(); err != nil {
		return 0, err
	}
	count, err := r.reader.Read(buffer)
	r.readErr = err
	return count, err
}

func sendRange(ctx *gin.Context, fileName string, start, size int) {
	f, err := os.Open(fileName)
	utils.CheckErr(err)
	defer f.Close()
	info, err := f.Stat()
	utils.CheckErr(err)
	if !info.Mode().IsRegular() {
		log.Panic("requested range source is not a regular file")
	}
	// Validate before sending headers or any neighboring pack bytes. Subtract
	// instead of adding start+size so even an overflowing API input is rejected.
	if start < 0 || size < 0 || int64(start) > info.Size() || int64(size) > info.Size()-int64(start) {
		log.Panic("wrong requested range")
	}
	ctx.Header("Content-Length", fmt.Sprint(size))
	ctx.Header("Content-Type", "application/octet-stream")
	reader := &rangeRequestReader{context: ctx.Request.Context(), reader: io.NewSectionReader(f, int64(start), int64(size))}
	io.CopyN(ctx.Writer, reader, int64(size))
	if errors.Is(reader.readErr, io.EOF) || errors.Is(reader.readErr, io.ErrUnexpectedEOF) {
		// A file truncated after Stat is still an incomplete response. Network
		// write failures and canceled requests simply stop and release the file.
		log.Panic("wrong requested range")
	}
	utils.CheckErr(reader.readErr)
}
