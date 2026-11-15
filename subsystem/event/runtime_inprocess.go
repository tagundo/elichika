//go:build elichika_inprocess

package event

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/event transient state", func() {
		// An interrupted event change must not affect the next runtime.
		isDirectEventChanging = false
		targetedEventId = 0
	})
}
