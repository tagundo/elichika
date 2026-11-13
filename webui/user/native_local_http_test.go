package user_test

import (
	"bytes"
	"elichika/client"
	"elichika/config"
	"elichika/generic"
	"elichika/nativeaccess"
	"elichika/readiness"
	"elichika/router"
	"elichika/subsystem/managedcredential"
	"elichika/userdata"
	"elichika/userdata/database"
	_ "elichika/webui/admin"
	"encoding/base64"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"xorm.io/xorm"
)

// Run through tests/run_go_tests.py (or its initialized-runtime wrapper). Locale
// initialization needs copied official databases; every account below is created
// in a separate temporary SQLite file and never uses the runtime's userdata.
func TestNativeLocalAccountAndAdminHTTP(t *testing.T) {
	if os.Getenv("ELICHIKA_TEST_RUNTIME") == "" {
		t.Skip("requires a disposable initialized ELICHIKA_TEST_RUNTIME")
	}
	const userID int32 = 123456789
	const legacyPassword = "synthetic-legacy-password"
	const newPassword = "SyntheticNewClientLoginPassword42"
	token := strings.Repeat("a7", 16)
	t.Setenv(nativeaccess.Environment, token)
	t.Setenv(readiness.Environment, strings.Repeat("c3", 16))
	privateRoot := t.TempDir()
	previousRoot, previousConfig := config.RootPath, config.Conf
	configured := *config.Conf
	binding, adminPassword, trust := "0.0.0.0:8080", "synthetic-admin-password", false
	configured.ServerAddress, configured.AdminPassword, configured.LocalTrustLoopback = &binding, &adminPassword, &trust
	config.Conf, config.RootPath = &configured, privateRoot+string(os.PathSeparator)
	t.Cleanup(func() { config.RootPath, config.Conf = previousRoot, previousConfig })
	for _, relative := range []string{"webui/user/login.html", "webui/admin/login.html", "webui/native_local.js", "webui/webui.css", "publickey.pem"} {
		contents, err := os.ReadFile(relative)
		if err != nil {
			t.Fatal(err)
		}
		target := filepath.Join(privateRoot, relative)
		if err = os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(target, contents, 0600); err != nil {
			t.Fatal(err)
		}
	}
	engine, err := xorm.NewEngine("sqlite", filepath.Join(t.TempDir(), "synthetic-userdata.db"))
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	database.InitTables(engine)
	previousEngine := userdata.Engine
	userdata.Engine = engine
	t.Cleanup(func() { userdata.Engine = previousEngine; engine.Close() })
	status := client.UserStatus{Rank: 42, Exp: 123456, GameMoney: 987654, TutorialPhase: 99, TutorialEndAt: 1234, LoginDays: 71}
	status.Name.DotUnderText = "Synthetic HTTP account"
	auth := database.UserAuthentication{AuthorizationKey: []byte("synthetic authorization key"), SessionKey: []byte("synthetic unchanged session"), AuthorizationCount: 17, CommandId: 23}
	legacyHash, err := bcrypt.GenerateFromPassword([]byte(legacyPassword), bcrypt.MinCost)
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range []struct {
		table string
		value any
	}{
		{"u_status", generic.UserIdWrapper[client.UserStatus]{UserId: userID, Object: &status}},
		{"u_authentication", generic.UserIdWrapper[database.UserAuthentication]{UserId: userID, Object: &auth}},
		{"u_pass_word", generic.UserIdWrapper[database.UserPassWord]{UserId: userID, Object: &database.UserPassWord{Hash: legacyHash}}},
	} {
		if _, err = engine.Table(row.table).Insert(row.value); err != nil {
			t.Fatal(err)
		}
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	// Nonmutating probes run the real user/admin initial authentication chain.
	router.AddHandler("/webui/user", "POST", "/native_http_test_probe", func(ctx *gin.Context) { ctx.Status(http.StatusNoContent) })
	router.AddHandler("/webui/admin", "POST", "/native_http_test_probe", func(ctx *gin.Context) { ctx.Status(http.StatusNoContent) })
	router.Router(r)
	server := httptest.NewServer(r)
	defer server.Close()
	jar, _ := cookiejar.New(nil)
	native := &http.Client{Jar: jar}
	ordinary := &http.Client{}
	type reply struct {
		status int
		body   []byte
	}
	request := func(client *http.Client, method, endpoint string, fields map[string]string, origin, capability string) reply {
		t.Helper()
		var body bytes.Buffer
		var contentType string
		if method == http.MethodPost {
			writer := multipart.NewWriter(&body)
			for key, value := range fields {
				if err := writer.WriteField(key, value); err != nil {
					t.Fatal(err)
				}
			}
			if err := writer.Close(); err != nil {
				t.Fatal(err)
			}
			contentType = writer.FormDataContentType()
		}
		req, err := http.NewRequest(method, server.URL+endpoint, &body)
		if err != nil {
			t.Fatal(err)
		}
		if contentType != "" {
			req.Header.Set("Content-Type", contentType)
		}
		if origin != "" {
			req.Header.Set("Origin", origin)
		}
		if capability != "" {
			req.Header.Set(nativeaccess.Header, capability)
		}
		response, err := client.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		contents, err := io.ReadAll(response.Body)
		if err != nil {
			t.Fatal(err)
		}
		return reply{response.StatusCode, contents}
	}
	decode := func(response reply, expectedStatus int) map[string]any {
		t.Helper()
		if response.status != expectedStatus {
			t.Fatalf("HTTP status %d, want %d (body omitted)", response.status, expectedStatus)
		}
		var result map[string]any
		if err := json.Unmarshal(response.body, &result); err != nil {
			t.Fatalf("invalid JSON response: %v", err)
		}
		return result
	}
	id := strconv.Itoa(int(userID))
	fields := map[string]string{"user_id": id}
	if got := request(ordinary, "GET", "/webui/user/native_accounts", nil, "", ""); got.status != http.StatusForbidden {
		t.Fatal("ordinary loopback browser read account directory")
	}
	if got := request(ordinary, "GET", "/webui/user/native_accounts", nil, "", strings.Repeat("c3", 16)); got.status != http.StatusForbidden {
		t.Fatal("public readiness nonce granted native authority")
	}
	remoteLogin := decode(request(ordinary, "POST", "/webui/user/login", map[string]string{"user_id": id, "user_password": "wrong"}, server.URL, ""), 200)
	if remoteLogin["error"] == nil {
		t.Fatal("ordinary account login accepted wrong password")
	}
	remoteLogin = decode(request(ordinary, "POST", "/webui/user/login", map[string]string{"user_id": id, "user_password": legacyPassword}, server.URL, ""), 200)
	if remoteLogin["error"] != nil || remoteLogin["response"] != base64.StdEncoding.EncodeToString(auth.SessionKey) {
		t.Fatal("ordinary password login changed behavior")
	}
	bootstrap := decode(request(native, "GET", "/webui/admin/native_access", nil, "", token), 200)
	if bootstrap["native_local"] != true {
		t.Fatal("owned native bootstrap did not authorize")
	}
	directory := request(native, "GET", "/webui/user/native_accounts", nil, "", "")
	accounts := decode(directory, 200)["accounts"].([]any)
	if len(accounts) != 1 || accounts[0].(map[string]any)["user_id"] != float64(userID) || bytes.Contains(directory.body, []byte("password")) || bytes.Contains(directory.body, legacyHash) {
		t.Fatal("account picker did not return exactly the synthetic public account ID")
	}
	clickLogin := decode(request(native, "POST", "/webui/user/login", fields, server.URL, ""), 200)
	if clickLogin["error"] != nil || clickLogin["response"] != base64.StdEncoding.EncodeToString(auth.SessionKey) {
		t.Fatal("native click login required a password or rotated the existing session")
	}
	if got := request(ordinary, "POST", "/webui/user/native_http_test_probe", fields, server.URL, ""); got.status != http.StatusForbidden {
		t.Fatal("ordinary browser bypassed user session authentication")
	}
	if got := request(native, "POST", "/webui/user/native_http_test_probe", fields, "https://foreign.example", ""); got.status != http.StatusForbidden {
		t.Fatal("foreign-origin native request bypassed boundary")
	}
	if got := request(native, "POST", "/webui/user/native_http_test_probe", fields, "", ""); got.status != http.StatusForbidden {
		t.Fatal("native write without Origin bypassed boundary")
	}
	if got := request(native, "POST", "/webui/user/native_http_test_probe", fields, server.URL, ""); got.status != http.StatusNoContent {
		t.Fatal("native account session probe failed")
	}
	connection := decode(request(native, "POST", "/webui/user/native_connection", fields, server.URL, ""), 200)
	if connection["has_managed_password"] != false || connection["server_address"] != "http://127.0.0.1:8080" || connection["password"] != nil {
		t.Fatal("connection metadata exposed a password or wildcard client destination")
	}
	if got := request(native, "POST", "/webui/user/native_password/reveal", fields, server.URL, ""); got.status != http.StatusConflict {
		t.Fatal("legacy bcrypt password was claimed to be recoverable")
	}
	if got := request(native, "POST", "/webui/user/native_password/set", fields, server.URL, ""); got.status != http.StatusBadRequest {
		t.Fatal("password changed without explicit confirmation")
	}
	if _, err = os.Stat(filepath.Join(privateRoot, managedcredential.KeyFile)); !os.IsNotExist(err) {
		t.Fatal("read-only login/metadata or unconfirmed action created an install key")
	}
	changed := decode(request(native, "POST", "/webui/user/native_password/set", map[string]string{"user_id": id, "confirm_password_change": "yes", "new_password": newPassword}, server.URL, ""), 200)
	if changed["has_managed_password"] != true || changed["password"] != nil {
		t.Fatal("password set did not remain masked")
	}
	revealed := decode(request(native, "POST", "/webui/user/native_password/reveal", fields, server.URL, ""), 200)
	if revealed["password"] != newPassword {
		t.Fatal("explicitly saved password did not survive a new HTTP request")
	}
	info, err := os.Stat(filepath.Join(privateRoot, managedcredential.KeyFile))
	if err != nil || info.Mode().Perm() != 0600 || info.Size() != 32 {
		t.Fatal("managed credential install key is not private 32-byte material")
	}
	var gotStatus client.UserStatus
	var gotAuth database.UserAuthentication
	var encrypted managedcredential.Record
	if _, err = engine.Table("u_status").Where("user_id = ?", userID).Get(&gotStatus); err != nil {
		t.Fatal(err)
	}
	if _, err = engine.Table("u_authentication").Where("user_id = ?", userID).Get(&gotAuth); err != nil {
		t.Fatal(err)
	}
	if _, err = engine.Table(managedcredential.Table).Where("user_id = ?", userID).Get(&encrypted); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(gotStatus, status) || !reflect.DeepEqual(gotAuth, auth) {
		t.Fatal("native login/password action changed existing progress or authentication")
	}
	if len(encrypted.Ciphertext) == 0 || bytes.Contains(encrypted.Ciphertext, []byte(newPassword)) {
		t.Fatal("managed password was not encrypted at rest")
	}
	outsideHash, _ := bcrypt.GenerateFromPassword([]byte("synthetic-external-change"), bcrypt.MinCost)
	if _, err = engine.Table("u_pass_word").Where("user_id = ?", userID).Update(database.UserPassWord{Hash: outsideHash}); err != nil {
		t.Fatal(err)
	}
	if got := request(native, "POST", "/webui/user/native_password/reveal", fields, server.URL, ""); got.status != http.StatusConflict {
		t.Fatal("external password change did not invalidate saved credential")
	}
	adminWrong := decode(request(ordinary, "POST", "/webui/admin/login", map[string]string{"admin_password": "wrong"}, server.URL, ""), 200)
	if adminWrong["error"] == nil {
		t.Fatal("ordinary admin login accepted wrong password")
	}
	adminLogin := decode(request(ordinary, "POST", "/webui/admin/login", map[string]string{"admin_password": adminPassword}, server.URL, ""), 200)
	adminKey, ok := adminLogin["response"].(string)
	if !ok || adminLogin["error"] != nil {
		t.Fatal("ordinary admin password login failed")
	}
	nativeAdmin := decode(request(native, "POST", "/webui/admin/login", nil, server.URL, ""), 200)
	if nativeAdmin["response"] != "native-local" {
		t.Fatal("native admin login required a password or leaked a remote session key")
	}
	if got := request(ordinary, "POST", "/webui/admin/native_http_test_probe", nil, server.URL, ""); got.status != http.StatusForbidden {
		t.Fatal("ordinary admin write bypassed authentication")
	}
	if got := request(ordinary, "POST", "/webui/admin/native_http_test_probe", map[string]string{"admin_session_key": adminKey}, server.URL, ""); got.status != http.StatusNoContent {
		t.Fatal("native login invalidated an existing remote admin session")
	}
	if got := request(native, "POST", "/webui/admin/native_http_test_probe", nil, server.URL, ""); got.status != http.StatusNoContent {
		t.Fatal("native admin write required a typed password")
	}
	settings := request(native, "GET", "/webui/admin/config_editor", nil, "", "")
	if settings.status != 200 || !bytes.Contains(settings.body, []byte("config_form")) {
		t.Fatal("native server settings did not open the editable form")
	}
	t.Log("actual HTTP: synthetic DB directory/click-login, explicit encrypted password, external-change invalidation, native admin and ordinary authentication passed")
}
