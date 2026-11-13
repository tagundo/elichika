package admin

import (
	"elichika/router"
	"elichika/utils"
	"elichika/webui/webui_utils"

	"bytes"
	"encoding/base64"
	"strings"

	"github.com/gin-gonic/gin"
)

func adminInitial(ctx *gin.Context) {
	if ctx.Request.Method == "POST" {
		form, err := ctx.MultipartForm()
		utils.CheckErr(err)
		ctx.Set("form", form)
		if !strings.HasPrefix(ctx.Request.URL.String(), "/webui/admin/login") && !webui_utils.LocalTrusted(ctx) {
			sessionKey, err := base64.StdEncoding.DecodeString(ctx.PostForm("admin_session_key"))
			if err != nil || !bytes.Equal(sessionKey, adminSessionKey) {
				ctx.AbortWithStatus(403)
				return
			}
		}
	}
	ctx.Next()
}

func init() {
	router.AddInitialHandler("/webui/admin", adminInitial)
}
