package userdata

import (
	"elichika/client"
	"elichika/log"
	"elichika/utils"
)

// NormalizeHomeSuits replaces removed HOME costumes with each member's owned
// initial costume. Call only after Login has populated the complete user model.
// Existing master entries, including mod costumes, are left unchanged.
func (session *Session) NormalizeHomeSuits() int {
	if session == nil || session.Db == nil || session.UserStatus == nil || session.Gamedata == nil ||
		session.SessionType != SessionTypeLogin || session.Finalized || session.IsBasic {
		return 0
	}
	repaired := 0
	for _, memberID := range session.UserModel.UserMemberByMemberId.OrderedKey {
		masterMember := session.Gamedata.Member[memberID]
		if masterMember == nil || masterMember.Id != memberID {
			continue
		}
		member, exists := session.UserModel.UserMemberByMemberId.Get(memberID)
		if !exists || member == nil || member.MemberMasterId != memberID {
			continue
		}
		if session.Gamedata.Suit[member.SuitMasterId] != nil {
			continue
		}

		suitID := masterMember.MemberInit.SuitMasterId
		initialSuit := session.Gamedata.Suit[suitID]
		if suitID <= 0 || initialSuit == nil || initialSuit.Id != suitID ||
			initialSuit.MemberMId == nil || *initialSuit.MemberMId != memberID {
			continue
		}
		owned, exists := session.UserModel.UserSuitBySuitId.Get(suitID)
		if !exists || owned == nil || owned.SuitMasterId != suitID {
			continue
		}

		// Login finalizes only status/authentication. Persist this one member
		// column in its transaction and reflect the same value in the response.
		changed := client.UserMember{SuitMasterId: suitID}
		affected, err := session.Db.Table("u_member").
			Where("user_id = ? AND member_master_id = ? AND suit_master_id = ?",
				session.UserId, memberID, member.SuitMasterId).
			Cols("suit_master_id").Update(&changed)
		utils.CheckErr(err)
		if affected != 1 {
			log.Panic("HOME member changed during login")
		}
		member.SuitMasterId = suitID
		repaired++
	}
	return repaired
}
