package admin

import (
	"elichika/nativeaccess"
	"elichika/router"
	"net/http"

	"github.com/gin-gonic/gin"
)

func init() {
	router.AddHandler("/webui/admin", "GET", "/native_access", func(ctx *gin.Context) {
		ctx.Header("Cache-Control", "no-store")
		ctx.JSON(http.StatusOK, gin.H{"native_local": nativeaccess.Authorized(ctx)})
	})
}
