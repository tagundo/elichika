//go:build !embedded

package main

import (
	"elichika/config"
	_ "elichika/handler"
	"elichika/handler/asset"
	"elichika/log"
	"elichika/router"
	"elichika/shutdown"
	_ "elichika/subsystem"
	"elichika/subsystem/user_training_tree"
	"elichika/userdata"
	_ "elichika/webui"

	"os"
	"runtime"
	"strconv"

	"github.com/gin-gonic/gin"
)

// with some cli, we keep the server open
// return true to keep open
func checkCli() bool {
	if os.Args[1] == "rebuild_assets" {
		if len(os.Args) > 2 && os.Args[2] == "keep_alive" {
			return true
		}
	}
	if os.Args[1] == "fix_training_trees" {
		user_training_tree.FixUsersTrainingTrees()
	}
	if os.Args[1] == "download_packs" {
		// download every pack the CDN serves that isn't cached yet (skips what you already have).
		workers := 8
		if len(os.Args) > 2 {
			if n, err := strconv.Atoi(os.Args[2]); err == nil && n > 0 {
				workers = n
			}
		}
		asset.DownloadAllMissing(workers)
	}
	if os.Args[1] == "download_archive" {
		// bulk-download every game file from archive.org (does NOT use the game CDN),
		// then extract into the cache dir. os.Args[2] picks the region: gl | jp | both.
		regions := []string{"gl", "jp"}
		if len(os.Args) > 2 {
			switch os.Args[2] {
			case "gl":
				regions = []string{"gl"}
			case "jp":
				regions = []string{"jp"}
			}
		}
		asset.DownloadArchive(regions)
	}
	if os.Args[1] == "reset_accounts" {
		// wipe ALL accounts back to a new-account state while keeping their logins
		// (u_authentication). Used by the app's "Reset server" console action right
		// after the vanilla game data has been restored.
		resetAllAccounts()
	}
	if os.Args[1] == "cdn_cache" {
		// toggle (or set on/off) the CDN cache flag in config.json, so the app can
		// expose it as a console button. os.Args[2]: on | off | toggle (default toggle).
		if config.Conf.CdnCache == nil {
			b := false
			config.Conf.CdnCache = &b
		}
		next := !*config.Conf.CdnCache
		if len(os.Args) > 2 {
			switch os.Args[2] {
			case "on", "true", "1":
				next = true
			case "off", "false", "0":
				next = false
			}
		}
		*config.Conf.CdnCache = next
		if err := config.Conf.Save("./config.json"); err != nil {
			log.Println("cdn_cache: save failed:", err)
		} else if next {
			log.Println("cdn_cache: now ON (restart the server to apply)")
		} else {
			log.Println("cdn_cache: now OFF (restart the server to apply)")
		}
	}
	log.Println("CLI is reserved for special behaviour, the server will now exit, start it again without any argument!")
	return false
}

func main() {
	if len(os.Args) > 1 {
		if !checkCli() {
			return
		}
	}
	userdata.Init()
	runtime.GC()
	gin.SetMode(gin.ReleaseMode)

	r := gin.Default()
	router.Router(r)
	log.Println("server address: ", *config.Conf.ServerAddress)
	log.Println("WebUI address: ", *config.Conf.ServerAddress+"/webui/...")
	go func() {
		r.Run(*config.Conf.ServerAddress)
	}()
	shutdown.ReceiveFinalSignal()
}
