package webui_utils

import (
	"elichika/config"
	"elichika/nativeaccess"

	"net"

	"github.com/gin-gonic/gin"
)

// LocalTrusted reports app-owned capability authentication, or the older
// explicit local_trust_loopback option. New local account/password APIs require
// nativeaccess.Authorized directly; enabling the compatibility option alone
// does not grant access to the account directory or managed passwords.
//
// It deliberately uses ctx.RemoteIP() (the actual socket peer) rather than
// ctx.ClientIP() (which honours X-Forwarded-For and similar headers), so a
// remote client on a 0.0.0.0 deployment cannot spoof a loopback origin. With
// the flag left at its default (false) this always returns false, so normal
// deployments are unaffected.
func LocalTrusted(ctx *gin.Context) bool {
	if nativeaccess.Authorized(ctx) {
		return true
	}
	if config.Conf == nil || config.Conf.LocalTrustLoopback == nil || !*config.Conf.LocalTrustLoopback {
		return false
	}
	ip := net.ParseIP(ctx.RemoteIP())
	return ip != nil && ip.IsLoopback()
}
