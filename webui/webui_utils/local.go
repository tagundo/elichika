package webui_utils

import (
	"elichika/config"

	"net"

	"github.com/gin-gonic/gin"
)

// LocalTrusted reports whether a WebUI request may skip session-key auth because
// the operator enabled config local_trust_loopback AND the request's real TCP
// peer is a loopback address.
//
// It deliberately uses ctx.RemoteIP() (the actual socket peer) rather than
// ctx.ClientIP() (which honours X-Forwarded-For and similar headers), so a
// remote client on a 0.0.0.0 deployment cannot spoof a loopback origin. With
// the flag left at its default (false) this always returns false, so normal
// deployments are unaffected.
func LocalTrusted(ctx *gin.Context) bool {
	if config.Conf == nil || config.Conf.LocalTrustLoopback == nil || !*config.Conf.LocalTrustLoopback {
		return false
	}
	ip := net.ParseIP(ctx.RemoteIP())
	return ip != nil && ip.IsLoopback()
}
