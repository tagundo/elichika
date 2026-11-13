package nativeaccess

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func testRouter(token string) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Middleware(token))
	r.Any("/webui/check", func(ctx *gin.Context) {
		if Authorized(ctx) {
			ctx.Status(http.StatusNoContent)
		} else {
			ctx.Status(http.StatusUnauthorized)
		}
	})
	return r
}

func TestBootstrapCookieBoundToOwnedProcessAndOrigin(t *testing.T) {
	token := strings.Repeat("ab", 16)
	r := testRouter(token)
	req := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080/webui/check", nil)
	req.RemoteAddr = "127.0.0.1:40200"
	req.Header.Set(Header, token)
	resp := httptest.NewRecorder()
	r.ServeHTTP(resp, req)
	if resp.Code != http.StatusNoContent {
		t.Fatalf("bootstrap failed: %d", resp.Code)
	}
	cookies := resp.Result().Cookies()
	if len(cookies) != 1 {
		t.Fatal("bootstrap did not issue a cookie")
	}
	cookie := cookies[0]
	if !cookie.HttpOnly || cookie.SameSite != http.SameSiteStrictMode || cookie.Secure || cookie.Path != "/webui" || strings.Contains(cookie.Value, token) {
		t.Fatal("unsafe bootstrap cookie")
	}
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		req = httptest.NewRequest(method, "http://127.0.0.1:8080/webui/check", nil)
		req.RemoteAddr = "127.0.0.1:40200"
		req.AddCookie(cookie)
		if method == http.MethodPost {
			req.Header.Set("Origin", "http://127.0.0.1:8080")
		}
		resp = httptest.NewRecorder()
		r.ServeHTTP(resp, req)
		if resp.Code != http.StatusNoContent {
			t.Fatalf("cookie failed for %s: %d", method, resp.Code)
		}
	}
	resp = httptest.NewRecorder()
	testRouter(strings.Repeat("cd", 16)).ServeHTTP(resp, req)
	if resp.Code != http.StatusUnauthorized {
		t.Fatal("old process cookie authorized a new owned launch")
	}
	for _, requestOrigin := range []string{"", "null", "https://evil.example", "http://127.0.0.1:8081"} {
		req = httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8080/webui/check", nil)
		req.RemoteAddr = "127.0.0.1:40200"
		req.AddCookie(cookie)
		req.Header.Set("Origin", requestOrigin)
		resp = httptest.NewRecorder()
		r.ServeHTTP(resp, req)
		if resp.Code != http.StatusForbidden {
			t.Fatal("native cookie allowed a write without the exact server Origin")
		}
	}
	for _, target := range []string{"http://127.0.0.1:8081/webui/check", "http://localhost:8080/webui/check"} {
		req = httptest.NewRequest(http.MethodGet, target, nil)
		req.RemoteAddr = "127.0.0.1:40200"
		req.AddCookie(cookie)
		resp = httptest.NewRecorder()
		r.ServeHTTP(resp, req)
		if resp.Code != http.StatusUnauthorized {
			t.Fatal("cookie authorized a different server authority")
		}
	}
}

func TestNativeAuthorityCannotBeSpoofedOrUsedCrossOrigin(t *testing.T) {
	token := strings.Repeat("12", 16)
	tests := []struct {
		name, peer, host, origin, method, supplied string
		status                                     int
	}{
		{"remote proxy spoof", "203.0.113.4:42", "127.0.0.1:8080", "", "GET", token, 401},
		{"LAN binding peer", "192.0.2.2:42", "127.0.0.1:8080", "", "GET", token, 401},
		{"DNS rebound", "127.0.0.1:42", "evil.example:8080", "", "GET", token, 401},
		{"authority userinfo", "127.0.0.1:42", "evil@127.0.0.1:8080", "", "GET", token, 401},
		{"missing capability", "127.0.0.1:42", "127.0.0.1:8080", "", "GET", "", 401},
		{"wrong capability", "127.0.0.1:42", "127.0.0.1:8080", "", "GET", strings.Repeat("34", 16), 401},
		{"foreign origin bootstrap", "127.0.0.1:42", "127.0.0.1:8080", "https://evil.example", "GET", token, 403},
		{"null origin", "127.0.0.1:42", "127.0.0.1:8080", "null", "GET", token, 403},
		{"missing write origin", "127.0.0.1:42", "127.0.0.1:8080", "", "POST", token, 403},
		{"wrong write port", "127.0.0.1:42", "127.0.0.1:8080", "http://127.0.0.1:8081", "POST", token, 403},
		{"same origin", "127.0.0.1:42", "127.0.0.1:8080", "http://127.0.0.1:8080", "POST", token, 204},
		{"IPv6", "[::1]:42", "[::1]:8080", "http://[::1]:8080", "POST", token, 204},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			req := httptest.NewRequest(test.method, "/webui/check", nil)
			req.Host = test.host
			req.RemoteAddr = test.peer
			req.Header.Set(Header, test.supplied)
			req.Header.Set("Origin", test.origin)
			req.Header.Set("X-Forwarded-For", "127.0.0.1")
			req.Header.Set("X-Forwarded-Host", "127.0.0.1:8080")
			resp := httptest.NewRecorder()
			testRouter(token).ServeHTTP(resp, req)
			if resp.Code != test.status {
				t.Fatalf("status %d, want %d", resp.Code, test.status)
			}
		})
	}
}

func TestUnmanagedAndInvalidLaunchTokensNeverGrantAccess(t *testing.T) {
	for _, token := range []string{"", "short", strings.Repeat("A", 32), strings.Repeat("z", 32), strings.Repeat("a", 33)} {
		req := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8080/webui/check", nil)
		req.RemoteAddr = "127.0.0.1:42"
		req.Header.Set(Header, token)
		resp := httptest.NewRecorder()
		testRouter(token).ServeHTTP(resp, req)
		if resp.Code != http.StatusUnauthorized {
			t.Fatal("invalid private launch capability granted access")
		}
	}
}
