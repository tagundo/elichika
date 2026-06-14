package asset

// serve a whole pack/metapack file, acting as the cdn.
// this replaces gin's plain static file server so that, with cdn_cache enabled, a pack that isn't on
// disk yet is downloaded from the upstream CDN into sukusta/packs on first request and served from there.

import (
	"elichika/router"

	"github.com/gin-gonic/gin"
)

func staticWhole(ctx *gin.Context) {
	file := ctx.Param("fileName")
	// ctx.File uses http.ServeFile: it sets the content type/length, supports Range requests, and
	// returns 404 if the file is missing (e.g. when caching is off and the pack isn't local).
	ctx.File(ensureLocalFile(file))
}

func init() {
	router.AddHandler("/static", "GET", "/:fileName", staticWhole)
}
