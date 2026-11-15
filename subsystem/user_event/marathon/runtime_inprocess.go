//go:build elichika_inprocess

package marathon

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/user_event/marathon caches", func() {
		eventMarathonRanking = nil
	})
}
