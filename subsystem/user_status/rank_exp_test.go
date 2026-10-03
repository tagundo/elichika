package user_status_test

import (
	"bytes"
	"elichika/client"
	"elichika/client/response"
	"elichika/enum"
	"elichika/gamedata"
	"elichika/generic"
	"elichika/locale"
	"elichika/subsystem/user_account"
	"elichika/subsystem/user_status"
	"elichika/userdata"
	"elichika/userdata/database"
	"net/http/httptest"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"xorm.io/xorm"
)

const rankExpUserID int32 = 123456789

func rankExpEngine(t *testing.T) *xorm.Engine {
	t.Helper()
	engine, err := xorm.NewEngine("sqlite", t.TempDir()+"/userdata.db")
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	database.InitTables(engine)
	oldEngine := userdata.Engine
	userdata.Engine = engine
	t.Cleanup(func() {
		userdata.Engine = oldEngine
		engine.Close()
	})
	return engine
}

func rankExpContext(g *gamedata.Gamedata) *gin.Context {
	ctx, _ := gin.CreateTestContext(httptest.NewRecorder())
	ctx.Set("gamedata", g)
	return ctx
}

func insertRankExpStatus(t *testing.T, engine *xorm.Engine, status client.UserStatus) {
	t.Helper()
	if _, err := engine.Table("u_status").Insert(generic.UserIdWrapper[client.UserStatus]{
		UserId: rankExpUserID, Object: &status,
	}); err != nil {
		t.Fatal(err)
	}
}

func storedRankExpStatus(t *testing.T, engine *xorm.Engine) client.UserStatus {
	t.Helper()
	status := client.UserStatus{}
	exists, err := engine.Table("u_status").Where("user_id = ?", rankExpUserID).Get(&status)
	if err != nil || !exists {
		t.Fatalf("read persisted status: exists=%v err=%v", exists, err)
	}
	return status
}

func TestLegacyRankExpRepairsLoginAndPersistsAwardWithoutChangingProgress(t *testing.T) {
	g := locale.Locales["en"].Gamedata
	minimum := g.UserRank[320].Exp
	for _, oldExp := range []int32{0, 8} {
		t.Run(map[int32]string{0: "original default", 8: "already played one live"}[oldExp], func(t *testing.T) {
			engine := rankExpEngine(t)
			original := client.UserStatus{
				Rank: 320, Exp: oldExp, GameMoney: 1234, CardExp: 56,
				LessonResumeStatus: enum.TopPriorityProcessStatusNone,
				LiveMaxScore:       382840, LiveMaxCombo: 70, TutorialPhase: 99,
				ActivityPointCount: 3, LastLoginAt: time.Now().Unix(),
			}
			original.Name.DotUnderText = "Existing account"
			insertRankExpStatus(t, engine, original)
			password := database.UserPassWord{Hash: []byte("unchanged password hash")}
			auth := database.UserAuthentication{
				AuthorizationKey: []byte("keep authorization"), SessionKey: []byte("old session"),
				AuthorizationCount: 17, CommandId: 25,
			}
			card := client.UserCard{CardMasterId: 100021001, Level: 7, Grade: 4, AdditionalPassiveSkill1Id: 30000303}
			for table, row := range map[string]any{
				"u_pass_word":      generic.UserIdWrapper[database.UserPassWord]{UserId: rankExpUserID, Object: &password},
				"u_authentication": generic.UserIdWrapper[database.UserAuthentication]{UserId: rankExpUserID, Object: &auth},
				"u_card":           generic.UserIdWrapper[client.UserCard]{UserId: rankExpUserID, Object: &card},
			} {
				if _, err := engine.Table(table).Insert(row); err != nil {
					t.Fatal(err)
				}
			}

			// Exercise the actual load hook and login payload before any reward is added.
			session := userdata.GetSession(rankExpContext(g), rankExpUserID)
			login := session.Login()
			if login.UserModel.UserStatus.Rank != 320 || login.UserModel.UserStatus.Exp != minimum {
				t.Fatalf("login still exposes inconsistent cumulative EXP: %+v", login.UserModel.UserStatus)
			}
			session.Finalize()
			session.Close()
			if got := storedRankExpStatus(t, engine); got.Rank != 320 || got.Exp != minimum {
				t.Fatalf("login correction was not persisted: rank=%d exp=%d", got.Rank, got.Exp)
			}

			// A subsequent live request sees the corrected BeforeUserExp, then keeps its earned reward.
			session = userdata.GetSession(rankExpContext(g), rankExpUserID)
			beforeUserExp := session.UserStatus.Exp
			user_status.AddUserExp(session, 8)
			if beforeUserExp != minimum || session.UserStatus.Exp != minimum+8 || session.UserStatus.Rank != 320 {
				t.Fatalf("live EXP award lost or caused a false rank-up: before=%d status=%+v", beforeUserExp, session.UserStatus)
			}
			session.Finalize()
			session.Close()
			got := storedRankExpStatus(t, engine)
			// Login's timestamp and key rotation are existing behavior; the repair only changes EXP.
			want := original
			want.Exp = minimum + 8
			want.LastLoginAt = got.LastLoginAt
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("unrelated account status changed: got=%+v want=%+v", got, want)
			}
			storedPassword := database.UserPassWord{}
			storedCard := client.UserCard{}
			storedAuth := database.UserAuthentication{}
			for table, row := range map[string]any{
				"u_pass_word": &storedPassword, "u_card": &storedCard, "u_authentication": &storedAuth,
			} {
				if exists, err := engine.Table(table).Where("user_id = ?", rankExpUserID).Get(row); err != nil || !exists {
					t.Fatalf("read %s: exists=%v err=%v", table, exists, err)
				}
			}
			if !reflect.DeepEqual(storedCard, card) || !bytes.Equal(storedPassword.Hash, password.Hash) ||
				!bytes.Equal(storedAuth.AuthorizationKey, auth.AuthorizationKey) || storedAuth.AuthorizationCount != auth.AuthorizationCount {
				t.Fatal("repair changed owned card/skill, password, or authorization identity")
			}
			session = userdata.GetSession(rankExpContext(g), rankExpUserID)
			if session.UserStatus.Exp != minimum+8 {
				t.Fatal("reloading repaired account changed valid earned EXP")
			}
			session.Finalize()
			session.Close()
		})
	}
}

func TestImportedLoginRepairsRankExpBeforePersistence(t *testing.T) {
	engine := rankExpEngine(t)
	g := locale.Locales["en"].Gamedata
	insertRankExpStatus(t, engine, client.UserStatus{Rank: 1})
	ctx := rankExpContext(g)
	session := userdata.GetSession(ctx, rankExpUserID)
	imported := client.UserModel{UserStatus: client.UserStatus{Rank: 320, Exp: 8, GameMoney: 9876, LiveMaxScore: 382840}}
	imported.UserStatus.Name.DotUnderText = "Imported account"
	session.ImportLoginData(ctx, &response.LoginResponse{UserModel: &imported})
	if session.UserStatus.Rank != 320 || session.UserStatus.Exp != g.UserRank[320].Exp || session.UserStatus.GameMoney != 9876 {
		t.Fatal("imported login was not normalized before finalization")
	}
	session.Finalize()
	session.Close()
	want := imported.UserStatus
	want.Exp = g.UserRank[320].Exp
	if got := storedRankExpStatus(t, engine); !reflect.DeepEqual(got, want) {
		t.Fatalf("import repair was not persisted or changed progress: got=%+v want=%+v", got, want)
	}
}

func TestImportedDatabaseRepairsRankExpOnNextClientSession(t *testing.T) {
	engine := rankExpEngine(t)
	g := locale.Locales["en"].Gamedata
	insertRankExpStatus(t, engine, client.UserStatus{Rank: 1})
	password := database.UserPassWord{Hash: []byte("destination password")}
	auth := database.UserAuthentication{AuthorizationKey: []byte("destination authorization"), SessionKey: []byte("destination session")}
	for table, row := range map[string]any{
		"u_pass_word":      generic.UserIdWrapper[database.UserPassWord]{UserId: rankExpUserID, Object: &password},
		"u_authentication": generic.UserIdWrapper[database.UserAuthentication]{UserId: rankExpUserID, Object: &auth},
	} {
		if _, err := engine.Table(table).Insert(row); err != nil {
			t.Fatal(err)
		}
	}

	// Use a real account database import, including its UID remapping and raw-write
	// transaction. The import itself preserves the uploaded EXP; the normal client
	// session repairs it before the client can display it or a live can award EXP.
	path := t.TempDir() + "/imported.db"
	source, err := xorm.NewEngine("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	database.InitTables(source)
	imported := client.UserStatus{Rank: 320, Exp: 8, GameMoney: 9876, LiveMaxScore: 382840, LiveMaxCombo: 70}
	imported.Name.DotUnderText = "SQLite imported account"
	card := client.UserCard{CardMasterId: 100021001, Level: 7, AdditionalPassiveSkill1Id: 30000303}
	for table, row := range map[string]any{
		"u_status": generic.UserIdWrapper[client.UserStatus]{UserId: 87654321, Object: &imported},
		"u_card":   generic.UserIdWrapper[client.UserCard]{UserId: 87654321, Object: &card},
	} {
		if _, err := source.Table(table).Insert(row); err != nil {
			source.Close()
			t.Fatal(err)
		}
	}
	source.Close()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	ctx := rankExpContext(g)
	session := userdata.GetSession(ctx, rankExpUserID)
	session.DeleteUserGameData()
	message, importError := session.ImportDatabaseData(ctx, content)
	session.Close()
	if message == nil || importError != nil {
		t.Fatalf("SQLite import failed: message=%v error=%v", message, importError)
	}
	if got := storedRankExpStatus(t, engine); !reflect.DeepEqual(got, imported) {
		t.Fatalf("raw database import changed uploaded status: got=%+v want=%+v", got, imported)
	}

	session = userdata.GetSession(ctx, rankExpUserID)
	beforeUserExp := session.UserStatus.Exp
	user_status.AddUserExp(session, 8)
	if beforeUserExp != g.UserRank[320].Exp || session.UserStatus.Rank != 320 {
		t.Fatalf("first post-import live would capture inconsistent EXP: before=%d rank=%d", beforeUserExp, session.UserStatus.Rank)
	}
	session.Finalize()
	session.Close()
	want := imported
	want.Exp = g.UserRank[320].Exp + 8
	if got := storedRankExpStatus(t, engine); !reflect.DeepEqual(got, want) {
		t.Fatalf("post-import repair or reward did not persist: got=%+v want=%+v", got, want)
	}
	storedPassword := database.UserPassWord{}
	storedAuth := database.UserAuthentication{}
	storedCard := client.UserCard{}
	for table, row := range map[string]any{
		"u_pass_word": &storedPassword, "u_authentication": &storedAuth, "u_card": &storedCard,
	} {
		if exists, err := engine.Table(table).Where("user_id = ?", rankExpUserID).Get(row); err != nil || !exists {
			t.Fatalf("read post-import %s: exists=%v err=%v", table, exists, err)
		}
	}
	if !bytes.Equal(storedPassword.Hash, password.Hash) || !reflect.DeepEqual(storedAuth, auth) || !reflect.DeepEqual(storedCard, card) {
		t.Fatal("post-import repair changed destination identity or imported card/skill")
	}
}

func TestNewAccountStartsWithConsistentRankExp(t *testing.T) {
	engine := rankExpEngine(t)
	lc := locale.Locales["en"]
	ctx := rankExpContext(lc.Gamedata)
	ctx.Set("dictionary", lc.Dictionary)
	if got := user_account.CreateNewAccount(ctx, rankExpUserID, "test-password"); got != rankExpUserID {
		t.Fatalf("new account UID changed: %d", got)
	}
	status := storedRankExpStatus(t, engine)
	if status.Rank != 320 || status.Exp != lc.Gamedata.UserRank[320].Exp {
		t.Fatalf("new account persisted inconsistent rank/EXP: rank=%d exp=%d", status.Rank, status.Exp)
	}
	count, err := engine.Table("u_card").Where("user_id = ?", rankExpUserID).Count(&client.UserCard{})
	if err != nil || count != int64(len(lc.Gamedata.Card)) {
		t.Fatalf("account initialization lost owned cards: count=%d err=%v", count, err)
	}
}

func TestValidRankExpAndRankUpRemainUnchanged(t *testing.T) {
	g := &gamedata.Gamedata{
		UserRankMax: 3,
		UserRank: map[int32]*gamedata.UserRank{
			1: {Rank: 1, Exp: 0, MaxLp: 10},
			2: {Rank: 2, Exp: 100, MaxLp: 20, AdditionalAccessoryLimit: 2},
			3: {Rank: 3, Exp: 300, MaxLp: 30, AdditionalAccessoryLimit: 3},
		},
		ConstantInt: make([]int32, enum.ConstantIntLivePointRecoverlyAt+1),
	}
	g.ConstantInt[enum.ConstantIntLivePointRecoverlyAt] = 240
	for _, tc := range []struct {
		name                                                       string
		rank, exp, award, wantRank, wantExp, wantLp, wantAccessory int32
	}{
		{"normal progress", 2, 150, 8, 2, 158, 0, 0},
		{"rank boundary", 1, 95, 5, 2, 100, 20, 2},
		{"multiple rank-ups", 1, 95, 205, 3, 300, 50, 5},
		{"maximum rank", 3, 350, 8, 3, 358, 0, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			engine := rankExpEngine(t)
			insertRankExpStatus(t, engine, client.UserStatus{Rank: tc.rank, Exp: tc.exp})
			session := userdata.GetSession(rankExpContext(g), rankExpUserID)
			if session.UserStatus.Exp != tc.exp || session.UserStatus.Rank != tc.rank {
				t.Fatal("loading a legitimate account changed EXP or rank")
			}
			user_status.AddUserExp(session, tc.award)
			if session.UserStatus.Rank != tc.wantRank || session.UserStatus.Exp != tc.wantExp ||
				session.UserStatus.LivePointBroken != tc.wantLp || session.UserStatus.AccessoryBoxAdditional != tc.wantAccessory {
				t.Fatalf("existing rank-up behavior changed: %+v", session.UserStatus)
			}
			if got := session.UserModel.UserInfoTriggerBasicByTriggerId.Size(); (tc.wantRank > tc.rank && got != 1) || (tc.wantRank == tc.rank && got != 0) {
				t.Fatalf("incorrect level-up trigger count: %d", got)
			}
			session.Finalize()
			session.Close()
			if got := storedRankExpStatus(t, engine); got.Rank != tc.wantRank || got.Exp != tc.wantExp {
				t.Fatalf("rank-up reward did not persist: %+v", got)
			}
		})
	}
}

func TestMissingOrInvalidRankMasterDoesNotPanicOrInventRank(t *testing.T) {
	for _, tc := range []struct {
		name string
		rank int32
		g    *gamedata.Gamedata
	}{
		{"missing gamedata", 2, nil},
		{"missing rank table", 2, &gamedata.Gamedata{UserRankMax: 3}},
		{"missing current rank", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{3: {Rank: 3, Exp: 300}}}},
		{"missing next rank", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{2: {Rank: 2, Exp: 0}}}},
		{"mismatched next rank", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{2: {Rank: 2, Exp: 0}, 3: {Rank: 99, Exp: 300}}}},
		{"negative next minimum", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{2: {Rank: 2, Exp: 0}, 3: {Rank: 3, Exp: -1}}}},
		{"mismatched rank row", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{2: {Rank: 99, Exp: 300}}}},
		{"negative rank minimum", 2, &gamedata.Gamedata{UserRankMax: 3, UserRank: map[int32]*gamedata.UserRank{2: {Rank: 2, Exp: -1}}}},
		{"invalid saved rank", 0, &gamedata.Gamedata{UserRankMax: 3}},
		{"unknown above max rank", 99, &gamedata.Gamedata{UserRankMax: 3}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			engine := rankExpEngine(t)
			insertRankExpStatus(t, engine, client.UserStatus{Rank: tc.rank, Exp: 150})
			session := userdata.GetSession(rankExpContext(tc.g), rankExpUserID)
			user_status.AddUserExp(session, 200)
			if session.UserStatus.Rank != tc.rank || session.UserStatus.Exp != 350 {
				t.Fatalf("missing/invalid master changed rank or lost awarded EXP: %+v", session.UserStatus)
			}
			session.Finalize()
			session.Close()
			if got := storedRankExpStatus(t, engine); got.Rank != tc.rank || got.Exp != 350 {
				t.Fatalf("defensive award failed to persist: %+v", got)
			}
		})
	}
}
