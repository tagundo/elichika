//go:build elichika_inprocess

package user_tower

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/user_tower caches", func() {
		// Rankings must be rebuilt from the current userdata database.
		rankingByTowerId = map[int32]*RankingType{}
	})
}
