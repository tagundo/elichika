package userdata

import (
	"elichika/client"
	"elichika/gamedata"
)

// NormalizeUserRankExp repairs accounts whose cumulative EXP is below their
// saved rank. Older default accounts started at rank 320 with zero EXP, while
// the client derives the live-result rank from cumulative EXP instead of Rank.
// Only raise the minimum: preserve the saved rank and all already valid EXP.
func NormalizeUserRankExp(status *client.UserStatus, gamedata *gamedata.Gamedata) {
	if status == nil || gamedata == nil || status.Rank < 1 {
		return
	}
	rank := gamedata.UserRank[status.Rank]
	if rank == nil || rank.Rank != status.Rank || rank.Exp < 0 {
		return
	}
	if status.Exp < rank.Exp {
		status.Exp = rank.Exp
	}
}
