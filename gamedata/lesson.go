package gamedata

import (
	"elichika/enum"
	"elichika/generic/drop"
	"elichika/log"
	"elichika/utils"
	"fmt"
	"math"

	"xorm.io/xorm"
)

// The lesson drop rates are not part of the game's own masterdata: the real server never
// shipped them to the client. They were recovered by observing several million real lesson
// results (see https://github.com/eman1can/SIFAS-Lesson-Data) and the asset repository
// provides them as 5 extra tables:
//   - m_lesson_drop_amount        how many items a lesson menu run gives
//   - m_lesson_skill_content      which insight skill can drop from which lesson combination
//   - m_lesson_skill_rarity       the mix of rarities, given that a skill drops
//   - m_lesson_skill_no_drop      how often no skill drops at all
//   - m_lesson_skill_member_chance which of the 9 deck positions receives the skill
//
// An asset repository that predates these tables is still usable: IsLoaded stays false,
// the caller keeps its built in drop amounts and no insight skill is dropped.
// The optional m_lesson_skill_shooting_star table identifies special animations; its
// absence does not affect drops from the five tables above.
//
// The ordinary rates themselves are data: how strict or generous lessons are is decided
// by the weights in those tables. The caller makes a narrow compatibility exception for
// an empty result while the original client's first skill guide is incomplete; this is
// a private-server compatibility policy, not a claim about the original service's rates.
// The sql file that creates the tables records where
// each number came from and which ones were a judgement call rather than an observation,
// so read that before changing any of them here.
type Lesson struct {
	// keyed by enum.LessonDropTypeNormal / enum.LessonDropTypeMegaphone
	ItemAmount map[int32]*drop.WeightedDropList[int32]

	// keyed by the 3 lesson menu ids as id1 * 100 + id2 * 10 + id3, a drop of 0 means
	// the run gives no skill at all
	SkillDrop   map[int32]*drop.WeightedDropList[int32]
	SkillRarity map[int32]int32

	// Compatibility draws for the original client's first insight-skill guide. These
	// keep the ordinary positive weights, but omit no-drop and shooting-star entries.
	FirstSkillDrop map[int32]*drop.WeightedDropList[int32]
	// Old pending results do not store their recipe. Only an any-combination skill
	// with no shooting-star mapping anywhere is safe to add to such a result.
	FirstSkillLegacyDrop *drop.WeightedDropList[int32]
	SkillPositionWeight  map[int32]int32

	// keyed by lesson combination, then insight skill master id; value is the menu id
	// that caused the skill to be available
	SkillSourceMenu map[int32]map[int32]int32

	// keyed by lesson combination, then insight skill master id. This is separate from
	// SkillSourceMenu: an ordinary skill available from any menu also has source id 0.
	ShootingStarSkills map[int32]map[int32]bool

	// which of the 9 deck positions receives the skill
	SkillPosition *drop.WeightedDropList[int32]

	// the insight pins guarantee the leader a skill of at least a given rarity, keyed by
	// lesson enhancing item id. Empty if masterdata has no such item.
	EnhancingItemSkillRarity map[int32]int32

	// the guaranteed draws those pins use: minimum rarity, then the combination key. Only
	// the rarities some pin actually asks for are built, and a combination is absent when
	// it offers nothing of that rarity or better.
	GuaranteedSkillDrop map[int32]map[int32]*drop.WeightedDropList[int32]

	IsLoaded bool
}

// the drop type of a row of m_lesson_skill_content, it decides which lesson combinations
// the skill can drop from
const (
	lessonSkillDropTypePure     int32 = 1 // all 3 lessons are LessonMenuId1
	lessonSkillDropTypeMixed    int32 = 2 // at least one lesson is LessonMenuId1
	lessonSkillDropTypeAny      int32 = 3 // any combination
	lessonSkillDropTypeMajority int32 = 4 // LessonMenuId1 twice and LessonMenuId2 once, in any order
)

type lessonSkillContent struct {
	SkillMasterId int32
	Rarity        int32
	DropType      int32
	LessonMenuId1 int32
	LessonMenuId2 int32
}

// whether the skill can drop from the given lesson menu combination
func (skill *lessonSkillContent) canDropFrom(id1, id2, id3 int32) bool {
	switch skill.DropType {
	case lessonSkillDropTypePure:
		return skill.LessonMenuId1 == id1 && id1 == id2 && id2 == id3
	case lessonSkillDropTypeMixed:
		return skill.LessonMenuId1 == id1 || skill.LessonMenuId1 == id2 || skill.LessonMenuId1 == id3
	case lessonSkillDropTypeAny:
		return true
	case lessonSkillDropTypeMajority:
		return (skill.LessonMenuId1 == id1 && id1 == id2 && skill.LessonMenuId2 == id3) ||
			(skill.LessonMenuId1 == id1 && skill.LessonMenuId2 == id2 && id1 == id3) ||
			(skill.LessonMenuId2 == id1 && id2 == id3 && skill.LessonMenuId1 == id3)
	default:
		// there is no other drop type in the data, ignore the row instead of guessing
		return false
	}
}

// whether the skill is exclusive to the combinations it drops from, rather than being on
// offer to any combination that merely contains its lesson. A combination that has one of
// these on offer drops a skill much more often: 84% against 63%.
func (skill *lessonSkillContent) isExclusive() bool {
	return skill.DropType == lessonSkillDropTypePure || skill.DropType == lessonSkillDropTypeMajority
}

// the tables this loader needs, all of them are provided by the asset repository
var lessonTables = []string{
	"m_lesson_drop_amount",
	"m_lesson_skill_content",
	"m_lesson_skill_rarity",
	"m_lesson_skill_no_drop",
	"m_lesson_skill_member_chance",
}

// the tables the masterdata actually has
func existingTables(gamedata *Gamedata) map[string]bool {
	existing := map[string]bool{}
	var rows []map[string]string
	var err error
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		rows, err = session.QueryString("SELECT name FROM sqlite_master WHERE type = 'table'")
	})
	utils.CheckErr(err)
	for _, row := range rows {
		existing[row["name"]] = true
	}
	return existing
}

// report the tables of lessonTables that the masterdata doesn't have
func missingLessonTables(gamedata *Gamedata) []string {
	existing := existingTables(gamedata)
	missing := []string{}
	for _, table := range lessonTables {
		if !existing[table] {
			missing = append(missing, table)
		}
	}
	return missing
}

// fill the drop lists, reporting whether the tables held everything that is needed:
// they can exist but be empty, and the caller must not end up with an empty drop list
func (lesson *Lesson) populate(gamedata *Gamedata) bool {
	var err error

	// how many items a lesson menu run drops, and how many megaphones each lesson drops
	type lessonDropAmount struct {
		ItemId int32
		Count  int32
		Weight int32
	}
	var dropAmounts []lessonDropAmount
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_drop_amount").Find(&dropAmounts)
	})
	utils.CheckErr(err)
	lesson.ItemAmount = map[int32]*drop.WeightedDropList[int32]{}
	for _, dropAmount := range dropAmounts {
		if lesson.ItemAmount[dropAmount.ItemId] == nil {
			lesson.ItemAmount[dropAmount.ItemId] = &drop.WeightedDropList[int32]{}
		}
		lesson.ItemAmount[dropAmount.ItemId].AddItem(dropAmount.Count, dropAmount.Weight)
	}

	// which position of the deck the skill is given to
	type lessonSkillMemberChance struct {
		PositionId int32
		Weight     int32
	}
	var memberChances []lessonSkillMemberChance
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_skill_member_chance").Find(&memberChances)
	})
	utils.CheckErr(err)
	lesson.SkillPosition = &drop.WeightedDropList[int32]{}
	lesson.SkillPositionWeight = map[int32]int32{}
	for _, memberChance := range memberChances {
		lesson.SkillPosition.AddItem(memberChance.PositionId, memberChance.Weight)
		if memberChance.PositionId >= 1 && memberChance.PositionId <= 9 && memberChance.Weight > 0 {
			lesson.SkillPositionWeight[memberChance.PositionId] = memberChance.Weight
		}
	}

	// the mix of rarities, given that a skill drops at all
	type lessonSkillRarity struct {
		Rarity int32
		Weight int32
	}
	var skillRarities []lessonSkillRarity
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_skill_rarity").Find(&skillRarities)
	})
	utils.CheckErr(err)

	// A recovered reward row alone does not prove that the original client knows its
	// ID. Missing stock metadata leaves compatibility pools unavailable, rather than
	// fabricating a skill when an owner's custom tables cannot support the guide.
	knownSkills := map[int32]bool{}
	if existingTables(gamedata)["m_passive_skill"] {
		var skillIds []int32
		gamedata.MasterdataDb.Do(func(session *xorm.Session) {
			err = session.Table("m_passive_skill").Cols("id").Find(&skillIds)
		})
		utils.CheckErr(err)
		for _, skillId := range skillIds {
			knownSkills[skillId] = true
		}
	}
	rarityWeight := map[int32]int32{}
	for _, skillRarity := range skillRarities {
		rarityWeight[skillRarity.Rarity] = skillRarity.Weight
	}

	// how often no skill drops at all, which depends only on whether the combination has
	// an exclusive skill on offer
	type lessonSkillNoDrop struct {
		HasExclusive int32
		Weight       int32
	}
	var noDrops []lessonSkillNoDrop
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_skill_no_drop").Find(&noDrops)
	})
	utils.CheckErr(err)
	noDropWeight := map[int32]int32{}
	for _, noDrop := range noDrops {
		noDropWeight[noDrop.HasExclusive] = noDrop.Weight
	}

	var skills []lessonSkillContent
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_skill_content").Find(&skills)
	})
	utils.CheckErr(err)

	type lessonSkillShootingStar struct {
		// Read SQLite integers at their full width: xorm silently truncates an
		// overflowing int32 instead of returning a scan error.
		SkillMasterId int64
		LessonMenuId  int64
	}
	var shootingStarRows []lessonSkillShootingStar
	// Animation metadata is optional. An older asset repository must still retain its
	// recovered drop rates and insight skills when this newer table is absent or a
	// preserved custom schema cannot be read. Never use partially scanned metadata.
	if existingTables(gamedata)["m_lesson_skill_shooting_star"] {
		gamedata.MasterdataDb.Do(func(session *xorm.Session) {
			err = session.Table("m_lesson_skill_shooting_star").Find(&shootingStarRows)
		})
		if err == nil {
			for _, row := range shootingStarRows {
				if row.SkillMasterId < math.MinInt32 || row.SkillMasterId > math.MaxInt32 || row.LessonMenuId < math.MinInt32 || row.LessonMenuId > math.MaxInt32 {
					err = fmt.Errorf("animation IDs exceed int32 range: skill %d, menu %d", row.SkillMasterId, row.LessonMenuId)
					break
				}
			}
		}
		if err != nil {
			log.Println("WARNING: Shooting Star animation metadata could not be loaded; using ordinary lesson animations: ", err)
			shootingStarRows = nil
		}
	}
	shootingStarByMenu := map[int32]map[int32]bool{}
	for _, row := range shootingStarRows {
		menuID, skillID := int32(row.LessonMenuId), int32(row.SkillMasterId)
		if shootingStarByMenu[menuID] == nil {
			shootingStarByMenu[menuID] = map[int32]bool{}
		}
		shootingStarByMenu[menuID][skillID] = true
	}
	shootingStarAnyMenu := map[int32]bool{}
	for _, row := range shootingStarRows {
		shootingStarAnyMenu[int32(row.SkillMasterId)] = true
	}

	// The insight pins (m_lesson_enhancing_item 1400 / 1401) guarantee the leader a skill.
	// This is stock masterdata rather than one of the recovered tables, but it is read
	// optionally: without it the pins simply grant nothing extra, which is better than
	// disabling every skill drop.
	lesson.EnhancingItemSkillRarity = map[int32]int32{}
	if existingTables(gamedata)["m_lesson_enhancing_item_effect_skill_drop"] {
		type lessonEnhancingItemSkillDrop struct {
			LessonEnhancingItemId int32
			TargetSkillRarity     int32
		}
		var pins []lessonEnhancingItemSkillDrop
		gamedata.MasterdataDb.Do(func(session *xorm.Session) {
			err = session.Table("m_lesson_enhancing_item_effect_skill_drop").Find(&pins)
		})
		utils.CheckErr(err)
		for _, pin := range pins {
			lesson.EnhancingItemSkillRarity[pin.LessonEnhancingItemId] = pin.TargetSkillRarity
		}
	}

	// only build a guaranteed list for a rarity some pin actually asks for
	lesson.SkillRarity = map[int32]int32{}
	for _, skill := range skills {
		lesson.SkillRarity[skill.SkillMasterId] = skill.Rarity
	}

	guaranteedRarities := map[int32]bool{}
	for _, rarity := range lesson.EnhancingItemSkillRarity {
		guaranteedRarities[rarity] = true
	}
	lesson.GuaranteedSkillDrop = map[int32]map[int32]*drop.WeightedDropList[int32]{}
	for rarity := range guaranteedRarities {
		lesson.GuaranteedSkillDrop[rarity] = map[int32]*drop.WeightedDropList[int32]{}
	}

	// the lesson menu ids that actually exist, instead of assuming the usual 1 to 8
	var menuIds []int32
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_menu").Cols("id").Find(&menuIds)
	})
	utils.CheckErr(err)

	// A run draws one skill out of every skill the combination can give, plus a "no skill"
	// entry. A rarity's weight is shared between all the skills of that rarity that the
	// combination can give, so the chance of getting *some* skill of a rarity doesn't
	// depend on how many skills of that rarity exist.
	//
	// The "no skill" weight is the only thing that varies between combinations: one that
	// has an exclusive skill on offer drops a skill far more often than one that doesn't.
	lesson.SkillDrop = map[int32]*drop.WeightedDropList[int32]{}
	lesson.FirstSkillDrop = map[int32]*drop.WeightedDropList[int32]{}
	lesson.SkillSourceMenu = map[int32]map[int32]int32{}
	lesson.ShootingStarSkills = map[int32]map[int32]bool{}
	for _, id1 := range menuIds {
		for _, id2 := range menuIds {
			for _, id3 := range menuIds {
				available := []*lessonSkillContent{}
				countByRarity := map[int32]int32{}
				hasExclusive := int32(0)
				for i := range skills {
					if skills[i].canDropFrom(id1, id2, id3) {
						available = append(available, &skills[i])
						countByRarity[skills[i].Rarity]++
						if skills[i].isExclusive() {
							hasExclusive = 1
						}
					}
				}

				dropList := &drop.WeightedDropList[int32]{}
				totalDropWeight := int64(noDropWeight[hasExclusive])
				if totalDropWeight < 0 {
					log.Panic("lesson skill no-drop weight must not be negative")
				}
				dropList.AddItem(0, noDropWeight[hasExclusive])
				for _, skill := range available {
					weight := rarityWeight[skill.Rarity] / countByRarity[skill.Rarity]
					totalDropWeight += int64(weight)
					if weight < 0 || totalDropWeight > math.MaxInt32 {
						log.Panic("lesson skill weights must be nonnegative and total at most MaxInt32")
					}
					dropList.AddItem(skill.SkillMasterId, weight)
				}

				combination := id1*100 + id2*10 + id3
				lesson.SkillDrop[combination] = dropList
				lesson.SkillSourceMenu[combination] = map[int32]int32{}
				lesson.ShootingStarSkills[combination] = map[int32]bool{}
				for _, skill := range available {
					lesson.SkillSourceMenu[combination][skill.SkillMasterId] = skill.LessonMenuId1
					for _, lessonMenuId := range []int32{id1, id2, id3} {
						if shootingStarByMenu[lessonMenuId][skill.SkillMasterId] {
							lesson.ShootingStarSkills[combination][skill.SkillMasterId] = true
							break
						}
					}
				}

				ordinary := &drop.WeightedDropList[int32]{}
				ordinaryWeight := int64(0)
				for _, skill := range available {
					weight := rarityWeight[skill.Rarity] / countByRarity[skill.Rarity]
					sourceValid := skill.LessonMenuId1 == 0 || skill.LessonMenuId1 == id1 ||
						skill.LessonMenuId1 == id2 || skill.LessonMenuId1 == id3
					if weight <= 0 || !knownSkills[skill.SkillMasterId] || skill.SkillMasterId <= 0 ||
						skill.Rarity < enum.SkillRarityTypeSkillRankD || skill.Rarity > enum.SkillRarityTypeSkillRankS ||
						!sourceValid || lesson.ShootingStarSkills[combination][skill.SkillMasterId] {
						continue
					}
					ordinaryWeight += int64(weight)
					if ordinaryWeight > math.MaxInt32 {
						log.Panic("first lesson skill guide has overflowing skill weights")
					}
					ordinary.AddItem(skill.SkillMasterId, weight)
				}
				if ordinaryWeight > 0 {
					lesson.FirstSkillDrop[combination] = ordinary
				}
				// A pin drops a skill of its target rarity *or better*, never nothing, so
				// its list has no "no skill" entry and only the eligible rarities. The
				// weights are the same ones, so the mix between those rarities is kept.
				for rarity := range guaranteedRarities {
					guaranteed := &drop.WeightedDropList[int32]{}
					total := int32(0)
					for _, skill := range available {
						if skill.Rarity < rarity {
							continue
						}
						weight := rarityWeight[skill.Rarity] / countByRarity[skill.Rarity]
						guaranteed.AddItem(skill.SkillMasterId, weight)
						total += weight
					}
					// a combination with nothing that good is left out, and the caller
					// falls back to the ordinary draw rather than drawing from nothing
					if total > 0 {
						lesson.GuaranteedSkillDrop[rarity][combination] = guaranteed
					}
				}
			}
		}
	}

	// For a resumed result, the recipe and its rarity denominators are unknown. Use
	// only skills eligible for every recipe, sharing each positive rarity weight
	// between its universally eligible ordinary skills.
	legacyCountByRarity := map[int32]int32{}
	for _, skill := range skills {
		if skill.DropType == lessonSkillDropTypeAny && skill.LessonMenuId1 == 0 && skill.LessonMenuId2 == 0 &&
			skill.SkillMasterId > 0 && knownSkills[skill.SkillMasterId] &&
			skill.Rarity >= enum.SkillRarityTypeSkillRankD && skill.Rarity <= enum.SkillRarityTypeSkillRankS &&
			!shootingStarAnyMenu[skill.SkillMasterId] && rarityWeight[skill.Rarity] > 0 {
			legacyCountByRarity[skill.Rarity]++
		}
	}
	legacy := &drop.WeightedDropList[int32]{}
	legacyWeight := int64(0)
	for _, skill := range skills {
		count := legacyCountByRarity[skill.Rarity]
		if count == 0 || skill.DropType != lessonSkillDropTypeAny || skill.SkillMasterId <= 0 ||
			skill.LessonMenuId1 != 0 || skill.LessonMenuId2 != 0 || !knownSkills[skill.SkillMasterId] || shootingStarAnyMenu[skill.SkillMasterId] {
			continue
		}
		weight := rarityWeight[skill.Rarity] / count
		if weight > 0 {
			legacyWeight += int64(weight)
			if legacyWeight > math.MaxInt32 {
				log.Panic("first lesson skill guide has overflowing legacy skill weights")
			}
			legacy.AddItem(skill.SkillMasterId, weight)
		}
	}
	if legacyWeight > 0 {
		lesson.FirstSkillLegacyDrop = legacy
	}

	_, hasCommonNoDrop := noDropWeight[0]
	_, hasExclusiveNoDrop := noDropWeight[1]
	return lesson.ItemAmount[enum.LessonDropTypeNormal] != nil &&
		lesson.ItemAmount[enum.LessonDropTypeMegaphone] != nil &&
		hasCommonNoDrop && hasExclusiveNoDrop &&
		len(memberChances) > 0 && len(skills) > 0 && len(menuIds) > 0
}

func loadLesson(gamedata *Gamedata) {
	log.Println("Loading Lesson")
	lesson := Lesson{}
	missing := missingLessonTables(gamedata)
	if len(missing) == 0 {
		lesson.IsLoaded = lesson.populate(gamedata)
		if !lesson.IsLoaded {
			log.Println("Lesson drop tables are present but incomplete.")
		}
	} else {
		log.Println("Lesson drop tables missing from masterdata:", missing)
	}
	if !lesson.IsLoaded {
		log.Println("Lessons will use the built-in drop amounts and will not drop insight skills.")
		log.Println("Reset the asset repository so the sql migrations run again to get them.")
	}
	gamedata.Lesson = &lesson
}

func init() {
	addLoadFunc(loadLesson)
}
