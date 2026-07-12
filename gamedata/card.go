package gamedata

import (
	"elichika/client"
	"elichika/log"
	"elichika/utils"

	"xorm.io/xorm"
)

/*
Assume the following result in the DB:
- SELECT * from m_card WHERE training_tree_m_id != id -> 0 record.
*/
type Card struct {
	// from m_card
	Id             int32   `xorm:"pk 'id'"`
	MemberMasterId *int32  `xorm:"'member_m_id'"`
	Member         *Member `xorm:"-"`
	// SchoolIdolNo int `xorm:"'school_idol_no'"`
	CardRarityType int32       `xorm:"'card_rarity_type'" enum:"CardRarityType"`
	Rarity         *CardRarity `xorm:"-"`
	Role           int32       `xorm:"'role'"`
	// MemberCardThumbnailAssetPath string
	// AtGacha bool
	// AtEvent bool
	TrainingTreeMasterId *int32        `xorm:"'training_tree_m_id'"` // must be equal to Id
	TrainingTree         *TrainingTree `xorm:"-"`
	// ActiveSkillVoicePath string
	// SpPoint int
	// ExchangeItemId int `xorm:"'exchange_item_id'"`
	// RoleEffectMasterId int `xorm:"'role_effect_master_id'"` // is just the same as role
	PassiveSkillSlot    int32 `xorm:"'passive_skill_slot'"`
	MaxPassiveSkillSlot int32 `xorm:"'max_passive_skill_slot'"`

	// from m_card_grade_up_item
	// map content_id to client.Content
	CardGradeUpItem map[int32](map[int32]client.Content) `xorm:"-"`
}

// cardGradeUpRow is m_card_grade_up_item as read in one bulk query (the per-card
// grade-up items, plus the owning card_id so we can group them in memory).
type cardGradeUpRow struct {
	CardId   int32          `xorm:"'card_id'"`
	Grade    int32          `xorm:"'grade'"`
	Resource client.Content `xorm:"extends"`
}

// populate fills the derived fields of a card. gradeUps is the card's own
// m_card_grade_up_item rows, pre-grouped by loadCard (see there).
func (card *Card) populate(gamedata *Gamedata, gradeUps []cardGradeUpRow) {
	card.Member = gamedata.Member[*card.MemberMasterId]
	card.MemberMasterId = &card.Member.Id
	card.TrainingTree = gamedata.TrainingTree[*card.TrainingTreeMasterId]
	card.TrainingTreeMasterId = &card.TrainingTree.Id
	card.Rarity = gamedata.CardRarity[card.CardRarityType]

	card.CardGradeUpItem = make(map[int32](map[int32]client.Content))
	for _, gradeUp := range gradeUps {
		_, exist := card.CardGradeUpItem[gradeUp.Grade]
		if !exist {
			card.CardGradeUpItem[gradeUp.Grade] = make(map[int32]client.Content)
		}
		card.CardGradeUpItem[gradeUp.Grade][gradeUp.Resource.ContentId] = gradeUp.Resource
	}

	gamedata.CardByMemberId[*card.MemberMasterId] = append(gamedata.CardByMemberId[*card.MemberMasterId], card)
}

func loadCard(gamedata *Gamedata) {
	log.Println("Loading Card")
	gamedata.Card = make(map[int32]*Card)
	var err error
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_card").Find(&gamedata.Card)
	})
	utils.CheckErr(err)
	gamedata.CardByMemberId = map[int32][]*Card{}

	// Read every grade-up item once and group by card_id, instead of running one
	// "WHERE card_id = ?" query per card. m_card_grade_up_item holds ~10 rows per
	// card, and the old per-card query was a serialized round-trip through the
	// single-goroutine MasterdataDb for each of the ~900 cards, on every locale.
	// Grouping preserves each card's row order, so the CardGradeUpItem maps built
	// below are identical to the old per-card path.
	rows := []cardGradeUpRow{}
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_card_grade_up_item").Find(&rows)
	})
	utils.CheckErr(err)
	gradeUpsByCard := make(map[int32][]cardGradeUpRow)
	for _, row := range rows {
		gradeUpsByCard[row.CardId] = append(gradeUpsByCard[row.CardId], row)
	}

	for _, card := range gamedata.Card {
		card.populate(gamedata, gradeUpsByCard[card.Id])
	}
}

func init() {
	addLoadFunc(loadCard)
	addPrequisite(loadCard, loadCardRarity)
	addPrequisite(loadCard, loadMember)
	addPrequisite(loadCard, loadTrainingTree)
}
