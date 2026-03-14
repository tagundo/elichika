package user_live_deck

import (
	"elichika/subsystem/user_live_party"
	"elichika/userdata"
)

func SaveUserOverwriteDeck(session *userdata.Session, sourceDeckId, destDeckId int32) {
	userLiveDeck := GetUserLiveDeck(session, sourceDeckId)
	userLiveDeck.UserLiveDeckId = destDeckId
	UpdateUserLiveDeck(session, userLiveDeck)
	liveParties := user_live_party.GetUserLivePartiesWithDeckId(session, sourceDeckId)
	for i := 0; i < 3; i++ {
		liveParties[i].UserLiveDeckId = destDeckId
		liveParties[i].PartyId = destDeckId*100 + int32(i) + 1
		user_live_party.UpdateUserLiveParty(session, liveParties[i])
	}
}
