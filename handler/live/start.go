package live

import (
	"elichika/client/request"
	"elichika/handler/common"
	"elichika/router"
	"elichika/subsystem/user_live"
	"elichika/userdata"
	"elichika/utils"

	"encoding/json"
	"net/http"

	"github.com/gin-gonic/gin"
)

func start(ctx *gin.Context) {
	req := request.StartLiveRequest{}
	err := json.Unmarshal(*ctx.MustGet("reqBody").(*json.RawMessage), &req)
	utils.CheckErr(err)

	session := ctx.MustGet("session").(*userdata.Session)
	if !requireRhythmChart(ctx, session, req.LiveDifficultyId) {
		return
	}

	resp := user_live.StartLive(session, req)

	common.JsonResponse(ctx, &resp)
}

func requireRhythmChart(ctx *gin.Context, session *userdata.Session, difficultyID int32) bool {
	if session != nil && session.Gamedata != nil && session.Gamedata.LiveDifficulty[difficultyID] != nil {
		return true
	}
	ctx.AbortWithStatusJSON(http.StatusBadRequest, gin.H{"error": "No rhythm chart for that difficulty"})
	return false
}

func init() {
	router.AddHandler("/", "POST", "/live/start", start)
}
