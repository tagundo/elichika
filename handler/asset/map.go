package asset

import (
	"elichika/assetdata"
	"elichika/log"
	"elichika/router"

	"github.com/gin-gonic/gin"
)

// acting as the cdn, we need a map from file to actual files
func staticMap(ctx *gin.Context) {
	file := ctx.Param("fileName")
	downloadData := assetdata.GetDownloadData(file)
	if downloadData.IsEntireFile {
		log.Panic("entire file downloaded through map endpoint")
	}
	// getPackUrl hands out /static_map URLs whenever elichika serves a pack itself: the
	// self-host/cache modes, or a metapack that is already on disk (installed mods /
	// pre-downloaded packs) even with an external CDN. Outside those cases nothing
	// legitimate calls this endpoint, so refuse instead of letting arbitrary queries
	// trigger upstream downloads.
	if !selfServeStatic() {
		if _, ok := localPath(downloadData.File); !ok {
			log.Panic("staticMap is not allowed because elichika is not serving this pack itself")
		}
	}

	// ensureLocalFile downloads the whole metapack into sukusta/packs (when cdn_cache is enabled)
	// before we read the requested range out of it.
	sendRange(ctx, ensureLocalFile(downloadData.File), downloadData.Start, downloadData.Size)
}

func init() {
	router.AddHandler("/static_map", "GET", "/:fileName", staticMap)
}
