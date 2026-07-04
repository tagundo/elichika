package user

import (
	"elichika/router"
	"elichika/subsystem/reset_progress"
	"elichika/subsystem/user_account"
	"elichika/userdata"
	"elichika/userdata/database"
	"elichika/utils"
	"elichika/webui/form/object_form"
	"elichika/webui/webui_utils"

	"encoding/json"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ResetRequest struct {
	StoryMain    bool `of_label:"Main story"`
	StorySide    bool `of_label:"Side story (card story)"`
	StoryMember  bool `of_label:"Member story (bond episode)"`
	StoryLinkage bool `of_label:"Linkage story (anime tie-in)"`
	StoryEvent   bool `of_label:"Event story"`
	Tower        bool `of_label:"DLP"`
}

// dangerous full-account reset section, shown below the per-aspect reset form.
// This is deliberately a SEPARATE button (not mixed with the checkboxes above) and carries
// a strong confirm dialog because it wipes the whole account and cannot be undone.
const resetAccountSection = `<hr>
<div><label><b>Danger zone &mdash; reset this ACCOUNT:</b></label></div>
<div><label>This is an ACCOUNT reset: it resets your ENTIRE account back to a brand-new-account state. ALL progress, cards, items, decks, costumes and story unlocks will be wiped and this CANNOT be undone. Your login (authentication) is preserved, so the game will keep talking to the server &mdash; it will just look like a fresh account. If you might want your data back, export a backup from "Import / Export account" first.</label></div>
<div><label>Note: installed mod costumes are SERVER data, not account data, so they are NOT removed by this. To remove installed mods and restore the original game data, use "Reset server" in the app console instead.</label></div>
<div><button type="button" onclick="if (confirm('WARNING: This PERMANENTLY resets your ENTIRE account to a fresh new-account state.\n\nALL progress, cards, items, decks, costumes and story unlocks will be lost and this CANNOT be undone.\n\nYour login is kept, so the game will keep working, but everything will be back to a new account.\n\n(Installed mod costumes are server data and are NOT removed - use the app console\'s Reset server for that.)\n\nAre you absolutely sure?')) submit_form(null, 'reset_account')">Reset account to initial state (keep login)</button></div>
`

func resetForm(ctx *gin.Context) {
	form := object_form.GenerateWebForm(&ResetRequest{}, "reset_form",
		` onclick="if (confirm('Reset progress?')) submit_form('reset_form', 'reset')"`, "Clear", "Reset progress")

	ctx.HTML(http.StatusOK, "logged_in_user.html", gin.H{
		"body": `<div><label>Choose aspect(s) to reset: </label></div>` + "\n" + form + "\n" + resetAccountSection,
	})
}

func ResetHandler(ctx *gin.Context) {
	req := ResetRequest{}
	err := object_form.ParseForm(ctx, &req)
	utils.CheckErr(err)

	session := ctx.MustGet("session").(*userdata.Session)
	resp := webui_utils.Response{
		Response: new(string),
	}

	if req.StoryMain {
		*resp.Response += "Main story progress was reset\n"
		reset_progress.RemoveUserProgress(session, "u_story_main")
		reset_progress.RemoveUserProgress(session, "u_story_main_part_digest_movie")
		reset_progress.RemoveUserProgress(session, "u_story_main_selected")
	}
	if req.StorySide {
		*resp.Response += "Side story progress was reset\n"
		reset_progress.MarkIsNew(session, "u_story_side", true)
	}
	if req.StoryMember {
		*resp.Response += "Bond story progress was reset\n"
		reset_progress.MarkIsNew(session, "u_story_member", true)
	}
	if req.StoryLinkage {
		*resp.Response += "Linkage story progress was reset\n"
		reset_progress.RemoveUserProgress(session, "u_story_linkage")
	}
	if req.StoryEvent {
		*resp.Response += "Event story unlock progress was reset, memory keys added\n"
		reset_progress.RemoveUserProgress(session, "u_story_event_history")
	}
	if req.Tower {
		*resp.Response += "DLP progress was reset\n"
		reset_progress.RemoveUserProgress(session, "u_tower")
	}
	session.Finalize()

	if *resp.Response == "" {
		*resp.Response = "There was nothing to reset!\n"
	}

	jsonBytes, err := json.Marshal(resp)
	utils.CheckErr(err)
	ctx.Header("Content-Type", "application/json")
	ctx.String(http.StatusOK, string(jsonBytes))
}

// ResetAccountHandler resets the CURRENT logged-in account back to a fresh new-account state
// while preserving the client's login, so the game keeps talking to the server.
//
// Correctness notes:
//   - We delete every user table EXCEPT u_authentication, so the account's identity and its
//     AuthorizationKey survive. The client authenticates with that key, so it keeps validating.
//   - We set the request session to SessionTypeDirectDbWrite BEFORE Finalize. With that type,
//     Session.Finalize() skips ALL finalizers (which would otherwise write the stale in-memory
//     u_status/etc. back and corrupt the reset) and only commits the raw deletes. This mirrors
//     userdata.(*Session).ImportDatabaseData.
//   - The userdata engine is SQLite with MaxOpenConns(1): the request session holds that single
//     connection via its open transaction. We MUST commit (Finalize) to release it before
//     calling CreateNewAccount, which opens its own sessions on userdata.Engine. This mirrors the
//     take_over.setTakeOver flow, which only calls CreateNewAccount once no session holds the
//     connection.
//   - CreateNewAccount re-seeds a fresh account for the SAME userId. Internally it loads the
//     preserved u_authentication row (userdata.GetSession -> fetchAuthenticationData) and writes
//     back the SAME AuthorizationKey; nothing calls GenerateNewAuthorizationKey, so the key is
//     unchanged and the client's saved login stays valid.
func ResetAccountHandler(ctx *gin.Context) {
	session := ctx.MustGet("session").(*userdata.Session)
	userId := session.UserId

	// Prevent the normal finalizers from writing stale in-memory data (old u_status, ...) back;
	// with SessionTypeDirectDbWrite, Finalize only commits the raw deletes below.
	session.SessionType = userdata.SessionTypeDirectDbWrite
	for table := range database.UserDataTableNameToInterface {
		if table == "u_authentication" {
			// Preserve identity + AuthorizationKey so the client's login keeps working.
			continue
		}
		// Some tables (e.g. u_member_guild_daily_coop_point) have no user_id column, so this
		// Delete errors on them. Ignore the error per-table (a failed statement does not abort
		// the surrounding SQLite transaction) instead of letting utils.CheckErr panic.
		session.Db.Table(table).Where("user_id = ?", session.UserId).Delete()
	}
	// Commit the deletes and release the single SQLite connection so CreateNewAccount can run.
	session.Finalize()

	// Re-seed a fresh account for the same userId with an empty WebUI password (new-account
	// default). The preserved u_authentication row is loaded and its AuthorizationKey re-saved
	// unchanged, so the game client is unaffected.
	user_account.CreateNewAccount(ctx, userId, "")

	webui_utils.CommonResponse(ctx,
		"Account was reset to its initial state. Your login was preserved, so the game client can keep talking to the server.\n", "")
}

func init() {
	addFeature("Reset Progress", "reset")
	router.AddHandler("/webui/user", "GET", "/reset", resetForm)
	router.AddHandler("/webui/user", "POST", "/reset", ResetHandler)
	router.AddHandler("/webui/user", "POST", "/reset_account", ResetAccountHandler)
}
