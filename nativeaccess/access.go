// Package nativeaccess grants app-owned WebViews local WebUI access. Its
// capability is deliberately independent of the publicly readable ready nonce.
package nativeaccess

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"net"
	"net/http"
	"net/url"
	"strings"

	"github.com/gin-gonic/gin"
)

const Environment = "ELICHIKA_LOCAL_WEBUI_TOKEN"
const Header = "X-Elichika-Local-Access"
const contextKey = "elichika_native_local_access"

func Authorized(ctx *gin.Context) bool { value, _ := ctx.Get(contextKey); return value == true }

func validToken(token string) bool {
	if len(token) != 32 {
		return false
	}
	for _, c := range token {
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return true
}

func loopbackHost(authority string) bool {
	u, err := url.Parse("http://" + authority)
	if err != nil || u.Host != authority || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" {
		return false
	}
	host := u.Hostname()
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func loopbackPeer(remote string) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		return false
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// Middleware captures one private launcher capability for this server process.
// Only the real TCP peer counts. Proxy headers never establish local authority.
func Middleware(token string) gin.HandlerFunc {
	valid := validToken(token)
	return func(ctx *gin.Context) {
		if !strings.HasPrefix(ctx.Request.URL.Path, "/webui/") && ctx.Request.URL.Path != "/webui" {
			ctx.Next()
			return
		}
		if !valid || !loopbackPeer(ctx.Request.RemoteAddr) || !loopbackHost(ctx.Request.Host) {
			ctx.Next()
			return
		}
		origin := "http://" + ctx.Request.Host
		if ctx.Request.TLS != nil {
			origin = "https://" + ctx.Request.Host
		}
		hostHash := sha256.Sum256([]byte(ctx.Request.Host))
		name := "elichika_local_" + hex.EncodeToString(hostHash[:6])
		mac := hmac.New(sha256.New, []byte(token))
		mac.Write([]byte("webui-cookie-v1\x00" + origin))
		expectedCookie := hex.EncodeToString(mac.Sum(nil))
		cookie, _ := ctx.Cookie(name)
		bootstrap := ctx.GetHeader(Header)
		viaHeader := len(bootstrap) == len(token) && subtle.ConstantTimeCompare([]byte(bootstrap), []byte(token)) == 1
		viaCookie := len(cookie) == len(expectedCookie) && subtle.ConstantTimeCompare([]byte(cookie), []byte(expectedCookie)) == 1
		if !viaHeader && !viaCookie {
			ctx.Next()
			return
		}
		requestOrigin := ctx.GetHeader("Origin")
		write := ctx.Request.Method != http.MethodGet && ctx.Request.Method != http.MethodHead
		// A bootstrap navigation may omit Origin. Writes must supply this exact
		// server origin, even if a native cookie or header was supplied.
		if requestOrigin != "" && requestOrigin != origin || write && requestOrigin != origin {
			ctx.AbortWithStatus(http.StatusForbidden)
			return
		}
		if viaHeader {
			http.SetCookie(ctx.Writer, &http.Cookie{Name: name, Value: expectedCookie, Path: "/webui", HttpOnly: true, Secure: ctx.Request.TLS != nil, SameSite: http.SameSiteStrictMode})
		}
		ctx.Set(contextKey, true)
		ctx.Header("Cache-Control", "no-store")
		ctx.Header("Referrer-Policy", "no-referrer")
		ctx.Next()
	}
}
