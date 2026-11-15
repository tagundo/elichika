//go:build elichika_inprocess

package user_training_tree

import "elichika/runtimeinit"

func init() {
	runtimeinit.Register("subsystem/user_training_tree repair state", func() {
		// Repair scratch rows belong only to the database that produced them.
		fixInsertCells = []FixUserCardTrainingTreeCell{}
	})
}
