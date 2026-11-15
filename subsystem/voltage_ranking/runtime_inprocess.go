//go:build elichika_inprocess

package voltage_ranking

import (
	"elichika/client"
	"elichika/runtimeinit"
	"elichika/subsystem/cache"
)

func init() {
	runtimeinit.Register("subsystem/voltage_ranking caches", func() {
		// No requests retain cache entries when the host initializes a new runtime.
		rankingByLiveDifficultyId = map[int32]*RankingType{}
		getVoltageRankingDeckResponseCache = cache.UniquePointerMap[int64, cache.CachedObject[client.OtherUserDeckDetail]]{}
	})
}
