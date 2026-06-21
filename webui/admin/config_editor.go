package admin

import (
	"elichika/config"
	"elichika/i18n"
	"elichika/router"
	"elichika/utils"
	"elichika/webui/form/object_form"
	"elichika/webui/webui_utils"

	"net/http"

	"github.com/gin-gonic/gin"
)

func ConfigEditor(ctx *gin.Context) {
	ctx.Header("Content-Type", "text/html")
	lang := webui_utils.Lang(ctx)

	starts := `<head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/></head>
	<div>` + i18n.T(lang, "Update server runtime config.") + `</div>
	<div>` + i18n.T(lang, "Note that some configurations will be applied right away, some will requires restarting the server.") + `</div>
	<div>` + i18n.T(lang, "Finally, you can always delete the config.json to reset everything to default.") + `</div>
	`

	ctx.HTML(http.StatusOK, "logged_in_admin.html", gin.H{
		"body": starts + object_form.GenerateWebForm(config.Conf, "config_form", `onclick="submit_form('config_form', './edit_config')"`, i18n.T(lang, "Reset to current config"), i18n.T(lang, "Update config")),
		"lang": lang,
	})
}

func UpdateConfig(ctx *gin.Context) {
	newConfig := config.RuntimeConfig{}
	err := object_form.ParseForm(ctx, &newConfig)
	utils.CheckErr(err)
	config.UpdateConfig(&newConfig)
	webui_utils.CommonResponse(ctx, i18n.T(webui_utils.Lang(ctx), "Config updated, some changes will require a server restart to work."), "")
}

func init() {
	router.AddHandler("/webui/admin", "GET", "/config_editor", ConfigEditor)
	router.AddHandler("/webui/admin", "POST", "/edit_config", UpdateConfig)
}
