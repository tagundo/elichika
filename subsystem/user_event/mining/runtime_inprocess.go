//go:build elichika_inprocess

package mining

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/user_event/mining caches", func() {
		eventMiningPointRanking = nil
		eventMiningVoltageRanking = nil
		// The next summary reads the selection amount from the reloaded event.
		voltageSelectionAmount = 1
	})
}
