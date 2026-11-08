package gamedata

import (
	"elichika/client"

	"xorm.io/xorm"
)

func loadTrainingTreeDetails(gamedata *Gamedata) (loaded bool, err error) {
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		for _, spec := range []struct {
			table  string
			key    []string
			unique [][]string
		}{
			{"m_training_tree_card_param", []string{"id", "training_content_no"}, nil},
			{"m_training_tree_card_story_side", []string{"card_m_id", "training_content_type", "training_content_no"}, nil},
			{"m_training_tree_card_suit", []string{"card_m_id", "training_content_no"}, [][]string{{"suit_m_id"}}},
			{"m_training_tree_card_voice", []string{"card_m_id", "training_content_no"}, nil},
			{"m_training_tree_progress_reward", []string{"card_master_id", "activate_num", "display_order"}, nil},
		} {
			var safe bool
			safe, err = batchReadOrderSafe(session, spec.table, spec.key, spec.unique...)
			if err != nil || !safe {
				return
			}
		}
		params := make(map[int32][]*TrainingTree)
		for _, tree := range gamedata.TrainingTree {
			params[tree.TrainingTreeCardParamMId] = append(params[tree.TrainingTreeCardParamMId], tree)
			tree.TrainingTreeCardParams = []TrainingTreeCardParam{{}}
			tree.TrainingTreeCardStorySides = make(map[int32]int32)
			tree.SuitMIds, tree.NaviActionIds = []int32{0}, []int32{0}
		}
		type paramRow struct {
			Owner                 int32 `xorm:"'id'"`
			TrainingTreeCardParam `xorm:"extends"`
		}
		err = batchRows(session.Table("m_training_tree_card_param").Where("id IN (SELECT training_tree_card_param_m_id FROM m_training_tree)").OrderBy("id, training_content_no"), new(paramRow), func(_ int, bean interface{}) error {
			row := bean.(*paramRow)
			for _, tree := range params[row.Owner] {
				tree.TrainingTreeCardParams = append(tree.TrainingTreeCardParams, row.TrainingTreeCardParam)
			}
			return nil
		})
		if err != nil {
			return
		}
		type storyRow struct {
			Owner                     int32 `xorm:"'card_m_id'"`
			TrainingTreeCardStorySide `xorm:"extends"`
		}
		err = batchRows(session.Table("m_training_tree_card_story_side").Where("card_m_id IN (SELECT id FROM m_training_tree)").OrderBy("card_m_id, training_content_type, training_content_no"), new(storyRow), func(_ int, bean interface{}) error {
			row := bean.(*storyRow)
			if tree := gamedata.TrainingTree[row.Owner]; tree != nil {
				tree.TrainingTreeCardStorySides[row.TrainingContentType] = row.StorySideMId
			}
			return nil
		})
		if err != nil {
			return
		}
		type suitRow struct {
			Owner   int32 `xorm:"'card_m_id'"`
			SuitMId int32 `xorm:"'suit_m_id'"`
		}
		err = batchRows(session.Table("m_training_tree_card_suit").Where("card_m_id IN (SELECT id FROM m_training_tree)").OrderBy("card_m_id, training_content_no"), new(suitRow), func(_ int, bean interface{}) error {
			row := bean.(*suitRow)
			if tree := gamedata.TrainingTree[row.Owner]; tree != nil {
				tree.SuitMIds = append(tree.SuitMIds, row.SuitMId)
			}
			return nil
		})
		if err != nil {
			return
		}
		type voiceRow struct {
			Owner        int32 `xorm:"'card_m_id'"`
			NaviActionId int32 `xorm:"'navi_action_id'"`
		}
		err = batchRows(session.Table("m_training_tree_card_voice").Where("card_m_id IN (SELECT id FROM m_training_tree)").OrderBy("card_m_id, training_content_no"), new(voiceRow), func(_ int, bean interface{}) error {
			row := bean.(*voiceRow)
			if tree := gamedata.TrainingTree[row.Owner]; tree != nil {
				tree.NaviActionIds = append(tree.NaviActionIds, row.NaviActionId)
			}
			return nil
		})
		if err != nil {
			return
		}
		type rewardRow struct {
			Owner                      int32 `xorm:"'card_master_id'"`
			TrainingTreeProgressReward `xorm:"extends"`
		}
		err = batchRows(session.Table("m_training_tree_progress_reward").Where("card_master_id IN (SELECT id FROM m_training_tree)").OrderBy("card_master_id, activate_num, display_order"), new(rewardRow), func(_ int, bean interface{}) error {
			row := bean.(*rewardRow)
			if tree := gamedata.TrainingTree[row.Owner]; tree != nil {
				tree.TrainingTreeProgressRewards = append(tree.TrainingTreeProgressRewards, row.TrainingTreeProgressReward)
			}
			return nil
		})
		loaded = err == nil
	})
	return
}

func loadTrainingMappingDetails(gamedata *Gamedata) (loaded bool, err error) {
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		var safe bool
		safe, err = batchReadOrderSafe(session, "m_training_tree_cell_content", []string{"id", "cell_id"}, []string{"id", "training_tree_cell_type", "training_content_no"})
		if err != nil || !safe {
			return
		}
		owners := make(map[int32][]*TrainingTreeMapping)
		for _, mapping := range gamedata.TrainingTreeMapping {
			owners[mapping.TrainingTreeCellContentMId] = append(owners[mapping.TrainingTreeCellContentMId], mapping)
		}
		type cellRow struct {
			Owner                   int32 `xorm:"'id'"`
			TrainingTreeCellContent `xorm:"extends"`
		}
		err = batchRows(session.Table("m_training_tree_cell_content").Where("id IN (SELECT training_tree_cell_content_m_id FROM m_training_tree_mapping)").OrderBy("id, cell_id"), new(cellRow), func(_ int, bean interface{}) error {
			row := bean.(*cellRow)
			for _, mapping := range owners[row.Owner] {
				mapping.TrainingTreeCellContents = append(mapping.TrainingTreeCellContents, row.TrainingTreeCellContent)
			}
			return nil
		})
		loaded = err == nil
	})
	return
}

func loadStoryMemberRewards(gamedata *Gamedata) (loaded bool, err error) {
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		var safe bool
		safe, err = batchReadOrderSafe(session, "m_story_member_rewards", []string{"story_member_master_id", "content_type", "content_id"})
		if err != nil || !safe {
			return
		}
		type rewardRow struct {
			Owner          int32 `xorm:"'story_member_master_id'"`
			client.Content `xorm:"extends"`
		}
		err = batchRows(session.Table("m_story_member_rewards").Where("story_member_master_id IN (SELECT id FROM m_story_member)").OrderBy("story_member_master_id, content_type, content_id"), new(rewardRow), func(_ int, bean interface{}) error {
			row := bean.(*rewardRow)
			if story := gamedata.StoryMember[row.Owner]; story != nil && story.Reward == nil {
				reward := row.Content
				story.Reward = &reward
			}
			return nil
		})
		loaded = err == nil
	})
	return
}
