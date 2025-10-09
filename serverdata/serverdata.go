package serverdata

import (
	"elichika/db"
	"elichika/log"
	"elichika/utils"

	"xorm.io/xorm"
)

// the serverdata system work as follow:
// - each table has a defined structure and an initializer, which can be null
// - if a table is new or empty, the initializer is called
// - howerver, all tables are created before any intializer is called, so one initializer can initalize multiple tables

type Initializer = func(*xorm.Session)

var (
	engine                           *xorm.Engine
	Database                         *db.DatabaseSync
	serverDataTableNameToInterface   = map[string]interface{}{}
	serverDataTableNameToInitializer = map[string]Initializer{}

	// whether to rebuild the assets
	// setting this to true should only update the assets to the newest version, and if the version are the same, it should not change anything
	rebuildAsset bool
)

func addTable(tableName string, structure interface{}, initializer Initializer) {
	_, exist := serverDataTableNameToInterface[tableName]
	if exist {
		log.Panic("table already exist: " + tableName)
	}
	serverDataTableNameToInterface[tableName] = structure
	serverDataTableNameToInitializer[tableName] = initializer
}

func createTable(tableName string, structure interface{}, overwrite bool) bool {
	exist, err := engine.Table(tableName).IsTableExist(tableName)
	utils.CheckErr(err)

	if !exist {
		log.Println("Creating new table:", tableName)
		err = engine.Table(tableName).CreateTable(structure)
		utils.CheckErr(err)
		return true
	} else {
		if !overwrite {
			return false
		}
		log.Println("Overwrite existing table:", tableName)
		err := engine.DropTables(tableName)
		utils.CheckErr(err)
		err = engine.Table(tableName).CreateTable(structure)
		utils.CheckErr(err)
		return true
	}
}

func isTableEmpty(tableName string) bool {
	total, err := engine.Table(tableName).Count()
	utils.CheckErr(err)
	return total == 0
}

func InitTables() {
	initializers := []Initializer{}
	for tableName := range serverDataTableNameToInterface {
		overwrite := rebuildAsset
		newOrEmpty := createTable(tableName, serverDataTableNameToInterface[tableName], overwrite)
		newOrEmpty = newOrEmpty || isTableEmpty(tableName)
		if newOrEmpty {
			initializers = append(initializers, serverDataTableNameToInitializer[tableName])
		}
	}
	session := engine.NewSession()
	defer session.Close()
	session.Begin()
	for _, initializer := range initializers {
		if initializer == nil {
			continue
		}
		initializer(session)
	}
	session.Commit()
}
