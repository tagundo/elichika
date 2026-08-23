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
	lm.Drop = map[int32]*drop.WeightedDropList[client.LessonDropItem]{}
	totalWeight := map[int32]int32{}
	for _, rate := range enhancingItems {
		if lm.Drop[rate.LessonEnhancingItemId] == nil {
			lm.Drop[rate.LessonEnhancingItemId] = &drop.WeightedDropList[client.LessonDropItem]{}
		}
		for _, content := range contents {
			if content.Rarity == rate.TargetRarity {
				weight := content.Weight * rate.MagnificationWeight / 10000
				lm.Drop[rate.LessonEnhancingItemId].AddItem(client.LessonDropItem{
					ContentType:   content.ContentType,
					ContentId:     content.ContentId,
					ContentAmount: content.ContentAmount,
					DropRarity:    content.Rarity,
				}, weight)
				totalWeight[rate.LessonEnhancingItemId] += weight
			}
		}
	}

	// A list of weight 0 cannot be drawn from: GetRandomItem asks rand.Int31n for a
	// number below 0 and panics, taking the server down mid lesson. The stock data
	// never builds one, because the only item here targets every rarity the menus
	// drop, but edited masterdata can: an item that targets a rarity this menu has
	// none of, or weights that all truncate away. Leaving those out makes the menu
	// fall back to its default drop, which is what an item with no effect should do.
	// ranging over lm.Drop rather than totalWeight on purpose: an item whose rarities
	// miss this menu entirely never reaches the accumulator at all, and that is exactly
	// the case that used to panic. Deleting during a range is defined behaviour.
	for itemId := range lm.Drop {
		if totalWeight[itemId] == 0 {
			delete(lm.Drop, itemId)
		}
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
