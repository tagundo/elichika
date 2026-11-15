//go:build elichika_inprocess

package user_love_ranking

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/user_love_ranking caches", func() {
		// Generate the summary for the current database on its next request.
		lastGeneratedAt = 0
	})
}
