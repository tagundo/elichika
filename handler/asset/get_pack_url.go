package asset

import (
	"elichika/assetdata"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/config"
	"elichika/handler/common"
	"elichika/log"
	"elichika/router"
	"elichika/utils"

	"encoding/json"
	"fmt"

	"github.com/gin-gonic/gin"
)

func getPackUrl(ctx *gin.Context) {
	req := request.GetPackUrlRequest{}
	err := json.Unmarshal(*ctx.MustGet("reqBody").(*json.RawMessage), &req)
	utils.CheckErr(err)

	host := *config.Conf.CdnServer

	// elichika's own address, used whenever elichika should serve a pack itself. Computed even off
	// cache mode because, with cache off, we still serve packs that are already on disk (see below).
	actualHost := ctx.Request.Host
	// ctx.Request.Proto is not what we want, it is HTTP/1.0 and similar and doesn't indicate whether the connection is TLS or not
	actualProto := "http"
	if ctx.Request.TLS != nil {
		actualProto = "https"
	}
	// if the connection is forwarded, we need to return the forwarded host instead
	forwardedHost, hostExists := ctx.Request.Header["X-Forwarded-Host"]
	forwardedProto, protoExists := ctx.Request.Header["X-Forwarded-Proto"]
	if hostExists && len(forwardedHost) > 0 {
		actualHost = forwardedHost[0]
	}
	if protoExists && len(forwardedProto) > 0 {
		actualProto = forwardedProto[0]
	}
	selfHost := actualProto + "://" + actualHost + "/static"

	// selfServe reports whether elichika should serve every pack itself: cache mode (it downloads
	// missing ones into sukusta/packs) or the explicit self-host modes.
	selfServe := cacheEnabled() || (host == "elichika") || (host == "elichika_tls")
	if selfServe {
		host = selfHost
	}
	resp := response.GetPackUrlResponse{}
	for _, pack := range req.PackNames.Slice {
		downloadData := assetdata.GetDownloadData(pack)

		// Even with cache OFF, serve any pack that is ALREADY on disk (pre-downloaded from
		// archive.org, or added by an installed mod — neither exists on the public CDN) from
		// elichika instead of sending the game to the upstream CDN. Cache OFF then only means
		// "don't download & store MISSING packs", so offline play and modded data keep working.
		// The underlying whole file for a partial pack is downloadData.File.
		localName := pack
		if !downloadData.IsEntireFile {
			localName = downloadData.File
		}
		servedLocally := selfServe
		packHost := host
		if !selfServe {
			if _, ok := localPath(localName); ok {
				servedLocally = true
				packHost = selfHost
			}
		}

		if downloadData.IsEntireFile { // whole file: served by /static/<pack>
			resp.UrlList.Append(fmt.Sprintf("%s/%s", packHost, pack))
			continue
		}
		partialCapability := *config.Conf.CdnPartialFileCapability
		if cacheEnabled() || servedLocally {
			// elichika holds the whole metapack locally, so it can serve the requested range
			// itself through the mapped endpoint.
			partialCapability = "mapped_file"
		}
		if partialCapability == "static_file" {
			// if the cdn has static partial files then just give a normal request
			// this is simple but require more storage on the cdn server
			resp.UrlList.Append(fmt.Sprintf("%s/%s", packHost, pack))
		} else if partialCapability == "mapped_file" {
			// end point is /static_map/<file>
			// if the cdn has mapping from partial files, (i.e. elichika itself) then just send the file name to this mapped api
			// having a separate endpoint help with some server impl.
			// if the server can use one endpoint for both normal and partial files, then using "static_file" should have the same effect.
			// this will require the cdn server to have some sort of mapping on hand
			// but it will also allow the cdn server to do some caching, as the urls are the same
			resp.UrlList.Append(fmt.Sprintf("%s_map/%s", packHost, pack))
		} else if partialCapability == "has_range_api" {
			// end point is /static_api?&file=<file>&start=<start>&size=<size>
			// this allow the cdn server to implement a simple range download function.
			// it can be cached too if, but it'll be more vulnerable to random queries that doesn't represent an actual file.
			resp.UrlList.Append(fmt.Sprintf("%s_api?file=%s&start=%d&size=%d", packHost,
				downloadData.File, downloadData.Start, downloadData.Size))
		} else if partialCapability == "nothing" {
			// the cdn server can't deal with partial files, so it's up to elichika to help it
			// (the /static_virtual endpoint range-reads the metapack from the upstream). Use
			// selfHost so this address honours X-Forwarded-Host/Proto like every other
			// self-served URL here — otherwise it breaks behind a reverse proxy / HTTPS front end.
			resp.UrlList.Append(fmt.Sprintf("%s_virtual/%s", selfHost, pack))
		} else {
			log.Panic("wrong cdn_partial_file_capability")
		}
	}

	common.JsonResponse(ctx, &resp)
}

func init() {
	router.AddHandler("/", "POST", "/asset/getPackUrl", getPackUrl)
}
