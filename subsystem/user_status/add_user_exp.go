package user_status

import (
	"elichika/client"
	"elichika/enum"
	"elichika/generic"
	"elichika/userdata"

	"elichika/subsystem/user_info_trigger"
)

func AddUserExp(session *userdata.Session, exp int32) {
	session.UserStatus.Exp += exp
	if session.Gamedata == nil || session.UserStatus.Rank < 1 {
		return
	}
	currentRank := session.Gamedata.UserRank[session.UserStatus.Rank]
	if currentRank == nil || currentRank.Rank != session.UserStatus.Rank || currentRank.Exp < 0 {
		return
	}
	trigger := client.UserInfoTriggerBasic{
		InfoTriggerType: enum.InfoTriggerTypeUserLevelUp,
		ParamInt:        generic.NewNullable(session.UserStatus.Rank),
	}
	isRankedUp := false
	for session.UserStatus.Rank < session.Gamedata.UserRankMax {
		nextRank := session.Gamedata.UserRank[session.UserStatus.Rank+1]
		if nextRank == nil || nextRank.Rank != session.UserStatus.Rank+1 || nextRank.Exp < 0 {
			break
		}
		if session.UserStatus.Exp >= nextRank.Exp {
			isRankedUp = true
			session.UserStatus.Rank++
			AddUserLp(session, nextRank.MaxLp)
			AddUserAccessoryLimit(session, nextRank.AdditionalAccessoryLimit)
		} else {
			break
		}
	}
	if isRankedUp {
		user_info_trigger.AddTriggerBasic(session, trigger)
	}
}
