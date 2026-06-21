package admin

import (
	"elichika/i18n"
	"elichika/log"
	"elichika/router"
	"elichika/shutdown"
	"elichika/utils"
	"elichika/webui/webui_utils"

	"fmt"
	"net/http"
	"os"
	"os/exec"

	"github.com/gin-gonic/gin"
)

func MaintenanceMode(ctx *gin.Context) {
	ctx.Header("Content-Type", "text/html")
	lang := webui_utils.Lang(ctx)

	body := `<head><meta name="viewport" content="width=device-width, initial-scale=1"/></head>
	<div>` + i18n.T(lang, "Switch the server to maintainence mode so you can update elichika or do other work.") + `</div>
	<div>` + i18n.T(lang, "Note that once you click the button, elichika will shutdown and the admin webui will become temporarily unavailable.") + `</div>
	<div>` + i18n.T(lang, "It might take a while for elichika to fully shut down and for the maintainence server to be up, howerver it shouldn't take longer than a few minutes.") + `</div>
	<div>` + i18n.T(lang, "If it takes too long, then something went wrong and you'll have to restart elichika manually.") + `</div>
	<div>` + i18n.T(lang, "Note that even if you have a clear error message, elichika will still stop.") + `</div>
	<div><input type="button" value="` + i18n.T(lang, "Switch to maintainence mode") + `" onclick="submit_form(null, './run_alisa')"/></div>
	`
	ctx.HTML(http.StatusOK, "logged_in_admin.html", gin.H{
		"body": body,
		"lang": lang,
	})
}

func RunAlisa(ctx *gin.Context) {
	// build the maintenance server if necessary
	shutdown.Shutdown()
	shutdown.WaitForFinish()
	good := false
	defer func() {
		defer func() {
			shutdown.SendFinalSignal()
		}()
		if !good {
			return
		}
		cmd := exec.Command("./alisa")
		cmd.Stdin = os.Stdin
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		err := cmd.Start()
		utils.CheckErr(err)
		err = cmd.Process.Release()
		utils.CheckErr(err)
	}()
	output, err := exec.Command("go", "build", "./webui/alisa").Output()
	if err != nil {
		cmd := exec.Command("go", "build", "./webui/alisa")
		cmd.Env = append(os.Environ(), "CGO_ENABLED=0")
		output, err = cmd.Output()
	}
	if err != nil {
		webui_utils.CommonResponse(ctx, "Error when building the maintenence server: "+fmt.Sprint("\noutput: ", output, "\nerror: ", err), "")
		log.Panic(err)
	}
	webui_utils.CommonResponse(ctx, i18n.T(webui_utils.Lang(ctx), "No error detected, trying to start maintenance server."), "")
	good = true
}

func init() {
	router.AddHandler("/webui/admin", "GET", "/maintenance_mode", MaintenanceMode)
	router.AddHandler("/webui/admin", "POST", "/run_alisa", RunAlisa)
}
