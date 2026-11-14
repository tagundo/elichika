package live_mv

import (
	"elichika/client/request"
	"elichika/client/response"
	"elichika/handler/common"
	"elichika/log"
	"elichika/router"
	"elichika/subsystem/user_live_mv"
	"elichika/userdata"
	"elichika/utils"

	"encoding/json"
	"fmt"
	"strings"

	"github.com/gin-gonic/gin"
)

func saveDeck(ctx *gin.Context) {
	req := request.SaveLiveMvDeckRequest{}
	err := json.Unmarshal(*ctx.MustGet("reqBody").(*json.RawMessage), &req)
	utils.CheckErr(err)

	selection := liveMvDeckSelectionSummary(&req)
	log.Printf("mv deck received: live=%d type=%d slots=[%s] member_entries=%d suit_entries=%d\n",
		req.LiveMasterId, req.LiveMvDeckType, selection, len(req.MemberMasterIdByPos.Map), len(req.SuitMasterIdByPos.Map))

	session := ctx.MustGet("session").(*userdata.Session)

	user_live_mv.SetLiveMvDeck(session, req.LiveMasterId, req.LiveMvDeckType, req.MemberMasterIdByPos, req.SuitMasterIdByPos, req.ViewStatusByPos)

	common.JsonResponse(ctx, response.UserModelResponse{
		UserModel: &session.UserModel,
	})

	// JsonResponse finalizes the session before serializing and sending the response.
	// A failed finalizer or commit panics before this completion diagnostic.
	custom, customPresent := session.UserModel.UserLiveMvDeckCustomById.Get(req.LiveMasterId)
	log.Printf("mv deck completed: live=%d type=%d slots=[%s] returned_custom=%t committed=%t response_status=%d context_errors=%d\n",
		req.LiveMasterId, req.LiveMvDeckType, selection, customPresent && custom != nil,
		session.Finalized && !session.IsSharedDb, ctx.Writer.Status(), len(ctx.Errors))
}

// liveMvDeckSelectionSummary reports only the twelve supported MV positions.
// It excludes account/connection data and keeps malformed large dictionaries
// from turning one request into an unbounded console message.
func liveMvDeckSelectionSummary(req *request.SaveLiveMvDeckRequest) string {
	var summary strings.Builder
	for pos := int32(1); pos <= 12; pos++ {
		member, memberPresent := req.MemberMasterIdByPos.Get(pos)
		suit, suitPresent := req.SuitMasterIdByPos.Get(pos)
		if !memberPresent && !suitPresent {
			continue
		}
		if summary.Len() > 0 {
			summary.WriteByte(' ')
		}
		fmt.Fprintf(&summary, "%d:m=", pos)
		if member == nil {
			summary.WriteString("null")
		} else {
			fmt.Fprintf(&summary, "%d", *member)
		}
		summary.WriteString(",s=")
		if suit == nil || !suit.HasValue {
			summary.WriteString("null")
		} else {
			fmt.Fprintf(&summary, "%d", suit.Value)
		}
	}
	return summary.String()
}

func init() {
	router.AddHandler("/", "POST", "/liveMv/saveDeck", saveDeck)
}
