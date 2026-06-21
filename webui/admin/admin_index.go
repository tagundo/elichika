package admin

import (
	"elichika/i18n"
	"elichika/router"
	"elichika/webui/webui_utils"

	"net/http"

	"github.com/gin-gonic/gin"
)

func Index(ctx *gin.Context) {
	ctx.Header("Content-Type", "text/html")
	lang := webui_utils.Lang(ctx)

	// `+ window.location.search` keeps the ?l= language across navigation.
	starts := `<head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/></head>
	<div><button onclick="location.href='config_editor' + window.location.search" type="button">
			` + i18n.T(lang, "Config Editor") + `</button></div>
	<div><button onclick="location.href='event_selector' + window.location.search" type="button">
			` + i18n.T(lang, "Event Selector") + `</button></div>
	<div><button onclick="location.href='event_scheduler' + window.location.search" type="button">
			` + i18n.T(lang, "Event Scheduler") + `</button></div>
	<div><button onclick="location.href='maintenance_mode' + window.location.search" type="button">
			` + i18n.T(lang, "Maintenance Mode (for updating)") + `</button></div>
	`

	ctx.HTML(http.StatusOK, "logged_in_admin.html", gin.H{
		"body": starts,
		"lang": lang,
	})
}

func init() {
	router.AddHandler("/webui/admin", "GET", "/", Index)
}
