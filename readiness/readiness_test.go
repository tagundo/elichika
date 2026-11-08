package readiness

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestReadyOnlyForLoopbackAndConfiguredChildIdentity(t *testing.T) {
	token := strings.Repeat("ab", 16)
	for _, remote := range []string{"127.0.0.1:10000", "[::1]:10000", "[::ffff:127.0.0.1]:10000"} {
		request := httptest.NewRequest(http.MethodGet, Path, nil)
		request.RemoteAddr = remote
		response := httptest.NewRecorder()
		Handler(token).ServeHTTP(response, request)
		var result struct {
			Ready bool   `json:"ready"`
			Token string `json:"token"`
		}
		if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		if response.Code != http.StatusOK || !result.Ready || result.Token != token || response.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("wrong readiness reply for %s: %s", remote, response.Body.String())
		}
	}
}

func TestReadyNeverEchoesRequestIdentityOrTrustsProxyHeaders(t *testing.T) {
	owned := strings.Repeat("a", 32)
	foreign := strings.Repeat("b", 32)
	request := httptest.NewRequest(http.MethodGet, Path+"?token="+foreign, nil)
	request.RemoteAddr = "127.0.0.1:1234"
	request.Header.Set("X-Elichika-Ready-Token", foreign)
	response := httptest.NewRecorder()
	Handler(owned).ServeHTTP(response, request)
	if strings.Contains(response.Body.String(), foreign) || !strings.Contains(response.Body.String(), owned) {
		t.Fatal("readiness identity came from an untrusted request")
	}
	request.RemoteAddr = "203.0.113.10:1234"
	request.Header.Set("X-Forwarded-For", "127.0.0.1")
	response = httptest.NewRecorder()
	Handler(owned).ServeHTTP(response, request)
	if response.Code != http.StatusNotFound || strings.Contains(response.Body.String(), owned) {
		t.Fatal("remote request read launcher identity through a forged proxy header")
	}
}

func TestUnmanagedInvalidOrWrongMethodCannotReportReady(t *testing.T) {
	for _, token := range []string{"", "short", strings.Repeat("A", 32), strings.Repeat("z", 32), strings.Repeat("a", 33)} {
		request := httptest.NewRequest(http.MethodGet, Path, nil)
		request.RemoteAddr = "127.0.0.1:1234"
		response := httptest.NewRecorder()
		Handler(token).ServeHTTP(response, request)
		if response.Code != http.StatusNotFound {
			t.Fatalf("invalid identity reported ready: %q", token)
		}
	}
	request := httptest.NewRequest(http.MethodPost, Path, nil)
	request.RemoteAddr = "127.0.0.1:1234"
	response := httptest.NewRecorder()
	Handler(strings.Repeat("a", 32)).ServeHTTP(response, request)
	if response.Code != http.StatusMethodNotAllowed {
		t.Fatal("unexpected readiness method accepted")
	}
}

func TestExplicitLocalInterfaceAndIPv6ZoneAreSupported(t *testing.T) {
	for _, remote := range []string{"192.0.2.15:8080", "[fe80::5%en0]:8080"} {
		request := httptest.NewRequest(http.MethodGet, Path, nil)
		request.RemoteAddr = remote
		response := httptest.NewRecorder()
		local := net.ParseIP("192.0.2.15")
		if strings.Contains(remote, "fe80") {
			local = net.ParseIP("fe80::5")
		}
		request = request.WithContext(context.WithValue(request.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: local, Port: 8080}))
		owned := Handler(strings.Repeat("c", 32))
		owned.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("own local interface readiness failed for %s", remote)
		}
	}
}
