package user_lesson

import (
	"elichika/client"
	"elichika/enum"
	"elichika/generic"
	"elichika/generic/drop"
	"elichika/log"
	"elichika/userdata"
	"elichika/utils"
	"reflect"
)

func lessonSkillGuideIncomplete(session *userdata.Session) bool {
	// Ordinary gameplay sessions do not populate every UserModel table. A tip saved
	// earlier in this request wins; otherwise read the persisted completion marker.
	if session.UserModel.UserSceneTipsByEnum.GetOnly(enum.SceneTipsTypeLesson) != nil {
		return false
	}
	exists, err := session.Db.Table("u_scene_tips").Where("user_id = ? AND scene_tips_type = ?",
		session.UserId, enum.SceneTipsTypeLesson).Exist()
	utils.CheckErr(err)
	return !exists
}

func firstLessonCompatibilitySkill(session *userdata.Session, deck client.UserLessonDeck,
	pool *drop.WeightedDropList[int32]) client.LessonResultDropPassiveSkill {
	lesson := session.Gamedata.Lesson
	if lesson == nil || !lesson.IsLoaded || pool == nil {
		log.Panic("first lesson skill guide requires valid ordinary skill metadata; update the asset repository")
	}
	positions := &drop.WeightedDropList[int32]{}
	totalWeight := int64(0)
	for position := int32(1); position <= 9; position++ {
		weight := lesson.SkillPositionWeight[position]
		if weight <= 0 {
			continue
		}
		// The result must be actionable on an owned card with an insight-skill slot.
		cardMasterId := reflect.ValueOf(deck).Field(int(position) + 1).Interface().(generic.Nullable[int32])
		if !cardMasterId.HasValue || cardMasterId.Value <= 0 || session.Gamedata.Card[cardMasterId.Value] == nil ||
			session.Gamedata.Card[cardMasterId.Value].MaxPassiveSkillSlot <= 0 {
			continue
		}
		card := session.UserModel.UserCardByCardId.GetOnly(cardMasterId.Value)
		if card == nil {
			loaded := client.UserCard{}
			exists, err := session.Db.Table("u_card").Where("user_id = ? AND card_master_id = ?",
				session.UserId, cardMasterId.Value).Cols("card_master_id", "max_free_passive_skill").Get(&loaded)
			utils.CheckErr(err)
			if !exists {
				continue
			}
			card = &loaded
		}
		if card.MaxFreePassiveSkill <= 0 {
			continue
		}
		totalWeight += int64(weight)
		if totalWeight > 1<<31-1 {
			log.Panic("first lesson skill guide has overflowing deck-position weights")
		}
		positions.AddItem(position, weight)
	}
	if totalWeight == 0 {
		log.Panic("first lesson skill guide requires an owned lesson-deck card with an insight-skill slot")
	}
	skillId := pool.GetRandomItem()
	if skillId <= 0 || lesson.SkillRarity[skillId] < enum.SkillRarityTypeSkillRankD ||
		lesson.SkillRarity[skillId] > enum.SkillRarityTypeSkillRankS {
		log.Panic("first lesson skill guide has invalid ordinary skill metadata")
	}
	return client.LessonResultDropPassiveSkill{Position: positions.GetRandomItem(), PassiveSkillId: skillId}
}
