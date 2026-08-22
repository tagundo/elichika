package user_lesson

import (
	"elichika/client"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/config"
	"elichika/enum"
	"elichika/generic"
	"elichika/generic/drop"
	"elichika/item"
	"elichika/subsystem/user_content"
	"elichika/subsystem/user_lesson_deck"
	"elichika/subsystem/user_mission"
	"elichika/subsystem/user_status"
	"elichika/subsystem/user_subscription_status"
	"elichika/userdata"

	"math"
	"reflect"
	"sort"
)

// handle the lesson and write the result to the database
// drop is calculated using the following process:
// - First get a random drop count for the whole menu, then split it evenly between the 3 lessons
//   - the last lesson takes the remainder so the 3 parts add up to the rolled count
//
// - Then iterate over the lesson menu in the order sent, let's say A, B, C, and generate the items using a generic.random list.
//   - We pick the list based on whether the user has the training enhancing items requested
//
// - Finally there is a chance to add megaphones, if it's applicable.
// - For 3 times, the order of A B C is not preserved for the later runs, instead it's sorted
//   - Don't really know why this is the case
//   - One plausible theory is that they sorted the list to use it for insight skills as the order doesn't matter
//
// - the amount of drop is assumed to be the following per lesson menu run (3 in total for x3), start with 15 and go up to 26
//   - 0.25
//   - 0.08
//   - 0.08
//   - 0.25
//   - 0.08
//   - 0.08
//   - 0.11
//   - 0.01
//   - 0.01
//   - 0.03
//   - 0.01
//   - 0.01
//
// - the amount of megaphone drop is assumed to be the following per instance of lesson menu, starting with 0, end with 3
//   - 0.81
//   - 0.1
//   - 0.075
//   - 0.015
//
// TODO(hard_coded): Maybe this should be in the database
var (
	dropCountList          drop.WeightedDropList[int32]
	megaphoneDropCountList drop.WeightedDropList[int32]
)

func init() {
	dropCountList.AddItem(15, 25)
	dropCountList.AddItem(16, 8)
	dropCountList.AddItem(17, 8)
	dropCountList.AddItem(18, 25)
	dropCountList.AddItem(19, 8)
	dropCountList.AddItem(20, 8)
	dropCountList.AddItem(21, 11)
	dropCountList.AddItem(22, 1)
	dropCountList.AddItem(23, 1)
	dropCountList.AddItem(24, 3)
	dropCountList.AddItem(25, 1)
	dropCountList.AddItem(26, 1)

	megaphoneDropCountList.AddItem(0, 810)
	megaphoneDropCountList.AddItem(1, 100)
	megaphoneDropCountList.AddItem(2, 75)
	megaphoneDropCountList.AddItem(3, 15)
}

// the deck position the insight pins hand their guaranteed skill to
const lessonLeaderPosition int32 = 1

func ExecuteLesson(session *userdata.Session, req request.ExecuteLessonRequest) response.ExecuteLessonResponse {
	resp := response.ExecuteLessonResponse{
		UserModelDiff: &session.UserModel,
	}

	result := response.LessonResultResponse{
		SelectedDeckId: req.SelectedDeckId,
	}

	deck := user_lesson_deck.GetUserLessonDeck(session, req.SelectedDeckId)
	repeatCount := int32(1)
	if req.IsThreeTimes {
		repeatCount = 3
	}
	if config.Conf.ResourceConfig().ConsumeAp {
		user_status.AddUserAp(session, -repeatCount)
	}
	// update mission progress
	user_mission.UpdateProgress(session, enum.MissionClearConditionTypeCountLesson, nil, nil,
		func(session *userdata.Session, missionList []any, _ ...any) {
			for _, mission := range missionList {
				user_mission.AddMissionProgress(session, mission, repeatCount)
			}
		})

	session.UserStatus.LessonResumeStatus = enum.TopPriorityProcessStatusLesson

	enhancingItems := map[int32]*client.Content{}

	for _, itemId := range req.ConsumedContentIds.Slice {
		item := user_content.GetUserContent(session, enum.ContentTypeLessonEnhancingItem, itemId)
		enhancingItems[itemId] = &item
	}

	resp.IsSubscription = user_subscription_status.HasSubscription(session)

	for lesson := int32(1); lesson <= 4; lesson++ {
		actions := generic.List[client.LessonMenuAction]{}
		for i := 1; i <= 9; i++ {
			cardMasterId := reflect.ValueOf(deck).Field(i + 1).Interface().(generic.Nullable[int32]).Value
			actions.Append(client.LessonMenuAction{
				CardMasterId: cardMasterId,
				Position:     int32(i),
			})
		}
		resp.LessonMenuActions.Set(lesson%4, actions)
		resp.LessonDropRarityList.Set(lesson%4, generic.List[int32]{})
	}

	// the drop amounts come from masterdata when the asset repository provides the lesson
	// drop tables, the built-in lists above are the fallback for an older asset repository
	lessonGamedata := session.Gamedata.Lesson
	markInsightSkill := func(position, skillMasterId int32) {
		if position < 1 || position > 9 {
			return
		}
		rarity := lessonGamedata.SkillRarity[skillMasterId]
		for _, actions := range resp.LessonMenuActions.Map {
			action := &actions.Slice[position-1]
			action.IsAddedPassiveSkill = true
			action.UpCount++
			if rarity > 0 && (!action.MaxRarity.HasValue || rarity > action.MaxRarity.Value) {
				action.MaxRarity = generic.NewNullable(rarity)
			}
		}
	}
	rollDropCount := dropCountList.GetRandomItem
	rollMegaphoneCount := megaphoneDropCountList.GetRandomItem
	if lessonGamedata.IsLoaded {
		rollDropCount = lessonGamedata.ItemAmount[enum.LessonDropTypeNormal].GetRandomItem
		rollMegaphoneCount = lessonGamedata.ItemAmount[enum.LessonDropTypeMegaphone].GetRandomItem
	}

	for repeat := int32(1); repeat <= repeatCount; repeat++ {
		usedItems := []int32{}
		for _, itemId := range req.ConsumedContentIds.Slice {
			if enhancingItems[itemId].ContentAmount > 0 {
				enhancingItems[itemId].ContentAmount--
				usedItems = append(usedItems, itemId)
			}
		}

		// handle skill here if we want
		gainedItems := []client.LessonDropItem{}

		// the drop count is rolled once for the whole menu and then split evenly
		// between the 3 lessons, it is not rolled once per lesson.
		dropCount := rollDropCount()
		lessonDropCount := int32(math.Round(float64(dropCount) / 3.0))

		// use default drop, but switch to other drop if necessary

		for lesson := int32(1); lesson <= 3; lesson++ {
			lessonMenu := session.Gamedata.LessonMenu[req.ExecuteLessonIds.Slice[lesson-1]]
			dropList := lessonMenu.DefaultDrop
			for _, item := range usedItems {
				drop, exist := lessonMenu.Drop[item]
				if exist {
					dropList = drop
				}
			}

			// the last lesson takes the remainder so the 3 lessons add up to dropCount
			currentDropCount := lessonDropCount
			if lesson == 3 {
				currentDropCount = dropCount - lessonDropCount*2
			}
			gainedRarity := []int32{}
			// only the items of this lesson, the ones actually awarded below
			lessonItems := []client.LessonDropItem{}

			dropRarityList := resp.LessonDropRarityList.GetOnly(lesson)
			for i := int32(0); i < currentDropCount; i++ {
				drop := dropList.GetRandomItem()
				if drop.DropRarity > enum.LessonDropRarityTypeRare1 {
					gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare2)
				} else {
					gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare1)
				}
				lessonItems = append(lessonItems, drop)
			}

			// megaphone drop
			megaphoneDrop := rollMegaphoneCount()
			for i := int32(0); i < megaphoneDrop; i++ {
				lessonItems = append(lessonItems, client.LessonDropItem{
					ContentType:   item.RallyMegaphone.ContentType,
					ContentId:     item.RallyMegaphone.ContentId,
					ContentAmount: item.RallyMegaphone.ContentAmount,
					DropRarity:    4, // this field is not enum
				})
				gainedRarity = append(gainedRarity, enum.LessonDropRarityTypeRare2)
			}

			for _, content := range lessonItems {
				user_content.AddContent(session, client.Content{
					ContentType:   content.ContentType,
					ContentId:     content.ContentId,
					ContentAmount: content.ContentAmount,
				})
			}
			for _, rarity := range gainedRarity {
				dropRarityList.Append(rarity)
			}

			if resp.IsSubscription {
				for _, rarity := range gainedRarity {
					dropRarityList.Append(rarity)
				}
				for _, content := range lessonItems {
					user_content.AddContent(session, client.Content{
						ContentType:   content.ContentType,
						ContentId:     content.ContentId,
						ContentAmount: content.ContentAmount,
					})
				}
			}

			// roll this lesson's items into the response's drop list
			gainedItems = append(gainedItems, lessonItems...)
		}

		for _, drop := range gainedItems {
			result.DropItemList.Append(drop)
		}

		if resp.IsSubscription {
			for _, drop := range gainedItems {
				drop.IsSubscription = true
				result.DropItemList.Append(drop)
			}
		}

		// insight skills: one ordinary draw per run of the lesson menu, plus one more if an
		// insight pin was used. Which skills can drop depends on the combination of the 3
		// lessons, the order doesn't matter so the sort below has no effect on this.
		if lessonGamedata.IsLoaded {
			key := req.ExecuteLessonIds.Slice[0]*100 + req.ExecuteLessonIds.Slice[1]*10 + req.ExecuteLessonIds.Slice[2]

			// An insight pin guarantees the leader a skill of at least its target rarity.
			// Using several at once takes the best of them.
			guaranteedRarity := int32(0)
			for _, itemId := range usedItems {
				rarity, isPin := lessonGamedata.EnhancingItemSkillRarity[itemId]
				if isPin && rarity > guaranteedRarity {
					guaranteedRarity = rarity
				}
			}

			// the ordinary draw happens either way, at its weighted position
			if skillDrop, exist := lessonGamedata.SkillDrop[key]; exist {
				skillMasterId := skillDrop.GetRandomItem()
				if skillMasterId != 0 {
					position := lessonGamedata.SkillPosition.GetRandomItem()
					result.DropSkillList.Append(client.LessonResultDropPassiveSkill{
						Position:       position,
						PassiveSkillId: skillMasterId,
					})
					markInsightSkill(position, skillMasterId)
				}
			}

			// A pin adds one on top of that rather than replacing it, so a run using one
			// can hand back two skills. Its own is always for the leader. A combination
			// with nothing of the required rarity simply adds nothing.
			if guaranteedRarity > 0 {
				if guaranteed, exist := lessonGamedata.GuaranteedSkillDrop[guaranteedRarity][key]; exist {
					skillMasterId := guaranteed.GetRandomItem()
					result.DropSkillList.Append(client.LessonResultDropPassiveSkill{
						Position:       lessonLeaderPosition,
						PassiveSkillId: skillMasterId,
					})
					markInsightSkill(lessonLeaderPosition, skillMasterId)
				}
			}
		}

		if (repeat == 1) && (repeat < repeatCount) {
			sort.Slice(req.ExecuteLessonIds.Slice, func(i, j int) bool {
				return req.ExecuteLessonIds.Slice[i] < req.ExecuteLessonIds.Slice[j]
			})
		}
	}

	for _, item := range enhancingItems {
		user_content.UpdateUserContent(session, *item)
	}

	userdata.GenericDatabaseInsert(session, "u_lesson", result)

	return resp
}
