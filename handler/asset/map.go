package asset

import (
	"elichika/assetdata"
	"elichika/log"
	"elichika/router"
	"elichika/config"
	"github.com/gin-gonic/gin"
)

// acting as the cdn, we need a map from file to actual files
func staticMap(ctx *gin.Context) {
	if (*config.Conf.CdnServer != "elichika") && (*config.Conf.CdnServer != "elichika_tls") {
		log.Panic("staticMap is not allowed because CDN is not elichika or elichika tls")
	}
	file := ctx.Param("fileName")
	downloadData := assetdata.GetDownloadData(file)
	if downloadData.IsEntireFile {
		log.Panic("entire file downloaded through map endpoint")
	}

	// ensureLocalFile downloads the whole metapack into sukusta/packs (when cdn_cache is enabled)
	// before we read the requested range out of it.
	sendRange(ctx, ensureLocalFile(downloadData.File), downloadData.Start, downloadData.Size)
}

func init() {
	router.AddHandler("/static_map", "GET", "/:fileName", staticMap)
}
