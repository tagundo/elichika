package asset

import (
	"elichika/log"
	"elichika/router"
	"elichika/utils"

	"fmt"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

func staticApi(ctx *gin.Context) {
	// The range API only makes sense when elichika serves static data itself (self-host or
	// cache mode); with an external CDN nothing legitimate calls it, so keep it closed
	// instead of answering arbitrary range probes.
	if !selfServeStatic() {
		log.Panic("staticApi is not allowed because elichika is not serving static data itself")
	}
	masterVersion, exist := ctx.GetQuery("master")
	utils.MustExist(exist)
	file, exist := ctx.GetQuery("file")
	utils.MustExist(exist)
	startString, exist := ctx.GetQuery("start")
	utils.MustExist(exist)
	start, err := strconv.Atoi(startString)
	utils.CheckErr(err)
	sizeString, exist := ctx.GetQuery("size")
	utils.MustExist(exist)
	size, err := strconv.Atoi(sizeString)
	utils.CheckErr(err)
	path := fmt.Sprintf("static/%s/%s", masterVersion, file)
	if strings.Contains(path, "..") {
		log.Panic("Bad path (contains ..)")
	}
	sendRange(ctx, path, start, size)
}

func init() {
	router.AddHandler("/static_api", "GET", "/", staticApi)
}
