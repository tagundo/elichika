package user_lesson

import (
	"elichika/client"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/config"
	"elichika/enum"
	"elichika/gamedata"
	"elichika/generic/drop"
	"elichika/userdata"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func firstSkillPool(session *userdata.Session, _ *request.ExecuteLessonRequest) {
	session.Gamedata.Lesson.FirstSkillDrop = map[int32]*drop.WeightedDropList[int32]{
		312: singleLessonDrop(101), 123: singleLessonDrop(101),
	}
}

func TestExecuteFirstLessonZeroSkillGetsOneActionableSkill(t *testing.T) {
	for _, threeTimes := range []bool{false, true} {
		t.Run(map[bool]string{false: "single", true: "three times total empty"}[threeTimes], func(t *testing.T) {
			var session *userdata.Session
			resp, result := executeLessonFixture(t, 0, 0, 1, 5, nil, threeTimes, firstSkillPool,
				func(s *userdata.Session, _ *request.ExecuteLessonRequest) { session = s })
			want := []client.LessonResultDropPassiveSkill{{Position: 5, PassiveSkillId: 101}}
			if !reflect.DeepEqual(result.DropSkillList.Slice, want) {
				t.Fatalf("complete empty result must get exactly one valid skill: %+v", result.DropSkillList.Slice)
			}
			marked := markedLessonActions(resp)
			if len(marked) != 1 || len(marked[2]) != 1 || marked[2][0].Position != 5 ||
				marked[2][0].UpCount != 1 || marked[2][0].IsAddedSpecialPassiveSkill ||
				marked[2][0].MaxRarity.Value != enum.SkillRarityTypeSkillRankB {
				t.Fatalf("first insight skill must have the normal source-menu action: %+v", marked)
			}
			if session.UserStatus.LessonResumeStatus != enum.TopPriorityProcessStatusLesson || !lessonSkillGuideIncomplete(session) {
				t.Fatal("result must stay pending and the unseen guide must remain incomplete")
			}
			stored := response.LessonResultResponse{}
			exists, err := session.Db.Table("u_lesson").Where("user_id = 1").Get(&stored)
			if err != nil || !exists || !reflect.DeepEqual(stored.DropSkillList, result.DropSkillList) {
				t.Fatalf("wire skill did not match the real pending SQLite row: %+v, %v", stored, err)
			}
		})
	}
}

func TestExecuteCompletedLessonGuidePreservesZero(t *testing.T) {
	for _, completion := range []string{"persisted marker", "same request marker"} {
		t.Run(completion, func(t *testing.T) {
			resp, result := executeLessonFixture(t, 0, 0, 1, 5, nil, false,
				func(session *userdata.Session, _ *request.ExecuteLessonRequest) {
					if completion == "persisted marker" {
						if _, err := session.Db.Exec(`INSERT INTO u_scene_tips VALUES (1, 1)`); err != nil {
							t.Fatal(err)
						}
					} else {
						session.UserModel.UserSceneTipsByEnum.Set(1, client.UserSceneTips{SceneTipsType: 1})
					}
				})
			if result.DropSkillList.Size() != 0 || len(markedLessonActions(resp)) != 0 {
				t.Fatal("a completed guide must keep the ordinary zero-drop result and animation")
			}
		})
	}
}

func TestExecuteFirstGuideExistingDropsDoNotGetAnExtraSkill(t *testing.T) {
	for _, tc := range []struct {
		name       string
		ordinary   int32
		pin        int32
		threeTimes bool
		want       int
	}{
		{"ordinary positive", 101, 0, false, 1},
		{"three ordinary positives", 101, 0, true, 3},
		{"zero plus guaranteed pin", 0, 102, false, 1},
		{"ordinary plus pin", 101, 102, false, 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, result := executeLessonFixture(t, tc.ordinary, tc.pin, 1, 5, nil, tc.threeTimes)
			if result.DropSkillList.Size() != tc.want {
				t.Fatalf("a positive total must not receive a compatibility award: %+v", result.DropSkillList.Slice)
			}
		})
	}
}

func TestResultRepairsLegacyFirstZeroOnlyOnceAndPreservesOtherFields(t *testing.T) {
	var session *userdata.Session
	_, _ = executeLessonFixture(t, 101, 0, 0, 5, nil, false,
		func(s *userdata.Session, _ *request.ExecuteLessonRequest) { session = s })
	// Model an old APK's stored result: it contains no recipe, but its selected deck
	// and item rewards are already authoritative and must not be recalculated.
	old := response.LessonResultResponse{SelectedDeckId: 1}
	old.DropItemList.Append(client.LessonDropItem{ContentType: 1, ContentId: 123, ContentAmount: 7, DropRarity: 2})
	oldItems, err := json.Marshal(old.DropItemList)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := session.Db.Exec(`UPDATE u_lesson SET drop_skill_list='[]', drop_item_list=? WHERE user_id=1`, string(oldItems)); err != nil {
		t.Fatal(err)
	}
	session.Gamedata.Lesson.FirstSkillLegacyDrop = singleLessonDrop(101)
	first := ResultLesson(session)
	second := ResultLesson(session)
	if first.DropSkillList.Size() != 1 || !reflect.DeepEqual(first, second) ||
		first.SelectedDeckId != old.SelectedDeckId || !reflect.DeepEqual(first.DropItemList, old.DropItemList) {
		t.Fatalf("legacy repair must append once without rerolling deck/items: first=%+v second=%+v", first, second)
	}
	if !lessonSkillGuideIncomplete(session) || session.UserStatus.LessonResumeStatus != enum.TopPriorityProcessStatusLesson {
		t.Fatal("legacy repair must wait for the original guide and actual skill edit")
	}
	rows, err := session.Db.QueryString(`SELECT selected_deck_id,drop_item_list,drop_skill_list FROM u_lesson WHERE user_id=1`)
	if err != nil || len(rows) != 1 || rows[0]["drop_item_list"] != string(oldItems) || rows[0]["drop_skill_list"] == "[]" {
		t.Fatalf("legacy repair did not preserve the existing SQLite row: %+v %v", rows, err)
	}
}

func TestResultDoesNotCreateMissingOrStalePendingResult(t *testing.T) {
	var session *userdata.Session
	_, _ = executeLessonFixture(t, 101, 0, 0, 5, nil, false,
		func(s *userdata.Session, _ *request.ExecuteLessonRequest) { session = s })
	session.Gamedata.Lesson.FirstSkillLegacyDrop = singleLessonDrop(101)
	if _, err := session.Db.Exec(`UPDATE u_lesson SET drop_skill_list='[]' WHERE user_id=1`); err != nil {
		t.Fatal(err)
	}
	session.UserStatus.LessonResumeStatus = enum.TopPriorityProcessStatusNone
	if got := ResultLesson(session); got.DropSkillList.Size() != 0 {
		t.Fatal("a stale row outside pending-lesson status must not gain a skill")
	}
	if _, err := session.Db.Exec(`DELETE FROM u_lesson WHERE user_id=1`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if recover() == nil {
			t.Fatal("missing authoritative result must fail instead of fabricating a reward")
		}
		exists, err := session.Db.Table("u_lesson").Where("user_id=1").Exist()
		if err != nil || exists {
			t.Fatalf("missing result was fabricated: exists=%v err=%v", exists, err)
		}
	}()
	ResultLesson(session)
}

func TestFirstSkillCompatibilityRejectsInvalidMetadataOrDeck(t *testing.T) {
	for _, tc := range []struct {
		name  string
		setup func(*userdata.Session, *request.ExecuteLessonRequest)
	}{
		{"missing ordinary pool", func(*userdata.Session, *request.ExecuteLessonRequest) {}},
		{"invalid skill rarity", func(s *userdata.Session, r *request.ExecuteLessonRequest) {
			firstSkillPool(s, r)
			delete(s.Gamedata.Lesson.SkillRarity, 101)
		}},
		{"unknown card metadata", func(s *userdata.Session, r *request.ExecuteLessonRequest) {
			firstSkillPool(s, r)
			s.Gamedata.Card = nil
		}},
		{"unowned card", func(s *userdata.Session, r *request.ExecuteLessonRequest) {
			firstSkillPool(s, r)
			_, err := s.Db.Exec(`DELETE FROM u_card`)
			if err != nil {
				t.Fatal(err)
			}
		}},
		{"no free skill slot", func(s *userdata.Session, r *request.ExecuteLessonRequest) {
			firstSkillPool(s, r)
			_, err := s.Db.Exec(`UPDATE u_card SET max_free_passive_skill=0`)
			if err != nil {
				t.Fatal(err)
			}
		}},
		{"invalid weighted position", func(s *userdata.Session, r *request.ExecuteLessonRequest) {
			firstSkillPool(s, r)
			s.Gamedata.Lesson.SkillPositionWeight = map[int32]int32{0: 1, 10: 1}
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			defer func() {
				got := recover()
				if got == nil || !strings.Contains(got.(string), "first lesson skill guide") {
					t.Fatalf("invalid compatibility data must fail with a specific diagnostic, got %v", got)
				}
			}()
			executeLessonFixture(t, 0, 0, 1, 5, nil, false, tc.setup)
		})
	}
}

func TestUnsupportedFirstSkillPoolRollsBackTheActualRequest(t *testing.T) {
	var session *userdata.Session
	_, _ = executeLessonFixture(t, 101, 0, 1, 5, nil, false,
		func(s *userdata.Session, _ *request.ExecuteLessonRequest) { session = s })
	engine := session.Db.Engine()
	for _, sql := range []string{
		`CREATE TABLE u_status (user_id INTEGER PRIMARY KEY, activity_point_count INTEGER, lesson_resume_status INTEGER)`,
		`INSERT INTO u_status VALUES (1,3,1)`,
		`CREATE TABLE u_content (user_id INTEGER, content_type INTEGER, content_id INTEGER, content_amount INTEGER)`,
		`INSERT INTO u_content VALUES (1,6,1400,1),(1,12,501,5)`,
		`CREATE TABLE u_mission (user_id INTEGER, mission_m_id INTEGER, is_new INTEGER, mission_count INTEGER, is_cleared INTEGER, is_received_reward INTEGER, new_expired_at INTEGER)`,
		`INSERT INTO u_mission VALUES (1,99,0,2,0,0,0)`,
		`INSERT INTO u_beginner_challenge_cell VALUES (1,77,0,2)`,
	} {
		if _, err := engine.Exec(sql); err != nil {
			t.Fatal(err)
		}
	}
	snapshot := func() map[string][]map[string]string {
		result := map[string][]map[string]string{}
		for _, table := range []string{"u_status", "u_content", "u_mission", "u_beginner_challenge_cell", "u_lesson", "u_scene_tips"} {
			rows, err := engine.QueryString("SELECT * FROM " + table + " ORDER BY rowid")
			if err != nil {
				t.Fatal(err)
			}
			result[table] = rows
		}
		return result
	}
	before := snapshot()
	session.Time = time.Now()
	session.UserStatus.ActivityPointCount = 3
	session.UserStatus.ActivityPointResetAt = session.Time.Add(time.Hour).Unix()
	session.UserStatus.TutorialPhase = enum.TutorialPhaseTutorialEnd
	session.Gamedata.ConstantInt = make([]int32, enum.ConstantIntActivityPointMaxCount+1)
	session.Gamedata.ConstantInt[enum.ConstantIntActivityPointMaxCount] = 3
	resource := "original"
	config.Conf.ResourceConfigType = &resource
	mission := &gamedata.Mission{Id: 99, Term: enum.MissionTermFree, TriggerType: enum.MissionTriggerGameStart,
		EndAt: 1<<63 - 1, MissionClearConditionType: enum.MissionClearConditionTypeCountLesson, MissionClearConditionCount: 10}
	session.Gamedata.Mission = map[int32]*gamedata.Mission{99: mission}
	session.Gamedata.MissionByClearConditionType = map[int32][]*gamedata.Mission{enum.MissionClearConditionTypeCountLesson: {mission}}
	cell := &gamedata.BeginnerChallengeCell{Id: 77, ChallengeId: 1, MissionClearConditionType: enum.MissionClearConditionTypeCountLesson, MissionClearConditionCount: 10}
	session.Gamedata.BeginnerChallengeCell = map[int32]*gamedata.BeginnerChallengeCell{77: cell}
	session.Gamedata.BeginnerChallenge = map[int32]*gamedata.BeginnerChallenge{1: {Id: 1, ChallengeCells: []*gamedata.BeginnerChallengeCell{cell}}}
	lesson := session.Gamedata.Lesson
	lesson.SkillDrop = map[int32]*drop.WeightedDropList[int32]{312: singleLessonDrop(0)}
	lesson.FirstSkillDrop = nil
	lesson.ItemAmount[enum.LessonDropTypeNormal] = singleLessonDrop(3)
	lesson.EnhancingItemSkillRarity = map[int32]int32{1400: enum.SkillRarityTypeSkillRankA}
	for _, menu := range session.Gamedata.LessonMenu {
		menu.DefaultDrop = &drop.WeightedDropList[client.LessonDropItem]{}
		menu.DefaultDrop.AddItem(client.LessonDropItem{ContentType: enum.ContentTypeTrainingMaterial, ContentId: 501, ContentAmount: 1, DropRarity: 1}, 1)
	}
	req := request.ExecuteLessonRequest{SelectedDeckId: 1}
	req.ExecuteLessonIds.Slice = []int32{3, 1, 2}
	req.ConsumedContentIds.Append(1400)
	if err := session.Db.Begin(); err != nil {
		t.Fatal(err)
	}
	var observedPanic any
	var attemptedChallengeProgress int32
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.POST("/lesson/executeLesson", func(ctx *gin.Context) {
		defer func() { session.Close() }() // Exact deferred wrapper used by handler/common.initial.
		defer func() {
			if err := recover(); err != nil {
				observedPanic = err
				rows, queryErr := session.Db.QueryString(`SELECT progress FROM u_beginner_challenge_cell WHERE cell_id=77`)
				if queryErr == nil && len(rows) == 1 && rows[0]["progress"] == "3" {
					attemptedChallengeProgress = 3
				}
				panic(err)
			}
		}()
		ExecuteLesson(session, req)
		session.Finalize()
		ctx.Status(http.StatusOK)
	})
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/lesson/executeLesson", nil))
	if recorder.Code != http.StatusInternalServerError || observedPanic == nil ||
		!strings.Contains(observedPanic.(string), "first lesson skill guide requires valid ordinary skill metadata") {
		t.Fatalf("unsupported first result must be an explicit recovered HTTP 500: status=%d error=%v", recorder.Code, observedPanic)
	}
	if attemptedChallengeProgress != 3 || session.UserStatus.ActivityPointCount != 2 ||
		session.UserModel.UserMissionByMissionId.GetOnly(99).MissionCount != 3 ||
		session.UserContentDiffs[enum.ContentTypeTrainingMaterial][501].ContentAmount != 11 { // 3 drops plus the existing subscription bonus.
		t.Fatalf("the test did not reach actual operations before failure: challenge=%d AP=%d mission=%+v item=%+v multiplier=%d",
			attemptedChallengeProgress, session.UserStatus.ActivityPointCount, session.UserModel.UserMissionByMissionId.GetOnly(99),
			session.UserContentDiffs[enum.ContentTypeTrainingMaterial][501], *config.Conf.MissionMultiplier)
	}
	if after := snapshot(); !reflect.DeepEqual(before, after) {
		t.Fatalf("failed request partially changed persisted AP/pin/items/mission/pending/tips: before=%v after=%v", before, after)
	}
}

func TestUnsupportedLegacyRepairPreservesStoredPendingResult(t *testing.T) {
	var session *userdata.Session
	_, _ = executeLessonFixture(t, 101, 0, 0, 5, nil, false,
		func(s *userdata.Session, _ *request.ExecuteLessonRequest) { session = s })
	engine := session.Db.Engine()
	if _, err := engine.Exec(`UPDATE u_lesson SET drop_skill_list='[]' WHERE user_id=1`); err != nil {
		t.Fatal(err)
	}
	before, err := engine.QueryString(`SELECT * FROM u_lesson`)
	if err != nil {
		t.Fatal(err)
	}
	if err := session.Db.Begin(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if got := recover(); got == nil {
			t.Fatal("missing universal metadata must not fabricate a legacy skill")
		}
		after, err := engine.QueryString(`SELECT * FROM u_lesson`)
		if err != nil || !reflect.DeepEqual(before, after) {
			t.Fatalf("unsupported legacy repair changed stored result: %v %v", after, err)
		}
	}()
	func() { defer func() { session.Close() }(); ResultLesson(session) }()
}
