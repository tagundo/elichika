package userdata_test

import (
	"bytes"
	"elichika/client"
	"elichika/config"
	"elichika/enum"
	"elichika/subsystem/user_scene_tips"
	"elichika/userdata"
	"encoding/json"
	"reflect"
	"strconv"
	"testing"
)

func tutorialPreference(t *testing.T, enabled bool) {
	t.Helper()
	previous := config.Conf.Tutorial
	config.Conf.Tutorial = &enabled
	t.Cleanup(func() { config.Conf.Tutorial = previous })
}

func assertCompletedGuides(t *testing.T, session *userdata.Session) {
	t.Helper()
	for _, tip := range []int32{1, 2, 3, 4} {
		value := session.UserModel.UserSceneTipsByEnum.GetOnly(tip)
		if value == nil || value.SceneTipsType != tip {
			t.Fatalf("login model is missing completed guide %d", tip)
		}
		rows, err := session.Db.Query("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=? AND scene_tips_type=?", session.UserId, tip)
		if err != nil || len(rows) != 1 {
			t.Fatalf("guide %d was not persisted exactly once: %v", tip, err)
		}
	}
}

func TestLoginSkipsMainTutorialAndFirstUseGuides(t *testing.T) {
	for _, input := range []struct {
		phase int32
		endAt int64
	}{
		{enum.TutorialPhaseNameInput, 0},
		{enum.TutorialPhaseTutorialEnd, 123456},
		{enum.TutorialPhaseTutorialEnd, 0},
	} {
		t.Run("phase_"+strconv.Itoa(int(input.phase))+"_end_"+strconv.FormatInt(input.endAt, 10), func(t *testing.T) {
			tutorialPreference(t, false)
			engine, _, ctx := homeSuitFixture(t)
			endAt := input.endAt
			if _, err := engine.Exec("UPDATE u_status SET tutorial_phase=?, tutorial_end_at=? WHERE user_id=?", input.phase, endAt, homeSuitUserID); err != nil {
				t.Fatal(err)
			}
			session := userdata.GetSession(ctx, homeSuitUserID)
			defer session.Close()
			login := session.Login()
			assertCompletedGuides(t, session)
			if login.UserModel != &session.UserModel || login.UserModel.UserStatus.TutorialPhase != enum.TutorialPhaseTutorialEnd {
				t.Fatal("first login response still requires the main tutorial")
			}
			if endAt > 0 && session.UserStatus.TutorialEndAt != endAt {
				t.Fatal("existing completion time changed")
			}
			if endAt == 0 && session.UserStatus.TutorialEndAt != session.Time.Unix() {
				t.Fatal("new completion time is missing")
			}
			session.Finalize()
			session.Close()
			second := userdata.GetSession(ctx, homeSuitUserID)
			defer second.Close()
			if second.UserStatus.TutorialPhase != enum.TutorialPhaseTutorialEnd || second.UserStatus.TutorialEndAt != session.UserStatus.TutorialEndAt {
				t.Fatal("tutorial completion status was not persisted by the first login")
			}
			second.Login()
			assertCompletedGuides(t, second)
			second.Finalize()
		})
	}
}

func TestGuideMigrationPreservesOtherProgress(t *testing.T) {
	tutorialPreference(t, true)
	engine, _, ctx := homeSuitFixture(t)
	if _, err := engine.Exec("UPDATE u_status SET tutorial_phase=1, tutorial_end_at=0 WHERE user_id=?", homeSuitUserID); err != nil {
		t.Fatal(err)
	}
	for _, tip := range []int32{2, 77} {
		if _, err := engine.Exec("INSERT INTO u_scene_tips(user_id,scene_tips_type) VALUES(?,?)", homeSuitUserID, tip); err != nil {
			t.Fatal(err)
		}
	}
	session := userdata.GetSession(ctx, homeSuitUserID)
	defer session.Close()
	session.Login()
	wantTables := homeSuitSnapshotInSession(t, session.Db)
	delete(wantTables, "u_scene_tips")
	wantModel := session.UserModel
	wantModel.UserSceneTipsByEnum = session.UserModel.UserSceneTipsByEnum.Copy()
	wantModel.UserStatus.TutorialPhase = enum.TutorialPhaseTutorialEnd
	wantModel.UserStatus.TutorialEndAt = session.Time.Unix()
	for _, tip := range []int32{1, 2, 3, 4} {
		if wantModel.UserSceneTipsByEnum.GetOnly(tip) == nil {
			wantModel.UserSceneTipsByEnum.Set(tip, client.UserSceneTips{SceneTipsType: tip})
		}
	}
	wantJSON, err := json.Marshal(wantModel)
	if err != nil {
		t.Fatal(err)
	}
	*config.Conf.Tutorial = false
	session.NormalizeTutorialState()
	assertCompletedGuides(t, session)
	gotTables := homeSuitSnapshotInSession(t, session.Db)
	delete(gotTables, "u_scene_tips")
	assertHomeSuitSnapshot(t, wantTables, gotTables)
	gotJSON, err := json.Marshal(session.UserModel)
	if err != nil || !bytes.Equal(wantJSON, gotJSON) {
		t.Fatal("migration changed unrelated login progress or lost an existing guide")
	}
	session.Finalize()
}

func TestTutorialOptInPreservesFirstUseGuides(t *testing.T) {
	tutorialPreference(t, true)
	engine, _, ctx := homeSuitFixture(t)
	if _, err := engine.Exec("UPDATE u_status SET tutorial_phase=1, tutorial_end_at=0 WHERE user_id=?", homeSuitUserID); err != nil {
		t.Fatal(err)
	}
	session := userdata.GetSession(ctx, homeSuitUserID)
	defer session.Close()
	session.Login()
	if session.UserStatus.TutorialPhase != 1 || session.UserStatus.TutorialEndAt != 0 || session.UserModel.UserSceneTipsByEnum.Size() != 0 {
		t.Fatal("explicit tutorial opt-in was ignored")
	}
	want := homeSuitSnapshotInSession(t, session.Db)
	session.NormalizeTutorialState()
	assertHomeSuitSnapshot(t, want, homeSuitSnapshotInSession(t, session.Db))
	session.Finalize()
}

func TestGuideMigrationRollsBackWithLogin(t *testing.T) {
	tutorialPreference(t, false)
	engine, _, ctx := homeSuitFixture(t)
	session := userdata.GetSession(ctx, homeSuitUserID)
	before := homeSuitSnapshotInSession(t, session.Db)
	session.Login()
	assertCompletedGuides(t, session)
	if err := session.Db.Rollback(); err != nil {
		t.Fatal(err)
	}
	session.Close()
	read := engine.NewSession()
	defer read.Close()
	after := homeSuitSnapshotInSession(t, read)
	if !reflect.DeepEqual(before, after) {
		t.Fatal("rolled-back login retained tutorial or other changes")
	}
}

func TestSceneTipCompletionIsIdempotentAfterMigration(t *testing.T) {
	tutorialPreference(t, false)
	engine, _, ctx := homeSuitFixture(t)
	login := userdata.GetSession(ctx, homeSuitUserID)
	login.Login()
	login.Finalize()
	login.Close()
	for count := 0; count < 2; count++ {
		session := userdata.GetSession(ctx, homeSuitUserID)
		user_scene_tips.SaveUserSceneTips(session, enum.SceneTipsTypeReferenceBook)
		session.Finalize()
		session.Close()
	}
	rows, err := engine.Query("SELECT scene_tips_type FROM u_scene_tips WHERE user_id=? ORDER BY scene_tips_type", homeSuitUserID)
	if err != nil || len(rows) != 4 {
		t.Fatalf("repeated official completion changed guide records: %v", err)
	}
}
