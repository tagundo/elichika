package serverstate

import (
	"elichika/config"
	"elichika/db"
	"elichika/runtimeinit"
	"elichika/utils"

	"os"

	"xorm.io/xorm"
)

func init() {
	runtimeinit.Register("serverstate", initialize)
}

func initialize() {
	var err error
	engine, err = xorm.NewEngine("sqlite", config.ServerstatePath)
	utils.CheckErr(err)
	engine.SetMaxOpenConns(50)
	engine.SetMaxIdleConns(10)
	runtimeinit.TrackCloser(engine.Close)
	resetServer = !runtimeinit.InProcess && (len(os.Args) >= 2) && (os.Args[1] == "reset_server")
	InitTables()
	engine.Close()
	Database, err = db.NewDatabase(config.ServerstatePath)
	utils.CheckErr(err)
}
