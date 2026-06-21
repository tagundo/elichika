package webui_utils

import (
	"elichika/config"
	"elichika/i18n"

	"github.com/gin-gonic/gin"
)

// Lang resolves the WebUI interface language for a request.
//
// A per-request "?l=" query parameter (the same one the user WebUI already uses
// to pick the game-data locale) wins; otherwise the server's configured default
// (RuntimeConfig.WebUILanguage) is used. The result is always a supported code
// (en/ko/ja), defaulting to English.
func Lang(ctx *gin.Context) string {
	if l := ctx.Query("l"); l != "" && i18n.Supported(i18n.Normalize(l)) {
		return i18n.Normalize(l)
	}
	if config.Conf != nil && config.Conf.WebUILanguage != nil {
		return i18n.Normalize(*config.Conf.WebUILanguage)
	}
	return i18n.DefaultLanguage
}
