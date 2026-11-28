package admin

import (
	"elichika/i18n"
	"elichika/router"
	"elichika/userdata"
	"elichika/webui/webui_utils"

	"errors"
	"fmt"
	"html"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
)

// The admin user manager lists accounts and deletes one (userdata.DeleteAccount).

func UserManager(ctx *gin.Context) {
	ctx.Header("Content-Type", "text/html")
	lang := webui_utils.Lang(ctx)
	users, err := userdata.ListAccounts(userdata.Engine)
	body := `<head><meta name="viewport" content="width=device-width, initial-scale=1"/></head>
	<div>` + i18n.T(lang, "Delete an account completely, including its login. A full copy of the user database is saved first; put that file back as userdata.db to undo.") + `</div>
	<div>` + i18n.T(lang, "Delete an account only while that player is not playing.") + `</div>`
	if err != nil {
		body += `<div>` + html.EscapeString(err.Error()) + `</div>`
	} else if len(users) == 0 {
		body += `<div>` + i18n.T(lang, "No accounts.") + `</div>`
	} else {
		body += `<table><tr><th>` + i18n.T(lang, "User ID") + `</th><th>` + i18n.T(lang, "Name") + `</th><th>` +
			i18n.T(lang, "Last login") + `</th><th></th></tr>`
		for _, user := range users {
			id := strconv.Itoa(int(user.UserId))
			last := "-"
			if user.LastLoginAt > 0 {
				last = time.Unix(user.LastLoginAt, 0).Format("2006-01-02 15:04")
			}
			confirm := fmt.Sprintf(i18n.T(lang, "Delete account %d (%s) and its login? This cannot be undone in the game."), user.UserId, user.Name)
			body += `<tr><td>` + id + `</td><td>` + html.EscapeString(user.Name) + `</td><td>` + last + `</td><td>` +
				`<form id="delete_user_` + id + `"><input type="hidden" name="user_id" value="` + id + `"/></form>` +
				`<button type="button" data-confirm="` + html.EscapeString(confirm) + `" onclick="if (confirm(this.dataset.confirm)) submit_form('delete_user_` + id +
				`', './delete_user' + window.location.search, false, () => location.reload())">` + i18n.T(lang, "Delete") + `</button></td></tr>`
		}
		body += `</table>`
	}
	ctx.HTML(http.StatusOK, "logged_in_admin.html", gin.H{
		"body": body,
		"lang": lang,
	})
}

func DeleteUser(ctx *gin.Context) {
	lang := webui_utils.Lang(ctx)
	userId, err := strconv.ParseInt(ctx.PostForm("user_id"), 10, 32)
	if err != nil {
		webui_utils.CommonResponse(ctx, i18n.T(lang, "Choose an account to delete."), "")
		return
	}
	backup, err := userdata.DeleteAccount(userdata.Engine, int32(userId), userdata.DeletedAccountBackupDir(), time.Now())
	switch {
	case errors.Is(err, userdata.ErrAccountNotFound):
		webui_utils.CommonResponse(ctx, i18n.T(lang, "That account no longer exists."), "")
	case err != nil:
		webui_utils.CommonResponse(ctx, i18n.T(lang, "The account was not deleted: ")+err.Error(), "")
	default:
		webui_utils.CommonResponse(ctx, i18n.T(lang, "Deleted. Backup: ")+backup, "")
	}
}

func init() {
	router.AddHandler("/webui/admin", "GET", "/user_manager", UserManager)
	router.AddHandler("/webui/admin", "POST", "/delete_user", DeleteUser)
}
