package gamedata

import (
	"elichika/client"
	"elichika/generic/drop"
	"elichika/log"
	"elichika/utils"

	"xorm.io/xorm"
)

type LessonMenu struct {
	// from m_lesson_menu
	Id int32 `xorm:"pk"`
	// PassiveSkillDropGroupId int32
	// Name string
	// ThumbnailMAssetPath string
	// ThumbnailSAssetPath string
	// BackgroundImagePath string
	// BgmPath string
	DefaultDrop *drop.WeightedDropList[client.LessonDropItem]           `xorm:"-"`
	Drop        map[int32]*drop.WeightedDropList[client.LessonDropItem] `xorm:"-"`
}

func (lm *LessonMenu) populate(gamedata *Gamedata) {

	type LessonDropContent struct {
		ContentType   int32
		ContentId     int32
		ContentAmount int32
		Weight        int32
		Rarity        int32
	}

	contents := []LessonDropContent{}
	var err error
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_drop_content").Where("lesson_menu_master_id == ?", lm.Id).Find(&contents)
	})
	utils.CheckErr(err)
	lm.DefaultDrop = &drop.WeightedDropList[client.LessonDropItem]{}
	for _, content := range contents {
		lm.DefaultDrop.AddItem(client.LessonDropItem{
			ContentType:   content.ContentType,
			ContentId:     content.ContentId,
			ContentAmount: content.ContentAmount,
			DropRarity:    content.Rarity,
		}, content.Weight)
	}

	type LessonEnhancingItemDropRate struct {
		LessonEnhancingItemId int32
		TargetRarity          int32
		MagnificationWeight   int32
	}
	enhancingItems := []LessonEnhancingItemDropRate{}
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_enhancing_item_effect_drop_rate").Find(&enhancingItems)
	})
	utils.CheckErr(err)
	// The table gives a magnification per rarity, out of 10000, and the list built here
	// REPLACES the default one while the item is in use. So every drop has to be carried
	// over, with only the mentioned rarities scaled: a rarity the item says nothing about
	// keeps its ordinary weight rather than disappearing from the drop table.
	//
	// Keeping only the mentioned rarities is what the code used to do, and it went
	// unnoticed because Lucky Charm *1 and *2 happen to mention all four rarities that
	// exist. Lucky Charm *3 does not mention rarity 3, so using it removed every rarity 3
	// drop, which on lesson menus 5 to 8 is the best rarity they have.
	//
	// It also means the list can never come out empty. An item whose rarities did not
	// overlap the menu's at all used to produce one, and drawing from it panics.
	magnification := map[int32]map[int32]int32{}
	for _, rate := range enhancingItems {
		if magnification[rate.LessonEnhancingItemId] == nil {
			magnification[rate.LessonEnhancingItemId] = map[int32]int32{}
		}
		magnification[rate.LessonEnhancingItemId][rate.TargetRarity] = rate.MagnificationWeight
	}

	lm.Drop = map[int32]*drop.WeightedDropList[client.LessonDropItem]{}
	for enhancingItemId, byRarity := range magnification {
		dropList := &drop.WeightedDropList[client.LessonDropItem]{}
		for _, content := range contents {
			weight := content.Weight
			if mag, scaled := byRarity[content.Rarity]; scaled {
				weight = content.Weight * mag / 10000
			}
			dropList.AddItem(client.LessonDropItem{
				ContentType:   content.ContentType,
				ContentId:     content.ContentId,
				ContentAmount: content.ContentAmount,
				DropRarity:    content.Rarity,
			}, weight)
		}
		lm.Drop[enhancingItemId] = dropList
	}
}

func loadLessonMenu(gamedata *Gamedata) {
	log.Println("Loading LessonMenu")
	gamedata.LessonMenu = make(map[int32]*LessonMenu)
	var err error
	gamedata.MasterdataDb.Do(func(session *xorm.Session) {
		err = session.Table("m_lesson_menu").Find(&gamedata.LessonMenu)
	})
	utils.CheckErr(err)
	for _, lessonMenu := range gamedata.LessonMenu {
		lessonMenu.populate(gamedata)
	}
}

func init() {
	addLoadFunc(loadLessonMenu)
}
