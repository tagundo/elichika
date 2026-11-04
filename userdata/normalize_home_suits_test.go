package userdata_test

import (
	"bytes"
	"elichika/client"
	"elichika/gamedata"
	"elichika/generic"
	"elichika/userdata"
	"elichika/userdata/database"
	"encoding/json"
	"net/http/httptest"
	"reflect"
	"strconv"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"xorm.io/xorm"
)

const homeSuitUserID int32 = 123456789

func homeSuitFixture(t *testing.T) (*xorm.Engine, *gamedata.Gamedata, *gin.Context) {
	t.Helper()
	engine, err := xorm.NewEngine("sqlite", t.TempDir()+"/userdata.db")
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	database.InitTables(engine)
	previous := userdata.Engine
	userdata.Engine = engine
	t.Cleanup(func() { userdata.Engine = previous; engine.Close() })
	memberID := int32(1)
	otherMemberID := int32(2)
	g := &gamedata.Gamedata{
		Member: map[int32]*gamedata.Member{1: {Id: 1, MemberInit: gamedata.MemberInit{SuitMasterId: 100}}, 2: {Id: 2, MemberInit: gamedata.MemberInit{SuitMasterId: 200}}},
		Suit:   map[int32]*gamedata.Suit{100: {Id: 100, MemberMId: &memberID}, 200: {Id: 200, MemberMId: &otherMemberID}},
	}
	status := client.UserStatus{
		FavoriteMemberId: 1, Rank: 1, Exp: 13, GameMoney: 12345, CardExp: 6789,
		TutorialPhase: 99, TutorialEndAt: 123456, TermsOfUseVersion: 3,
		LiveMaxScore: 987654, LiveMaxCombo: 456, LatestLiveDeckId: 7,
		LastLoginAt: time.Now().Unix(), LoginDays: 42, RecommendCardMasterId: 555,
		EmblemId: 777, FreeSnsCoin: 123, AccessoryBoxAdditional: 50,
	}
	status.Name.DotUnderText = "Synthetic progress"
	status.Nickname.DotUnderText = "Synthetic nickname"
	status.Message.DotUnderText = "Keep this profile"
	member := client.UserMember{MemberMasterId: 1, SuitMasterId: 900001, CustomBackgroundMasterId: 600,
		LoveLevel: 77, LovePoint: 123456, LovePointLimit: 654321, ViewStatus: 2, IsNew: true}
	otherMember := client.UserMember{MemberMasterId: 2, SuitMasterId: 200, CustomBackgroundMasterId: 601, LoveLevel: 66}
	initialSuit := client.UserSuit{SuitMasterId: 100, IsNew: true}
	orphanSuit := client.UserSuit{SuitMasterId: 900001, IsNew: false}
	background := client.UserCustomBackground{CustomBackgroundMasterId: 600, IsNew: true}
	card := client.UserCard{CardMasterId: 555, Level: 67, Grade: 4, Exp: 123, IsFavorite: true}
	deck := client.UserLiveDeck{UserLiveDeckId: 7, CardMasterId1: generic.NewNullable(int32(555)), SuitMasterId1: generic.NewNullable(int32(900001))}
	deck.Name.DotUnderText = "Keep this deck"
	auth := database.UserAuthentication{AuthorizationKey: []byte("synthetic authorization"), SessionKey: []byte("synthetic old session"), AuthorizationCount: 17, CommandId: 23}
	password := database.UserPassWord{Hash: []byte("synthetic password hash")}
	rows := []struct {
		table string
		value any
	}{
		{"u_status", generic.UserIdWrapper[client.UserStatus]{UserId: homeSuitUserID, Object: &status}},
		{"u_member", generic.UserIdWrapper[client.UserMember]{UserId: homeSuitUserID, Object: &member}},
		{"u_member", generic.UserIdWrapper[client.UserMember]{UserId: homeSuitUserID, Object: &otherMember}},
		{"u_suit", generic.UserIdWrapper[client.UserSuit]{UserId: homeSuitUserID, Object: &initialSuit}},
		{"u_suit", generic.UserIdWrapper[client.UserSuit]{UserId: homeSuitUserID, Object: &orphanSuit}},
		{"u_custom_background", generic.UserIdWrapper[client.UserCustomBackground]{UserId: homeSuitUserID, Object: &background}},
		{"u_card", generic.UserIdWrapper[client.UserCard]{UserId: homeSuitUserID, Object: &card}},
		{"u_live_deck", generic.UserIdWrapper[client.UserLiveDeck]{UserId: homeSuitUserID, Object: &deck}},
		{"u_authentication", generic.UserIdWrapper[database.UserAuthentication]{UserId: homeSuitUserID, Object: &auth}},
		{"u_pass_word", generic.UserIdWrapper[database.UserPassWord]{UserId: homeSuitUserID, Object: &password}},
	}
	for _, row := range rows {
		if _, err := engine.Table(row.table).Insert(row.value); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := engine.Exec(`CREATE TABLE retained_mod_state (id INTEGER PRIMARY KEY, value TEXT); INSERT INTO retained_mod_state VALUES (1, 'keep custom state')`); err != nil {
		t.Fatal(err)
	}
	ctx, _ := gin.CreateTestContext(httptest.NewRecorder())
	ctx.Set("gamedata", g)
	return engine, g, ctx
}

type homeSuitSnapshot map[string][]map[string][]byte

func homeSuitSnapshotInSession(t *testing.T, db *xorm.Session) homeSuitSnapshot {
	t.Helper()
	tables, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name`)
	if err != nil {
		t.Fatal(err)
	}
	result := homeSuitSnapshot{}
	for _, table := range tables {
		name := string(table["name"])
		rows, err := db.Query(`SELECT * FROM "` + name + `" ORDER BY rowid`)
		if err != nil {
			t.Fatal(err)
		}
		result[name] = rows
	}
	return result
}

func assertHomeSuitSnapshot(t *testing.T, want, got homeSuitSnapshot) {
	t.Helper()
	if len(want) != len(got) {
		t.Fatal("normalization changed the database table set")
	}
	for table, rows := range want {
		if !reflect.DeepEqual(rows, got[table]) {
			t.Fatalf("normalization changed unexpected fields in table %s", table)
		}
	}
}

func TestNormalizeHomeSuitsPreservesAccountAndLoginPayload(t *testing.T) {
	engine, _, ctx := homeSuitFixture(t)
	session := userdata.GetSession(ctx, homeSuitUserID)
	defer session.Close()
	login := session.Login()
	want := homeSuitSnapshotInSession(t, session.Db)
	for _, row := range want["u_member"] {
		if string(row["member_master_id"]) == "1" {
			row["suit_master_id"] = []byte("100")
		}
	}
	wantModel := session.UserModel
	wantModel.UserMemberByMemberId = session.UserModel.UserMemberByMemberId.Copy()
	wantModel.UserMemberByMemberId.GetOnly(1).SuitMasterId = 100
	wantJSON, err := json.Marshal(wantModel)
	if err != nil {
		t.Fatal(err)
	}
	if session.NormalizeHomeSuits() != 1 {
		t.Fatal("removed selected costume was not normalized")
	}
	assertHomeSuitSnapshot(t, want, homeSuitSnapshotInSession(t, session.Db))
	gotJSON, err := json.Marshal(login.UserModel)
	if err != nil || !bytes.Equal(gotJSON, wantJSON) {
		t.Fatal("login payload did not preserve the model except the selected costume")
	}
	if session.NormalizeHomeSuits() != 0 {
		t.Fatal("normalization is not idempotent")
	}
	assertHomeSuitSnapshot(t, want, homeSuitSnapshotInSession(t, session.Db))
	wantStatus, wantAuth := *session.UserStatus, session.AuthenticationData
	session.Finalize()
	session.Close()

	stored := client.UserMember{}
	exists, err := engine.Table("u_member").Where("user_id = ? AND member_master_id = ?", homeSuitUserID, 1).Get(&stored)
	if err != nil || !exists || stored.SuitMasterId != 100 {
		t.Fatal("login did not commit the selected costume repair")
	}
	status, auth := client.UserStatus{}, database.UserAuthentication{}
	if _, err := engine.Table("u_status").Where("user_id = ?", homeSuitUserID).Get(&status); err != nil {
		t.Fatal(err)
	}
	if _, err := engine.Table("u_authentication").Where("user_id = ?", homeSuitUserID).Get(&auth); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(status, wantStatus) || !reflect.DeepEqual(auth, wantAuth) {
		t.Fatal("normalization changed status or authentication beyond existing login behavior")
	}
	// A second login must read the persisted repair, without changing other rows.
	next := userdata.GetSession(ctx, homeSuitUserID)
	defer next.Close()
	if next.Login().UserModel.UserMemberByMemberId.GetOnly(1).SuitMasterId != 100 || next.NormalizeHomeSuits() != 0 {
		t.Fatal("next login did not retain the already normalized costume")
	}
}

func TestNormalizeHomeSuitsOnlyRepairsRemovedMasterWithOwnedDefault(t *testing.T) {
	cases := []struct {
		name string
		edit func(*xorm.Engine, *gamedata.Gamedata)
	}{
		{"existing vanilla", func(e *xorm.Engine, g *gamedata.Gamedata) {
			_, _ = e.Exec("UPDATE u_member SET suit_master_id=100 WHERE member_master_id=1")
		}},
		{"valid mod", func(e *xorm.Engine, g *gamedata.Gamedata) {
			id := int32(1)
			g.Suit[900001] = &gamedata.Suit{Id: 900001, MemberMId: &id}
		}},
		{"existing master without ownership", func(e *xorm.Engine, g *gamedata.Gamedata) {
			id := int32(1)
			g.Suit[900001] = &gamedata.Suit{Id: 900001, MemberMId: &id}
			_, _ = e.Exec("DELETE FROM u_suit WHERE suit_master_id=900001")
		}},
		{"missing default master", func(e *xorm.Engine, g *gamedata.Gamedata) { delete(g.Suit, 100) }},
		{"unowned default", func(e *xorm.Engine, g *gamedata.Gamedata) {
			_, _ = e.Exec("DELETE FROM u_suit WHERE suit_master_id=100")
		}},
		{"wrong default owner", func(e *xorm.Engine, g *gamedata.Gamedata) { id := int32(2); g.Suit[100].MemberMId = &id }},
		{"missing default owner", func(e *xorm.Engine, g *gamedata.Gamedata) { g.Suit[100].MemberMId = nil }},
		{"zero default", func(e *xorm.Engine, g *gamedata.Gamedata) { g.Member[1].MemberInit.SuitMasterId = 0 }},
		{"missing favorite master", func(e *xorm.Engine, g *gamedata.Gamedata) { delete(g.Member, 1) }},
		{"missing selected user member", func(e *xorm.Engine, g *gamedata.Gamedata) {
			_, _ = e.Exec("DELETE FROM u_member WHERE member_master_id=1")
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			engine, g, ctx := homeSuitFixture(t)
			tc.edit(engine, g)
			session := userdata.GetSession(ctx, homeSuitUserID)
			defer session.Close()
			session.Login()
			before := homeSuitSnapshotInSession(t, session.Db)
			model, err := json.Marshal(session.UserModel)
			if err != nil {
				t.Fatal(err)
			}
			if session.NormalizeHomeSuits() != 0 {
				t.Fatal("normalization changed an existing selection or used an unsafe fallback")
			}
			assertHomeSuitSnapshot(t, before, homeSuitSnapshotInSession(t, session.Db))
			after, err := json.Marshal(session.UserModel)
			if err != nil || !bytes.Equal(model, after) {
				t.Fatal("no-op normalization changed the response model")
			}
		})
	}
}

func TestNormalizeHomeSuitsRollsBackWithLoginTransaction(t *testing.T) {
	engine, _, ctx := homeSuitFixture(t)
	session := userdata.GetSession(ctx, homeSuitUserID)
	session.Login()
	if session.NormalizeHomeSuits() != 1 {
		t.Fatal("expected repair before rollback")
	}
	if err := session.Db.Rollback(); err != nil {
		t.Fatal(err)
	}
	session.Close()
	member := client.UserMember{}
	if _, err := engine.Table("u_member").Where("user_id = ? AND member_master_id = ?", homeSuitUserID, 1).Get(&member); err != nil {
		t.Fatal(err)
	}
	if member.SuitMasterId != 900001 {
		t.Fatal("normalization committed outside the login transaction: " + strconv.Itoa(int(member.SuitMasterId)))
	}
}

func TestNormalizeHomeSuitsRepairsThirtyMembersAndPreservesValidMod(t *testing.T) {
	engine, g, ctx := homeSuitFixture(t)
	for memberID := int32(1); memberID <= 31; memberID++ {
		owner := memberID
		initial := int32(10000) + memberID
		selected := int32(900000) + memberID
		g.Member[memberID] = &gamedata.Member{Id: memberID, MemberInit: gamedata.MemberInit{SuitMasterId: initial}}
		g.Suit[initial] = &gamedata.Suit{Id: initial, MemberMId: &owner}
		if memberID == 31 {
			// A valid mod must survive even when every other selection was removed.
			g.Suit[selected] = &gamedata.Suit{Id: selected, MemberMId: &owner}
		}
		if _, err := engine.Exec(`INSERT OR REPLACE INTO u_member
			(user_id,member_master_id,suit_master_id,custom_background_master_id,love_point,love_level,love_point_limit,view_status,is_new)
			VALUES (?,?,?,?,?,?,?,?,?)`, homeSuitUserID, memberID, selected, 600+memberID, 12345+memberID, 50+memberID, 98765+memberID, 2, true); err != nil {
			t.Fatal(err)
		}
		for _, suitID := range []int32{initial, selected} {
			if _, err := engine.Exec(`INSERT OR IGNORE INTO u_suit (user_id,suit_master_id,is_new) VALUES (?,?,?)`, homeSuitUserID, suitID, true); err != nil {
				t.Fatal(err)
			}
		}
	}
	session := userdata.GetSession(ctx, homeSuitUserID)
	login := session.Login()
	want := homeSuitSnapshotInSession(t, session.Db)
	for _, row := range want["u_member"] {
		id, err := strconv.Atoi(string(row["member_master_id"]))
		if err != nil {
			t.Fatal(err)
		}
		if id <= 30 {
			row["suit_master_id"] = []byte(strconv.Itoa(10000 + id))
		}
	}
	wantModel := session.UserModel
	wantModel.UserMemberByMemberId = session.UserModel.UserMemberByMemberId.Copy()
	for id := int32(1); id <= 30; id++ {
		wantModel.UserMemberByMemberId.GetOnly(id).SuitMasterId = 10000 + id
	}
	wantJSON, err := json.Marshal(wantModel)
	if err != nil {
		t.Fatal(err)
	}
	if got := session.NormalizeHomeSuits(); got != 30 {
		t.Fatalf("repaired %d members, want 30", got)
	}
	assertHomeSuitSnapshot(t, want, homeSuitSnapshotInSession(t, session.Db))
	gotJSON, err := json.Marshal(login.UserModel)
	if err != nil || !bytes.Equal(wantJSON, gotJSON) {
		t.Fatal("multi-member login changed fields beyond the 30 missing costume selections")
	}
	if login.UserModel.UserMemberByMemberId.GetOnly(31).SuitMasterId != 900031 {
		t.Fatal("valid mod costume was changed")
	}
	session.Finalize()
	session.Close()
	next := userdata.GetSession(ctx, homeSuitUserID)
	defer next.Close()
	loaded := next.Login()
	before := homeSuitSnapshotInSession(t, next.Db)
	if next.NormalizeHomeSuits() != 0 {
		t.Fatal("second login repeated a completed normalization")
	}
	for id := int32(1); id <= 30; id++ {
		if loaded.UserModel.UserMemberByMemberId.GetOnly(id).SuitMasterId != 10000+id {
			t.Fatal("second login lost a persisted costume repair")
		}
	}
	assertHomeSuitSnapshot(t, before, homeSuitSnapshotInSession(t, next.Db))
}

func TestNormalizeHomeSuitsDoesNotRunOutsideActiveLogin(t *testing.T) {
	for _, state := range []string{"gameplay", "finalized", "basic"} {
		t.Run(state, func(t *testing.T) {
			_, _, ctx := homeSuitFixture(t)
			session := userdata.GetSession(ctx, homeSuitUserID)
			defer session.Close()
			session.Login()
			switch state {
			case "gameplay":
				session.SessionType = userdata.SessionTypeGameplay
			case "finalized":
				session.Finalized = true
			case "basic":
				session.IsBasic = true
			}
			before := homeSuitSnapshotInSession(t, session.Db)
			if session.NormalizeHomeSuits() != 0 {
				t.Fatal("normalization wrote outside an active ordinary login")
			}
			assertHomeSuitSnapshot(t, before, homeSuitSnapshotInSession(t, session.Db))
		})
	}
}
