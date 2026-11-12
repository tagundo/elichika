package managementmode

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// Boundary rejects DNS rebinding and foreign-origin writes before WebUI auth.
// The ordinary admin password and user session checks still run afterwards.
func Boundary(origin string) gin.HandlerFunc {
	host := strings.TrimPrefix(origin, "http://")
	return func(ctx *gin.Context) {
		if ctx.Request.Host != host {
			ctx.AbortWithStatus(http.StatusForbidden)
			return
		}
		if ctx.Request.Method != http.MethodGet && ctx.Request.Method != http.MethodHead && ctx.Request.Header.Get("Origin") != origin {
			ctx.AbortWithStatus(http.StatusForbidden)
			return
		}
		ctx.Header("Cache-Control", "no-store")
		ctx.Header("X-Content-Type-Options", "nosniff")
		ctx.Header("Referrer-Policy", "no-referrer")
		ctx.Set("management_mode", true)
		ctx.Next()
	}
}
