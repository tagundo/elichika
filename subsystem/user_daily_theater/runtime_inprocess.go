//go:build elichika_inprocess

package user_daily_theater

import (
	"elichika/client/response"
	"elichika/runtimeinit"
)

func init() {
	runtimeinit.Register("subsystem/user_daily_theater caches", func() {
		// The host drains requests before reloading the data backing this cache.
		dailyTheaterArchive = map[string]*response.FetchDailyTheaterArchiveResponse{}
	})
}
