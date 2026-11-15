//go:build elichika_inprocess

package iosbridge

import (
	"elichika/config"
	_ "elichika/handler"
	"elichika/managementmode"
	"elichika/router"
	"elichika/runtimeinit"
	_ "elichika/subsystem"
	"elichika/userdata"
	_ "elichika/webui"

	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	_ "time/tzdata" // iOS has no Go installation containing zoneinfo.zip.

	"github.com/gin-gonic/gin"
)

func prepareServer(options Options, progress func(string)) (handler http.Handler, cleanup func() error, err error) {
	cleanup = func() error {
		defer managementmode.Release()
		return runtimeinit.Close()
	}
	defer func() {
		if failure := recover(); failure != nil {
			err = fmt.Errorf("game service initialization: %v", failure)
		}
		runtimeinit.Progress = nil
	}()
	if err = config.ConfigureRoot(options.DataRoot); err != nil {
		return
	}
	// Fail before creating partial databases when the host has not finished
	// installing its prepared payload. The full data loaders validate schemas.
	for _, relative := range []string{"serverdata.db", "privatekey.pem", "publickey.pem", "assets/db/gl/masterdata.db", "assets/db/jp/masterdata.db", "webui/admin/logged_in_admin.html", "webui/user/logged_in_user.html"} {
		info, statError := os.Stat(config.DataPath(relative))
		if statError != nil || !info.Mode().IsRegular() {
			err = fmt.Errorf("prepared payload is missing %s", relative)
			return
		}
	}
	if err = managementmode.Acquire(config.RootPath); err != nil {
		return
	}
	if err = validateKeys(options); err != nil {
		return
	}
	language := options.Language
	if language == "" && options.Region == "jp" {
		language = "ja"
	}
	if options.PacksRoot != "" {
		if err = os.MkdirAll(filepath.Clean(options.PacksRoot), 0700); err != nil {
			return
		}
	}
	config.ConfigureHost(options.ListenAddress, options.PacksRoot, language)
	runtimeinit.Progress = progress
	if err = runtimeinit.Initialize(); err != nil {
		return
	}
	progress("user tables")
	userdata.Init()
	gin.SetMode(gin.ReleaseMode)
	engine := gin.New()
	engine.Use(gin.RecoveryWithWriter(io.Discard))
	router.InProcessRouter(engine, options.ReadyToken, options.WebToken)
	handler = engine
	return
}
