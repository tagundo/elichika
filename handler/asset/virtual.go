package asset

// if the server doesn't have any other way of handling range, then we have to do it ourselves
// this assume the server has Accept-Range: bytes, which is true for both elichika or the catfolk cdn.

import (
	"elichika/assetdata"
	"elichika/config"
	"elichika/log"
	"elichika/router"

	"fmt"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
)

func staticVirtual(ctx *gin.Context) {
	file := ctx.Param("fileName")
	downloadData := assetdata.GetDownloadData(file)
	if downloadData.IsEntireFile {
		// The virtual endpoint only serves partial packs. A whole-file request here means a
		// stale/unknown pack name; don't panic the request (the client can re-fetch it via the
		// normal whole-file path) - just refuse this one.
		log.Println("static_virtual: unexpected whole-file request:", file)
		ctx.Status(http.StatusBadRequest)
		return
	}

	host := *config.Conf.CdnServer
	if host == "elichika" {
		host = "http://" + ctx.Request.Host + "/static"
	} else if host == "elichika_tls" {
		host = "https://" + ctx.Request.Host + "/static"
	}
	// Reuse the package's timeout-bounded httpClient with retry/backoff (cdnGetRange) instead of a
	// fresh, unbounded http.Client{} - a stalled upstream now fails fast and a transient hiccup is
	// retried, matching the whole-file path. On failure we return a gateway error instead of
	// panicking (which gin.Recovery would turn into a 500).
	start := downloadData.Start
	end := downloadData.Start + downloadData.Size - 1
	response, err := cdnGetRange(fmt.Sprintf("%s/%s", host, downloadData.File), start, end)
	if err != nil {
		log.Printf("static_virtual: upstream fetch failed for %s: %v\n", downloadData.File, err)
		ctx.Status(http.StatusBadGateway)
		return
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusPartialContent {
		log.Printf("static_virtual: upstream returned %d for %s\n", response.StatusCode, downloadData.File)
		ctx.Status(http.StatusBadGateway)
		return
	}

	ctx.Header("Content-Length", fmt.Sprint(downloadData.Size))
	ctx.Header("Content-Type", "application/octet-stream")
	// Stream straight to the client instead of buffering the whole range in memory.
	io.Copy(ctx.Writer, response.Body)
}

func init() {
	router.AddHandler("/static_virtual", "GET", "/:fileName", staticVirtual)
}
