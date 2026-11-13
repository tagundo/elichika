package live_mv_test

import (
	"bytes"
	"elichika/client"
	"elichika/client/request"
	"elichika/client/response"
	"elichika/encrypt"
	"elichika/enum"
	"elichika/generic"
	"elichika/locale"
	"elichika/router"
	"elichika/userdata"
	"elichika/userdata/database"
	_ "elichika/webui"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"testing"

	"github.com/gin-gonic/gin"
	"xorm.io/xorm"
)

// This tests the public game protocol and committed account data, rather than
// duplicating the reflective field offsets used by the deck implementation.
// Run through the initialized, disposable tests/run_go_tests.py runtime.
func TestMVDeckPersistenceAcrossSaveReloadAndStart(t *testing.T) {
	if os.Getenv("ELICHIKA_TEST_RUNTIME") == "" {
		t.Skip("requires a disposable initialized ELICHIKA_TEST_RUNTIME")
	}
	const userID int32 = 123456789
	game := locale.Locales["en"].Gamedata
	// Original lineups belong to the client/master data. Use two actual songs
	// with different 12-member lineups as independent per-song fixture oracles.
	type originalMember struct {
		LiveId         int32
		Position       int32
		MemberMasterId int32
		SuitMasterId   *int32
	}
	var mappingRows []originalMember
	var mappingErr error
	game.MasterdataDb.Do(func(db *xorm.Session) {
		mappingErr = db.SQL(`SELECT l.live_id, m.position, m.member_master_id, m.suit_master_id
FROM m_live l JOIN m_live_member_mapping m ON m.mapping_id = l.live_member_mapping_id
ORDER BY l.live_id, m.position`).Find(&mappingRows)
	})
	if mappingErr != nil {
		t.Fatal(mappingErr)
	}
	bySong := map[int32][]originalMember{}
	for _, row := range mappingRows {
		bySong[row.LiveId] = append(bySong[row.LiveId], row)
	}
	var songIDs []int32
	for id, rows := range bySong {
		if len(rows) == 12 && rows[0].Position == 1 && rows[11].Position == 12 {
			songIDs = append(songIDs, id)
		}
	}
	sort.Slice(songIDs, func(i, j int) bool { return songIDs[i] < songIDs[j] })
	if len(songIDs) < 2 {
		t.Fatal("official fixture needs two 12-slot MV songs")
	}
	songA := songIDs[0]
	var songB int32
	for _, candidate := range songIDs[1:] {
		if bySong[candidate][0].MemberMasterId != bySong[songA][0].MemberMasterId || bySong[candidate][11].MemberMasterId != bySong[songA][11].MemberMasterId {
			songB = candidate
			break
		}
	}
	if songB == 0 {
		t.Fatal("official fixture needs distinct per-song Original lineups")
	}
	memberA, memberB := bySong[songA][0].MemberMasterId, bySong[songA][11].MemberMasterId
	suitsFor := func(member int32) []int32 {
		var suits []int32
		for id, suit := range game.Suit {
			if suit.MemberMId != nil && *suit.MemberMId == member {
				suits = append(suits, id)
			}
		}
		sort.Slice(suits, func(i, j int) bool { return suits[i] < suits[j] })
		if len(suits) < 2 {
			t.Fatalf("fixture member %d needs two costumes", member)
		}
		return suits
	}
	suitsA, suitsB := suitsFor(memberA), suitsFor(memberB)
	databasePath := filepath.Join(t.TempDir(), "synthetic-mv-account.db")
	engine, err := xorm.NewEngine("sqlite", databasePath)
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	database.InitTables(engine)
	previous := userdata.Engine
	userdata.Engine = engine
	t.Cleanup(func() { userdata.Engine = previous; engine.Close() })
	status := client.UserStatus{Rank: 1, TutorialPhase: 99, TutorialEndAt: 1234}
	status.Name.DotUnderText = "Synthetic MV account"
	auth := database.UserAuthentication{AuthorizationKey: []byte("synthetic mv authorization"), SessionKey: []byte("synthetic mv session"), CommandId: 0}
	if _, err = engine.Table("u_status").Insert(generic.UserIdWrapper[client.UserStatus]{UserId: userID, Object: &status}); err != nil {
		t.Fatal(err)
	}
	if _, err = engine.Table("u_authentication").Insert(generic.UserIdWrapper[database.UserAuthentication]{UserId: userID, Object: &auth}); err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	router.Router(r)
	server := httptest.NewServer(r)
	defer server.Close()
	commandID := 0
	call := func(path string, body any, result any) {
		t.Helper()
		commandID++
		endpoint := fmt.Sprintf("%s?u=%d&id=%d&l=en", path, userID, commandID)
		payload, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		signature := encrypt.HMAC_SHA1_Encrypt([]byte(endpoint+" "+string(payload)), auth.SessionKey)
		wire := []byte(fmt.Sprintf("[%s,%q]", payload, signature))
		resp, err := http.Post(server.URL+endpoint, "application/json", bytes.NewReader(wire))
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		contents, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		if resp.StatusCode != 200 {
			t.Fatalf("%s returned HTTP %d (body omitted)", path, resp.StatusCode)
		}
		var envelope []json.RawMessage
		if err = json.Unmarshal(contents, &envelope); err != nil || len(envelope) != 5 {
			t.Fatalf("invalid game response from %s", path)
		}
		if string(envelope[2]) != "0" {
			t.Fatalf("game response from %s was not successful", path)
		}
		reflect.ValueOf(result).Elem().SetZero()
		if err = json.Unmarshal(envelope[3], result); err != nil {
			t.Fatal(err)
		}
	}
	custom := func(slot12Member, slot1Suit, slot12Suit int32) request.SaveLiveMvDeckRequest {
		deck := request.SaveLiveMvDeckRequest{LiveMasterId: songA, LiveMvDeckType: enum.LiveMvDeckTypeCustom}
		deck.MemberMasterIdByPos.Set(1, memberA)
		deck.MemberMasterIdByPos.Set(12, slot12Member)
		deck.SuitMasterIdByPos.Set(1, generic.NewNullable(slot1Suit))
		deck.SuitMasterIdByPos.Set(12, generic.NewNullable(slot12Suit))
		return deck
	}
	readDeck := func(table string, song int32) client.UserLiveMvDeck {
		t.Helper()
		// A new SQLite engine/connection must see the committed save, without
		// relying on the request's in-memory UserModel or session cache.
		fresh, err := xorm.NewEngine("sqlite", databasePath)
		if err != nil {
			t.Fatal(err)
		}
		defer fresh.Close()
		var deck client.UserLiveMvDeck
		found, err := fresh.Table(table).Where("user_id = ? AND live_master_id = ?", userID, song).Get(&deck)
		if err != nil || !found {
			t.Fatalf("saved %s deck for song %d did not reload: %v", table, song, err)
		}
		return deck
	}
	assertCustom := func(deck client.UserLiveMvDeck, slot12Member, slot1Suit, slot12Suit int32) {
		t.Helper()
		if deck.LiveMasterId != songA || deck.MemberMasterId1 != generic.NewNullable(memberA) || deck.MemberMasterId12 != generic.NewNullable(slot12Member) || deck.SuitMasterId1 != generic.NewNullable(slot1Suit) || deck.SuitMasterId12 != generic.NewNullable(slot12Suit) {
			t.Fatal("slots 1 and 12 did not retain their independent member/costume selections")
		}
	}
	var saved response.UserModelResponse
	call("/liveMv/saveDeck", custom(memberA, suitsA[0], suitsA[0]), &saved)
	if saved.UserModel == nil || !saved.UserModel.UserLiveMvDeckCustomById.Has(songA) {
		t.Fatal("save did not return the Custom deck model update")
	}
	assertCustom(*saved.UserModel.UserLiveMvDeckCustomById.GetOnly(songA), memberA, suitsA[0], suitsA[0])
	assertCustom(readDeck("u_live_mv_deck_custom", songA), memberA, suitsA[0], suitsA[0])
	t.Log("Custom slots 1 and 12 accept the same member and same costume")
	call("/liveMv/saveDeck", custom(memberA, suitsA[0], suitsA[1]), &saved)
	assertCustom(readDeck("u_live_mv_deck_custom", songA), memberA, suitsA[0], suitsA[1])
	t.Log("duplicate members retain different per-slot costumes after save/reload")
	call("/liveMv/saveDeck", custom(memberB, suitsA[0], suitsB[0]), &saved)
	assertCustom(readDeck("u_live_mv_deck_custom", songA), memberB, suitsA[0], suitsB[0])
	t.Log("replacing slot 12 preserves slot 1")
	customBeforeStart := readDeck("u_live_mv_deck_custom", songA)
	var started response.StartLiveMvResponse
	call("/liveMv/start", request.StartLiveMvRequest{LiveMasterId: songA, LiveMvDeckType: generic.NewNullable(enum.LiveMvDeckTypeCustom)}, &started)
	if started.UniqId <= 0 || !reflect.DeepEqual(readDeck("u_live_mv_deck_custom", songA), customBeforeStart) {
		t.Fatal("starting Custom MV changed its persisted lineup or costumes")
	}
	originalRequest := func(song int32) request.SaveLiveMvDeckRequest {
		deck := request.SaveLiveMvDeckRequest{LiveMasterId: song, LiveMvDeckType: enum.LiveMvDeckTypeOriginal}
		for _, row := range bySong[song] {
			deck.MemberMasterIdByPos.Set(row.Position, row.MemberMasterId)
			suit := game.Member[row.MemberMasterId].MemberInit.SuitMasterId
			if row.SuitMasterId != nil {
				suit = *row.SuitMasterId
			}
			deck.SuitMasterIdByPos.Set(row.Position, generic.NewNullable(suit))
		}
		return deck
	}
	assertOriginalLineup := func(deck client.UserLiveMvDeck, song int32) {
		t.Helper()
		contents, err := json.Marshal(deck)
		if err != nil {
			t.Fatal(err)
		}
		var fields map[string]json.RawMessage
		if err = json.Unmarshal(contents, &fields); err != nil {
			t.Fatal(err)
		}
		for _, row := range bySong[song] {
			var member int32
			if err = json.Unmarshal(fields["member_master_id_"+strconv.Itoa(int(row.Position))], &member); err != nil || member != row.MemberMasterId {
				t.Fatalf("Original song %d position %d lost its master-derived member", song, row.Position)
			}
		}
	}
	originalA, originalB := originalRequest(songA), originalRequest(songB)
	call("/liveMv/saveDeck", originalA, &saved)
	call("/liveMv/saveDeck", originalB, &saved)
	originalA.SuitMasterIdByPos.Set(1, generic.NewNullable(suitsA[1]))
	originalA.SuitMasterIdByPos.Set(12, generic.NewNullable(suitsB[1]))
	call("/liveMv/saveDeck", originalA, &saved)
	loadedA, loadedB := readDeck("u_live_mv_deck", songA), readDeck("u_live_mv_deck", songB)
	assertOriginalLineup(loadedA, songA)
	assertOriginalLineup(loadedB, songB)
	if loadedA.SuitMasterId1 != generic.NewNullable(suitsA[1]) || loadedA.SuitMasterId12 != generic.NewNullable(suitsB[1]) {
		t.Fatal("Original per-slot costume changes did not persist independently")
	}
	if !reflect.DeepEqual(readDeck("u_live_mv_deck_custom", songA), customBeforeStart) {
		t.Fatal("Original save overwrote the independent Custom lineup")
	}
	call("/liveMv/start", request.StartLiveMvRequest{LiveMasterId: songA, LiveMvDeckType: generic.NewNullable(enum.LiveMvDeckTypeOriginal)}, &started)
	call("/liveMv/start", request.StartLiveMvRequest{LiveMasterId: songB, LiveMvDeckType: generic.NewNullable(enum.LiveMvDeckTypeOriginal)}, &started)
	if !reflect.DeepEqual(readDeck("u_live_mv_deck", songA), loadedA) || !reflect.DeepEqual(readDeck("u_live_mv_deck", songB), loadedB) {
		t.Fatal("starting Original MV changed per-song members or per-slot costumes")
	}
	// Verify a normal user-model reload exposes both deck types to the client.
	ctx, _ := gin.CreateTestContext(httptest.NewRecorder())
	ctx.Set("gamedata", game)
	session := userdata.GetSession(ctx, userID)
	if session == nil {
		t.Fatal("synthetic account did not reload")
	}
	defer session.Close()
	session.PopulateUserModelField("UserLiveMvDeckById")
	session.PopulateUserModelField("UserLiveMvDeckCustomById")
	if session.UserModel.UserLiveMvDeckById.Size() != 2 || session.UserModel.UserLiveMvDeckCustomById.Size() != 1 {
		t.Fatal("model reload lost per-song or per-type deck identity")
	}
	assertOriginalLineup(*session.UserModel.UserLiveMvDeckById.GetOnly(songA), songA)
	assertCustom(*session.UserModel.UserLiveMvDeckCustomById.GetOnly(songA), memberB, suitsA[0], suitsB[0])
	t.Logf("Original song lineups %d/%d and independent slot costumes survive save/start/model reload; client owns Original selection enforcement", songA, songB)
}
