package user_lesson

import (
	"elichika/client"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/config"
	"elichika/enum"
	"elichika/gamedata"
	"elichika/generic"
	"elichika/generic/drop"
	"elichika/userdata"
	"encoding/json"
	"reflect"
	"testing"

	"xorm.io/xorm"
)

func singleLessonDrop(value int32) *drop.WeightedDropList[int32] {
	list := &drop.WeightedDropList[int32]{}
	list.AddItem(value, 1)
	return list
}

func executeLessonFixture(t *testing.T, ordinarySkill, pinSkill, sourceMenu, position int32,
	stars map[int32]bool, threeTimes bool, configure ...func(*userdata.Session, *request.ExecuteLessonRequest)) (response.ExecuteLessonResponse, response.LessonResultResponse) {
	t.Helper()
	engine, err := xorm.NewEngine("sqlite", t.TempDir()+"/userdata.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { engine.Close() })
	for _, statement := range []string{
		`CREATE TABLE u_beginner_challenge_cell (user_id INTEGER, cell_id INTEGER, is_reward_received INTEGER, progress INTEGER)`,
		`CREATE TABLE u_lesson (user_id INTEGER PRIMARY KEY, selected_deck_id INTEGER, drop_item_list TEXT, drop_skill_list TEXT)`,
		`CREATE TABLE u_scene_tips (user_id INTEGER, scene_tips_type INTEGER)`,
		`CREATE TABLE u_card (user_id INTEGER, card_master_id INTEGER, max_free_passive_skill INTEGER)`,
	} {
		if _, err := engine.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
	dbSession := engine.NewSession()
	t.Cleanup(func() { dbSession.Close() })

	// The fixture does not depend on loaded globals: use real execution and persistence
	// with deterministic reward lists and an empty set of beginner challenges/missions.
	lesson := &gamedata.Lesson{
		IsLoaded: true,
		ItemAmount: map[int32]*drop.WeightedDropList[int32]{
			enum.LessonDropTypeNormal:    singleLessonDrop(0),
			enum.LessonDropTypeMegaphone: singleLessonDrop(0),
		},
		SkillDrop:           map[int32]*drop.WeightedDropList[int32]{312: singleLessonDrop(ordinarySkill), 123: singleLessonDrop(ordinarySkill)},
		SkillPosition:       singleLessonDrop(position),
		SkillPositionWeight: map[int32]int32{position: 1},
		SkillRarity:         map[int32]int32{101: enum.SkillRarityTypeSkillRankB, 102: enum.SkillRarityTypeSkillRankS},
		SkillSourceMenu:     map[int32]map[int32]int32{312: {101: sourceMenu, 102: sourceMenu}, 123: {101: sourceMenu, 102: sourceMenu}},
		ShootingStarSkills: map[int32]map[int32]bool{
			312: stars,
			123: stars,
		},
	}
	session := &userdata.Session{
		Db:         dbSession,
		UserId:     1,
		UserStatus: &client.UserStatus{},
		Gamedata: &gamedata.Gamedata{
			Lesson: lesson,
			Card:   map[int32]*gamedata.Card{},
			LessonMenu: map[int32]*gamedata.LessonMenu{
				1: {Id: 1}, 2: {Id: 2}, 3: {Id: 3},
			},
		},
		UserContentDiffs: map[int32]map[int32]client.Content{},
	}
	deck := client.UserLessonDeck{UserLessonDeckId: 1}
	for i := 2; i < reflect.ValueOf(&deck).Elem().NumField(); i++ {
		cardId := int32(1000 + i)
		reflect.ValueOf(&deck).Elem().Field(i).Set(reflect.ValueOf(generic.NewNullable(cardId)))
		session.Gamedata.Card[cardId] = &gamedata.Card{Id: cardId, MaxPassiveSkillSlot: 1}
		if _, err := dbSession.Exec(`INSERT INTO u_card VALUES (1, ?, 1)`, cardId); err != nil {
			t.Fatal(err)
		}
	}
	session.UserModel.UserLessonDeckById.Set(1, deck)
	req := request.ExecuteLessonRequest{
		SelectedDeckId:   1,
		ExecuteLessonIds: generic.Array[int32]{Slice: []int32{3, 1, 2}},
		IsThreeTimes:     threeTimes,
	}
	if pinSkill != 0 {
		lesson.EnhancingItemSkillRarity = map[int32]int32{1400: enum.SkillRarityTypeSkillRankA}
		lesson.GuaranteedSkillDrop = map[int32]map[int32]*drop.WeightedDropList[int32]{
			enum.SkillRarityTypeSkillRankA: {312: singleLessonDrop(pinSkill), 123: singleLessonDrop(pinSkill)},
		}
		session.UserContentDiffs[enum.ContentTypeLessonEnhancingItem] = map[int32]client.Content{
			1400: {ContentType: enum.ContentTypeLessonEnhancingItem, ContentId: 1400, ContentAmount: 3},
		}
		req.ConsumedContentIds.Append(1400)
	}
	oldConfig := config.Conf
	configCopy := *oldConfig
	resourceType := "comfortable"
	configCopy.ResourceConfigType = &resourceType
	config.Conf = &configCopy
	t.Cleanup(func() { config.Conf = oldConfig })
	for _, setup := range configure {
		setup(session, &req)
	}
	execute := ExecuteLesson(session, req)
	result := ResultLesson(session)
	// Exercise the exact wire dictionary (including special key 0) as well as its
	// in-memory representation, so serialization cannot hide a missing special action.
	wire, err := json.Marshal(execute)
	if err != nil {
		t.Fatal(err)
	}
	execute = response.ExecuteLessonResponse{}
	if err := json.Unmarshal(wire, &execute); err != nil {
		t.Fatal(err)
	}
	return execute, result
}

func markedLessonActions(resp response.ExecuteLessonResponse) map[int32][]client.LessonMenuAction {
	marked := map[int32][]client.LessonMenuAction{}
	for key, actions := range resp.LessonMenuActions.Map {
		for _, action := range actions.Slice {
			if action.IsAddedPassiveSkill {
				marked[key] = append(marked[key], action)
			}
		}
	}
	return marked
}

func TestExecuteLessonShootingStarUsesSpecialAction(t *testing.T) {
	resp, result := executeLessonFixture(t, 102, 0, 1, 5, map[int32]bool{102: true}, false)
	marked := markedLessonActions(resp)
	if len(marked) != 1 || len(marked[0]) != 1 {
		t.Fatalf("shooting star should mark only special action key 0: %+v", marked)
	}
	action := marked[0][0]
	if action.Position != 5 || action.LessonMenuId != 0 || action.UpCount != 1 ||
		!action.IsAddedSpecialPassiveSkill || !action.MaxRarity.HasValue || action.MaxRarity.Value != enum.SkillRarityTypeSkillRankS {
		t.Fatalf("incorrect special action metadata: %+v", action)
	}
	if !reflect.DeepEqual(result.DropSkillList.Slice, []client.LessonResultDropPassiveSkill{{Position: 5, PassiveSkillId: 102}}) {
		t.Fatalf("shooting-star skill was not persisted: %+v", result.DropSkillList.Slice)
	}
}

func TestExecuteLessonOrdinarySkillsKeepBulbs(t *testing.T) {
	for _, sourceMenu := range []int32{0, 1} {
		t.Run(map[int32]string{0: "any-combination skill", 1: "menu-specific skill"}[sourceMenu], func(t *testing.T) {
			resp, result := executeLessonFixture(t, 101, 0, sourceMenu, 9, nil, false)
			marked := markedLessonActions(resp)
			if len(marked) != 1 || len(marked[0]) != 0 {
				t.Fatalf("ordinary skill should mark one selected lesson: %+v", marked)
			}
			for key, actions := range marked {
				if key < 1 || key > 3 || len(actions) != 1 || actions[0].Position != 9 || actions[0].UpCount != 1 ||
					actions[0].IsAddedSpecialPassiveSkill {
					t.Fatalf("incorrect ordinary action: key=%d actions=%+v", key, actions)
				}
				if sourceMenu != 0 && actions[0].LessonMenuId != sourceMenu {
					t.Fatalf("ordinary bulb lost its source menu: %+v", actions[0])
				}
			}
			if result.DropSkillList.Size() != 1 || result.DropSkillList.Slice[0].Position != 9 {
				t.Fatalf("ordinary skill result changed: %+v", result.DropSkillList.Slice)
			}
		})
	}
}

func TestExecuteLessonPinShootingStarAlongsideOrdinarySkill(t *testing.T) {
	resp, result := executeLessonFixture(t, 101, 102, 1, lessonLeaderPosition, map[int32]bool{102: true}, false)
	marked := markedLessonActions(resp)
	if len(marked) != 2 || len(marked[0]) != 1 || len(marked[2]) != 1 {
		t.Fatalf("pin star and ordinary skill should use separate action lists: %+v", marked)
	}
	if marked[0][0].Position != lessonLeaderPosition || marked[0][0].UpCount != 1 ||
		!marked[0][0].IsAddedSpecialPassiveSkill || marked[2][0].IsAddedSpecialPassiveSkill {
		t.Fatalf("pin and ordinary animation metadata mixed: %+v", marked)
	}
	want := []client.LessonResultDropPassiveSkill{
		{Position: lessonLeaderPosition, PassiveSkillId: 101},
		{Position: lessonLeaderPosition, PassiveSkillId: 102},
	}
	if !reflect.DeepEqual(result.DropSkillList.Slice, want) {
		t.Fatalf("pin did not add a leader skill alongside ordinary draw: got %+v, want %+v", result.DropSkillList.Slice, want)
	}
}

func TestExecuteLessonRepeatedShootingStarsAccumulate(t *testing.T) {
	resp, result := executeLessonFixture(t, 101, 102, 1, lessonLeaderPosition, map[int32]bool{101: true, 102: true}, true)
	marked := markedLessonActions(resp)
	if len(marked) != 1 || len(marked[0]) != 1 {
		t.Fatalf("repeated stars should accumulate on one special action: %+v", marked)
	}
	action := marked[0][0]
	if action.UpCount != 6 || !action.IsAddedSpecialPassiveSkill || action.MaxRarity.Value != enum.SkillRarityTypeSkillRankS {
		t.Fatalf("repeated ordinary and pin stars lost count or maximum rarity: %+v", action)
	}
	if result.DropSkillList.Size() != 6 {
		t.Fatalf("three repetitions should persist six skills, got %+v", result.DropSkillList.Slice)
	}
	for _, skill := range result.DropSkillList.Slice {
		if skill.Position != lessonLeaderPosition {
			t.Fatalf("repeated pin skills lost the leader position: %+v", skill)
		}
	}
}
