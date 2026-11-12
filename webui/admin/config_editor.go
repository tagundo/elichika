package admin

import (
	"elichika/config"
	"elichika/i18n"
	"elichika/router"
	"elichika/utils"
	"elichika/webui/form/object_form"
	"elichika/webui/webui_utils"

	"html"
	"net/http"
	"net/url"
	"strings"

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
	starts += sourceCDNHelp(lang)
	form := object_form.GenerateWebForm(config.Conf, "config_form", `onclick="submit_form('config_form', './edit_config')"`, i18n.T(lang, "Reset to current config"), i18n.T(lang, "Update config"))
	for _, label := range []string{"Original-game source CDN", "Cache original game files locally"} {
		form = strings.Replace(form, "<label>"+label+"</label>", "<label>"+html.EscapeString(i18n.T(lang, label))+"</label>", 1)
	}

	ctx.HTML(http.StatusOK, "logged_in_admin.html", gin.H{
		"body": starts + form,
		"lang": lang,
	})
}

func sourceCDNHelp(lang string) string {
	text := `<p>` + html.EscapeString(i18n.T(lang, "Original game files use this source CDN or your optional local cache. Added mod files are served automatically by Elichika. Installing content does not change this address.")) + `</p>`
	current := ""
	if config.Conf.CdnServer != nil {
		current = *config.Conf.CdnServer
	}
	parsed, _ := url.Parse(current)
	if current == "elichika" || current == "elichika_tls" || parsed != nil &&
		(parsed.Hostname() == "127.0.0.1" || parsed.Hostname() == "::1" || parsed.Hostname() == "localhost") {
		text += `<p role="status">` + html.EscapeString(i18n.T(lang, "The source currently points to Elichika itself. Original files must already be local in this mode. If an older installer changed the address, use the default source CDN or enter your previous source, then save. Added mod files work automatically in either mode.")) + `</p>`
	}
	return text + `<button type="button" id="use-default-source-cdn" data-cdn="` + html.EscapeString(config.DefaultCdnServer) + `" onclick="document.querySelector('#config_form [name=CdnServer]').value=this.dataset.cdn">` + html.EscapeString(i18n.T(lang, "Use default source CDN")) + `</button><p>` + html.EscapeString(i18n.T(lang, "This fills the source CDN field. Save with Update config to apply; your current setting stays unchanged until then.")) + `</p>`
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
