package asset

// serve a whole pack/metapack file, acting as the cdn.
// this replaces gin's plain static file server so that, with cdn_cache enabled, a pack that isn't on
// disk yet is downloaded from the upstream CDN into the cache directory on first request and served
// from there.
//
// the route is a catch-all (*fileName) to match gin's original r.Static behavior: besides flat pack
// names, the game also downloads nested paths like /static/<masterVersion>/masterdata_a_ko.

import (
	"elichika/router"

	"strings"

	"github.com/gin-gonic/gin"
)

func staticWhole(ctx *gin.Context) {
	// a catch-all param keeps the leading slash, e.g. "/8d4c19e12fb304cf/masterdata_a_ko"
	file := strings.TrimPrefix(ctx.Param("fileName"), "/")
	// ctx.File uses http.ServeFile: it sets the content type/length, supports Range requests, and
	// returns 404 if the file is missing (e.g. when caching is off and the pack isn't local).
	ctx.File(ensureLocalFile(file))
}

func init() {
	router.AddHandler("/static", "GET", "/*fileName", staticWhole)
}
