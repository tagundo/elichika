package live_deck

import (
	"elichika/client/request"
	"elichika/client/response"
	"elichika/handler/common"
	"elichika/router"
	"elichika/subsystem/user_live_deck"
	"elichika/userdata"
	"elichika/utils"

	"encoding/json"

	"github.com/gin-gonic/gin"
)

func saveOverwriteDeck(ctx *gin.Context) {
	req := request.SaveOverwriteDeckRequest{}
	err := json.Unmarshal(*ctx.MustGet("reqBody").(*json.RawMessage), &req)
	utils.CheckErr(err)

	session := ctx.MustGet("session").(*userdata.Session)

	user_live_deck.SaveUserOverwriteDeck(session, req.SourceDeckId, req.DestDeckId)

	common.JsonResponse(ctx, response.UserModelResponse{
		UserModel: &session.UserModel,
	})
}

func init() {
	router.AddHandler("/", "POST", "/liveDeck/saveOverwriteDeck", saveOverwriteDeck)
}
