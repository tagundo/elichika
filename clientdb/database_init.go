package clientdb

import (
	"elichika/config"
	"elichika/log"
	"elichika/utils"

	"bufio"
	"fmt"
	"os"
	"strings"

	"xorm.io/xorm"
)

// a single sql file to apply to one of the client databases
type migration struct {
	name string
	path string
	// the client database to apply it to, taken from the file name
	dbName string
}

// list the migrations of a directory, in file name order
// a directory that doesn't exist simply has none: an asset repository is allowed to
// provide only the locale specific ones, or only the shared ones
func discoverMigrations(dir string) []migration {
	files, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	migrations := []migration{}
	for _, file := range files {
		// the shared directory holds the locale specific directories too
		if file.IsDir() {
			continue
		}
		name := file.Name()
		// file name has the format <order>.filename.sql
		// order must be exactly 3 digits (technically it can be any 3 characters)
		if len(name) <= 8 || !strings.HasSuffix(name, ".sql") {
			continue
		}
		migrations = append(migrations, migration{
			name:   name,
			path:   dir + name,
			dbName: name[4 : len(name)-4],
		})
	}
	return migrations
}

// note that this is subject to change, do not depend on it too much
func initLocale(locale string) {
	dbDir := fmt.Sprint("db/", locale, "/")

	// the migrations of this locale first, then the ones shared by every locale
	migrations := discoverMigrations(fmt.Sprint(config.AssetPath, "sql/", locale, "/"))
	migrations = append(migrations, discoverMigrations(fmt.Sprint(config.AssetPath, "sql/"))...)
	if len(migrations) == 0 {
		return
	}

	// for each file, if it has not changed then apply the update
	// if an error is encountered, no change would be made to any of the file
	var err error
	needUpdate := map[string]bool{}
	engines := map[string]*xorm.Engine{}
	sessions := map[string]*xorm.Session{}

	for _, file := range migrations {
		dbName := file.dbName
		need, exists := needUpdate[dbName]
		if !exists {
			needUpdate[dbName] = isNotChanged(dbDir + dbName)
			need = needUpdate[dbName]
		}
		if !need {
			continue
		}
		session, exists := sessions[dbName]
		if !exists {
			engines[dbName], err = xorm.NewEngine("sqlite", config.AssetPath+dbDir+dbName)
			utils.CheckErr(err)
			engines[dbName].SetMaxOpenConns(50)
			engines[dbName].SetMaxIdleConns(10)
			sessions[dbName] = engines[dbName].NewSession()
			session = sessions[dbName]
			session.Begin()
		}
		log.Println("Running SQL file: ", file.name)

		f, err := os.Open(file.path)
		utils.CheckErr(err)
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			_, err = session.Exec(scanner.Text())
			utils.CheckErr(err)

		}
		utils.CheckErr(scanner.Err())
	}
	for _, session := range sessions {
		err := session.Commit()
		utils.CheckErr(err)
		session.Close()
	}
}

// initialise the database inside of the db repository, if necessary
func databaseInit() {
	initLocale("gl")
	initLocale("jp")
}
