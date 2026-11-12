package managementmode

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestBoundaryRequiresExactLocalHostAndSameOriginWrites(t *testing.T) {
	gin.SetMode(gin.TestMode)
	origin := "http://127.0.0.1:12345"
	r := gin.New()
	r.Use(Boundary(origin))
	authCalls := 0
	r.Any("/webui/admin/edit_config", func(ctx *gin.Context) {
		authCalls++
		if ctx.GetHeader("Test-Existing-Session") != "valid" {
			ctx.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		ctx.Status(http.StatusNoContent)
	})
	for _, test := range []struct {
		name, method, host, origin, session string
		status, calls                       int
	}{
		{"foreign host", "GET", "attacker.invalid", "", "valid", 403, 0},
		{"foreign origin", "POST", "127.0.0.1:12345", "https://attacker.invalid", "valid", 403, 0},
		{"missing origin", "POST", "127.0.0.1:12345", "", "valid", 403, 0},
		{"normal auth remains required", "POST", "127.0.0.1:12345", origin, "", 401, 1},
		{"authenticated same origin", "POST", "127.0.0.1:12345", origin, "valid", 204, 1},
		{"local read", "GET", "127.0.0.1:12345", "", "valid", 204, 1},
	} {
		t.Run(test.name, func(t *testing.T) {
			authCalls = 0
			request := httptest.NewRequest(test.method, origin+"/webui/admin/edit_config", nil)
			request.Host = test.host
			request.Header.Set("Origin", test.origin)
			request.Header.Set("Test-Existing-Session", test.session)
			response := httptest.NewRecorder()
			r.ServeHTTP(response, request)
			if response.Code != test.status || authCalls != test.calls {
				t.Fatalf("status=%d auth calls=%d; want %d/%d", response.Code, authCalls, test.status, test.calls)
			}
		})
	}
}
