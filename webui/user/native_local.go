package user

import (
	"elichika/config"
	"elichika/nativeaccess"
	"elichika/router"
	"elichika/subsystem/managedcredential"
	"elichika/userdata"
	_ "embed"

	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

//go:embed native_connection.html
var nativeConnectionHTML string

func requireNativeLocal(ctx *gin.Context) bool {
	if !nativeaccess.Authorized(ctx) {
		ctx.AbortWithStatus(http.StatusForbidden)
		return false
	}
	ctx.Header("Cache-Control", "no-store")
	return true
}

func nativeAccounts(ctx *gin.Context) {
	if !requireNativeLocal(ctx) {
		return
	}
	type account struct {
		UserId int32 `json:"user_id"`
		Rank   int32 `json:"rank"`
	}
	accounts := []account{}
	if err := userdata.Engine.Table("u_status").Cols("user_id", "rank").Asc("user_id").Find(&accounts); err != nil {
		ctx.JSON(http.StatusInternalServerError, gin.H{"error": "Could not read local accounts."})
		return
	}
	ctx.JSON(http.StatusOK, gin.H{"accounts": accounts})
}

func nativeSession(ctx *gin.Context) *userdata.Session {
	if !requireNativeLocal(ctx) {
		return nil
	}
	session, _ := ctx.MustGet("session").(*userdata.Session)
	if session == nil {
		ctx.JSON(http.StatusBadRequest, gin.H{"error": "Choose a local account first."})
	}
	return session
}

func credentialKeyPath() string { return filepath.Join(config.RootPath, managedcredential.KeyFile) }

func clientAddress(binding string) (string, string) {
	host, port, err := net.SplitHostPort(binding)
	if err != nil {
		return "", "Check the game server address in Server Settings."
	}
	if host == "" || host == "0.0.0.0" || host == "::" {
		return "http://" + net.JoinHostPort("127.0.0.1", port), "0.0.0.0 / :: is a listening address, not a client destination. On this device use the address above. On another device use this server device's LAN address and the same port."
	}
	return "http://" + net.JoinHostPort(host, port), "On another device, a loopback address points to that device itself. Use this server device's reachable LAN address and port."
}

func nativeConnection(ctx *gin.Context) {
	session := nativeSession(ctx)
	if session == nil {
		return
	}
	address, note := clientAddress(*config.Conf.ServerAddress)
	_, err := managedcredential.Reveal(session.Db, session.UserId, credentialKeyPath())
	result := gin.H{"user_id": session.UserId, "server_address": address, "binding_address": *config.Conf.ServerAddress, "address_note": note, "has_managed_password": err == nil}
	if public, readErr := os.ReadFile(filepath.Join(config.RootPath, "publickey.pem")); readErr == nil && len(public) < 65536 && strings.Contains(string(public), "PUBLIC KEY") {
		result["server_public_key"] = string(public)
	}
	ctx.JSON(http.StatusOK, result)
}

func nativePasswordSet(ctx *gin.Context) {
	session := nativeSession(ctx)
	if session == nil {
		return
	}
	if ctx.PostForm("confirm_password_change") != "yes" {
		ctx.JSON(http.StatusBadRequest, gin.H{"error": "Explicitly confirm changing the client login password."})
		return
	}
	password := ctx.PostForm("new_password")
	var err error
	if password == "" {
		password, err = managedcredential.Generate()
	}
	if err == nil {
		err = managedcredential.Set(session.Db, session.UserId, password, credentialKeyPath())
	}
	if err != nil {
		ctx.JSON(http.StatusBadRequest, gin.H{"error": "Could not save the password. Use 8–72 bytes and check that the private credential key is writable."})
		return
	}
	// Do not run gameplay/status/authentication finalizers: password changes
	// preserve progress, authorization keys and existing game sessions.
	session.SessionType = userdata.SessionTypeDirectDbWrite
	session.Finalize()
	ctx.JSON(http.StatusOK, gin.H{"has_managed_password": true})
}

func nativePasswordReveal(ctx *gin.Context) {
	session := nativeSession(ctx)
	if session == nil {
		return
	}
	password, err := managedcredential.Reveal(session.Db, session.UserId, credentialKeyPath())
	if err != nil {
		ctx.JSON(http.StatusConflict, gin.H{"error": "No current managed password is available. Old bcrypt passwords cannot be recovered; explicitly set or generate a new password."})
		return
	}
	ctx.JSON(http.StatusOK, gin.H{"password": password})
}

func init() {
	router.AddHandler("/webui/user", "GET", "/client_connection", func(ctx *gin.Context) {
		if !requireNativeLocal(ctx) {
			return
		}
		ctx.HTML(http.StatusOK, "logged_in_user.html", gin.H{"body": nativeConnectionHTML})
	})
	router.AddHandler("/webui/user", "GET", "/native_accounts", nativeAccounts)
	router.AddHandler("/webui/user", "POST", "/native_connection", nativeConnection)
	router.AddHandler("/webui/user", "POST", "/native_password/set", nativePasswordSet)
	router.AddHandler("/webui/user", "POST", "/native_password/reveal", nativePasswordReveal)
}
