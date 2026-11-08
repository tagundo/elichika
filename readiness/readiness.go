// Package readiness identifies a fully initialized, launcher-owned Go child.
package readiness

import (
	"encoding/json"
	"net"
	"net/http"
	"strings"
)

const Path = "/_elichika/ready"
const Environment = "ELICHIKA_READY_TOKEN"

// Handler captures a fresh per-process identity. This token grants no game or
// admin permissions; it lets the launcher distinguish its child from an older
// listener. Never accept a token from request headers or query parameters.
func Handler(token string) http.Handler {
	return handler(token, localAddress)
}

// A launcher may connect through a specifically bound local LAN interface.
// Inspect the real TCP peer, never the proxy/forwarding headers.
func localAddress(r *http.Request, ip net.IP) bool {
	if ip.IsLoopback() {
		return true
	}
	// Connecting to an explicitly bound local interface uses that same address
	// as the socket peer. This avoids interface enumeration/Android permissions.
	local, ok := r.Context().Value(http.LocalAddrContextKey).(*net.TCPAddr)
	return ok && local.IP.Equal(ip)
}

func handler(token string, isLocal func(*http.Request, net.IP) bool) http.Handler {
	valid := len(token) == 32 && strings.IndexFunc(token, func(r rune) bool {
		return !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f')
	}) < 0
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if zone := strings.LastIndexByte(host, '%'); zone >= 0 {
			host = host[:zone]
		}
		ip := net.ParseIP(host)
		if !valid || err != nil || ip == nil || !isLocal(r, ip) {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", http.MethodGet)
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(struct {
			Ready bool   `json:"ready"`
			Token string `json:"token"`
		}{true, token})
	})
}
