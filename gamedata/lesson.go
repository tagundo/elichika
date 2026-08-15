package gamedata

import (
	"elichika/enum"
	"elichika/generic/drop"
	"elichika/log"
	"elichika/utils"

	"xorm.io/xorm"
)

// The lesson drop rates are not part of the game's own masterdata: the real server never
// shipped them to the client. They were recovered by observing several million real lesson
// results (see https://github.com/eman1can/SIFAS-Lesson-Data) and the asset repository
// provides them as 4 extra tables:
//   - m_lesson_drop_amount        how many items a lesson menu run gives
//   - m_lesson_skill_content      which insight skill can drop from which lesson combination
//   - m_lesson_skill_rarity       the mix of rarities, given that a skill drops
//   - m_lesson_skill_no_drop      how often no skill drops at all
//   - m_lesson_skill_member_chance which of the 9 deck positions receives the skill
//
// An asset repository that predates these tables is still usable: IsLoaded stays false,
// the caller keeps its built in drop amounts and no insight skill is dropped.
//
// The rates themselves are data, not code: how strict or generous lessons are is decided
// entirely by the weights in those tables. The sql file that creates them records where
// each number came from and which ones were a judgement call rather than an observation,
// so read that before changing any of them here.
type Lesson struct {
	// keyed by enum.LessonDropTypeNormal / enum.LessonDropTypeMegaphone
	ItemAmount map[int32]*drop.WeightedDropList[int32]

	// keyed by the 3 lesson menu ids as id1 * 100 + id2 * 10 + id3, a drop of 0 means
	// the run gives no skill at all
	SkillDrop map[int32]*drop.WeightedDropList[int32]

	// which of the 9 deck positions receives the skill
	SkillPosition *drop.WeightedDropList[int32]

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

// report the tables of lessonTables that the masterdata doesn't have
func missingLessonTables(gamedata *Gamedata) []string {
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
	for _, memberChance := range memberChances {
		lesson.SkillPosition.AddItem(memberChance.PositionId, memberChance.Weight)
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
				dropList.AddItem(0, noDropWeight[hasExclusive])
				for _, skill := range available {
					dropList.AddItem(skill.SkillMasterId, rarityWeight[skill.Rarity]/countByRarity[skill.Rarity])
				}
				lesson.SkillDrop[id1*100+id2*10+id3] = dropList
			}
		}
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
