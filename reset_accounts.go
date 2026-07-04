//go:build !embedded

package main

import (
	"elichika/locale"
	"elichika/log"
	"elichika/subsystem/user_account"
	"elichika/userdata"
	"elichika/userdata/database"
	"elichika/utils"

	"strconv"

	"github.com/gin-gonic/gin"
)

// resetAllAccounts wipes EVERY account in userdata.db back to a brand-new-account
// state while preserving each account's login (u_authentication), so game clients
// keep authenticating with their saved AuthorizationKey afterwards.
//
// This is the account half of the app's "Reset server" console action: the app
// first restores the bundled vanilla game data (removing installed mods), then
// runs this verb so no account keeps costumes/cards that no longer exist in the
// restored master data. It mirrors the per-account WebUI reset
// (webui/user.ResetAccountHandler) but covers all accounts and clears whole
// tables, which also empties the few tables that have no user_id column.
func resetAllAccounts() {
	userdata.Init()

	ids := []int32{}
	{
		db := userdata.Engine.NewSession()
		err := db.Begin()
		utils.CheckErr(err)
		rows, err := db.QueryString("SELECT user_id FROM u_authentication")
		utils.CheckErr(err)
		for _, row := range rows {
			id, err := strconv.Atoi(row["user_id"])
			utils.CheckErr(err)
			ids = append(ids, int32(id))
		}
		for table := range database.UserDataTableNameToInterface {
			if table == "u_authentication" {
				// Preserve identity + AuthorizationKey so saved logins keep working.
				continue
			}
			_, err := db.Exec("DELETE FROM \"" + table + "\"")
			utils.CheckErr(err)
		}
		err = db.Commit()
		utils.CheckErr(err)
		db.Close()
	}

	if len(ids) == 0 {
		log.Println("reset_accounts: no accounts found, nothing to re-seed")
		return
	}

	// CreateNewAccount reads gamedata/dictionary from the gin context; outside a
	// request we hand it a bare context carrying a loaded locale ("en" always
	// resolves — locale.init aliases unselected locales to a loaded one).
	ctx := &gin.Context{}
	ctx.Set("gamedata", locale.Locales["en"].Gamedata)
	ctx.Set("dictionary", locale.Locales["en"].Dictionary)
	for _, id := range ids {
		// Re-seeds a fresh account for the same userId; the preserved
		// u_authentication row is loaded and its AuthorizationKey re-saved
		// unchanged, so the game client's saved login stays valid.
		user_account.CreateNewAccount(ctx, id, "")
		log.Println("reset_accounts: account", id, "was reset (login preserved)")
	}
}
