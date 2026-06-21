package admin

import (
	"elichika/config"
	"elichika/i18n"
	"elichika/router"
	"elichika/utils"
	"elichika/webui/webui_utils"

	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"mime/multipart"
	"net/http"

	"github.com/gin-gonic/gin"
)

func login(ctx *gin.Context) {
	var respString string
	resp := webui_utils.Response{}
	form := ctx.MustGet("form").(*multipart.Form)

	adminPassword := form.Value["admin_password"][0]
	if subtle.ConstantTimeCompare([]byte(*config.Conf.AdminPassword), []byte(adminPassword)) == 1 {
		newSessionKey()
		resp.Response = &respString
		*resp.Response = base64.StdEncoding.EncodeToString(adminSessionKey)
	} else {
		resp.Error = &respString
		*resp.Error = i18n.T(webui_utils.Lang(ctx), "Wrong password!")
	}

	jsonBytes, err := json.Marshal(resp)
	utils.CheckErr(err)

	ctx.Header("Content-Type", "application/json")
	ctx.String(http.StatusOK, string(jsonBytes))
}

func init() {
	router.AddSpecialSetup("/webui/admin", func(group *gin.RouterGroup) {
		group.StaticFile("/login", config.RootPath+"webui/admin/login.html")
	})
	router.AddHandler("/webui/admin", "POST", "/login", login)
}
