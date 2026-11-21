package live

import (
	"elichika/client"
	"elichika/gamedata"
	"elichika/userdata"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestChartlessMVNeverStartsOrSkipsRhythmGameplay(t *testing.T) {
	status := client.UserStatus{LastLiveDifficultyId: 507, LatestLiveDeckId: 2, LivePointFullAt: 60, Rank: 15}
	session := &userdata.Session{
		UserStatus: &status,
		Gamedata:   &gamedata.Gamedata{LiveDifficulty: map[int32]*gamedata.LiveDifficulty{507: {}}},
	}
	for _, tc := range []struct {
		name string
		body json.RawMessage
		call func(*gin.Context)
	}{
		{"start", json.RawMessage(`{"live_difficulty_id":90000,"deck_id":7}`), start},
		{"skip", json.RawMessage(`{"live_difficulty_master_id":90000,"deck_id":7}`), skip},
	} {
		t.Run(tc.name, func(t *testing.T) {
			recorder := httptest.NewRecorder()
			ctx, _ := gin.CreateTestContext(recorder)
			ctx.Set("session", session)
			ctx.Set("reqBody", &tc.body)
			tc.call(ctx)
			if recorder.Code != http.StatusBadRequest || !strings.Contains(recorder.Body.String(), "No rhythm chart") {
				t.Fatalf("unexpected response %d: %s", recorder.Code, recorder.Body.String())
			}
			if status.LastLiveDifficultyId != 507 || status.LatestLiveDeckId != 2 || status.LivePointFullAt != 60 || status.Rank != 15 {
				t.Fatalf("missing chart changed the session: %+v", status)
			}
		})
	}
	if ctx, _ := gin.CreateTestContext(httptest.NewRecorder()); !requireRhythmChart(ctx, session, 507) {
		t.Fatal("an installed difficulty must still reach the original gameplay path")
	}
}
