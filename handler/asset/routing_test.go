package asset

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"elichika/assetdata"
	"elichika/config"
	"elichika/encrypt"
	"elichika/locale"
	"elichika/userdata"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"xorm.io/xorm"
)

func TestClientAssetHostUsesReachableRequestAndExplicitProxyTrust(t *testing.T) {
	t.Setenv("ELICHIKA_TRUSTED_PROXIES", "")
	request := httptest.NewRequest("GET", "http://192.0.2.25:8080/", nil)
	request.RemoteAddr = "127.0.0.1:12345"
	request.Header.Set("X-Forwarded-Host", "attacker.invalid")
	request.Header.Set("X-Forwarded-Proto", "javascript")
	if got, err := clientAssetBase(request); err != nil || got != "http://192.0.2.25:8080/static" {
		t.Fatalf("untrusted forwarding changed game address: %q %v", got, err)
	}
	t.Setenv("ELICHIKA_TRUSTED_PROXIES", "127.0.0.1/32")
	request.Header.Set("X-Forwarded-Host", "game.example.org:8443")
	request.Header.Set("X-Forwarded-Proto", "https")
	if got, err := clientAssetBase(request); err != nil || got != "https://game.example.org:8443/static" {
		t.Fatalf("explicit reverse proxy failed: %q %v", got, err)
	}
	request.RemoteAddr = "198.51.100.1:12345"
	if got, err := clientAssetBase(request); err != nil || got != "http://192.0.2.25:8080/static" {
		t.Fatalf("public peer spoofed trusted forwarding: %q %v", got, err)
	}
	request.TLS = &tls.ConnectionState{}
	request.Host = "[2001:db8::25]:8443"
	if got, err := clientAssetBase(request); err != nil || got != "https://[2001:db8::25]:8443/static" {
		t.Fatalf("IPv6/TLS address failed: %q %v", got, err)
	}
}

func TestAssetRoutingRejectsURLInjectionAndSelfUpstream(t *testing.T) {
	for _, host := range []string{"", "user@host", "host/path", "host?query", "host#fragment", "host:0", "host:65536", "host:", "host\r\nInjected: x", "a,b"} {
		if validAssetHost(host) {
			t.Errorf("unsafe host accepted: %q", host)
		}
	}
	for _, name := range []string{"../config.json", "name?url=http://bad", "name#hash", "name%2fetc", "folder\\file", ".", "..", "a/b"} {
		if validAssetPath(name, false) {
			t.Errorf("unsafe pack accepted: %q", name)
		}
	}
	previous := config.Conf
	t.Cleanup(func() { config.Conf = previous })
	listen := "0.0.0.0:8080"
	config.Conf = &config.RuntimeConfig{ServerAddress: &listen}
	for _, base := range []string{"http://127.0.0.1:8080/static", "http://localhost:8080/static", "http://[::1]:8080/static", "file:///etc", "http://user:pass@example.org/static", "https://example.org/static?url=x"} {
		if _, err := sourceCDNURL(base, "pack", nil); err == nil {
			t.Errorf("self/invalid upstream accepted: %q", base)
		}
	}
	request := httptest.NewRequest("GET", "https://game.example.org/static/pack", nil)
	if _, err := sourceCDNURL("https://game.example.org/static", "pack", request); err == nil {
		t.Fatal("reverse-proxy self-origin loop was accepted")
	}
	if got, err := sourceCDNURL("https://original.example.org/custom/", "pack", request); err != nil || got != "https://original.example.org/custom/pack" {
		t.Fatalf("owner's external source changed: %q %v", got, err)
	}
}

func TestSourceCDNRedirectCannotReenterGameServer(t *testing.T) {
	previous := config.Conf
	t.Cleanup(func() { config.Conf = previous })
	requests := 0
	game := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		w.Write([]byte("must never be fetched through a CDN redirect"))
	}))
	defer game.Close()
	gameURL, _ := url.Parse(game.URL)
	listen := gameURL.Host
	config.Conf = &config.RuntimeConfig{ServerAddress: &listen}
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, game.URL+"/static/recursive", http.StatusFound)
	}))
	defer source.Close()
	if response, err := cdnHTTPClient(nil).Get(source.URL); err == nil {
		response.Body.Close()
		t.Fatal("a source CDN redirect re-entered the game server")
	}
	if requests != 0 {
		t.Fatal("the loop target was contacted before redirect validation")
	}
}

func TestSelfUpstreamAliasIsRejectedBeforeTakingCacheLock(t *testing.T) {
	previousConfig, previousStatic := config.Conf, config.StaticDataPath
	t.Cleanup(func() { config.Conf, config.StaticDataPath = previousConfig, previousStatic })
	root := t.TempDir()
	cdn, cache, listen := "http://proxy-alias.example:8080/static", true, "127.0.0.1:8080"
	config.Conf = &config.RuntimeConfig{CdnServer: &cdn, CdnCache: &cache, CdnCacheDir: &root, ServerAddress: &listen}
	config.StaticDataPath = root + "/static/"
	name := "private-self-alias-lock-test"
	lock := cacheLockFor(name)
	lock.Lock()
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest("GET", "http://proxy-alias.example:8080/static/"+name, nil)
	ctx.Params = gin.Params{{Key: "fileName", Value: "/" + name}}
	done := make(chan struct{})
	go func() { staticWhole(ctx); close(done) }()
	select {
	case <-done:
		lock.Unlock()
		if ctx.Writer.Status() != http.StatusBadGateway {
			t.Fatalf("self alias status: %d", ctx.Writer.Status())
		}
	case <-time.After(300 * time.Millisecond):
		lock.Unlock()
		<-done
		t.Fatal("self alias waited on the recursive cache lock before validation")
	}
}

func TestLockedRangeAndMetapackDownloadsKeepClientOriginForRedirects(t *testing.T) {
	previousConfig, previousStatic, previousClient := config.Conf, config.StaticDataPath, httpClient
	t.Cleanup(func() {
		config.Conf, config.StaticDataPath, httpClient = previousConfig, previousStatic, previousClient
	})
	targetContacts := 0
	game := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		targetContacts++
		w.Write([]byte("recursive target must not be contacted"))
	}))
	defer game.Close()
	gameURL, _ := url.Parse(game.URL)
	_, port, _ := net.SplitHostPort(gameURL.Host)
	alias := "192.0.2.25:" + port
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://"+alias+"/static/recursive-metapack", http.StatusFound)
	}))
	defer upstream.Close()
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		if address == alias {
			address = gameURL.Host
		}
		return (&net.Dialer{}).DialContext(ctx, network, address)
	}}
	defer transport.CloseIdleConnections()
	httpClient = &http.Client{Transport: transport}
	root := t.TempDir()
	cdn, enabled, listen := upstream.URL, true, "0.0.0.0:"+port
	config.Conf = &config.RuntimeConfig{CdnServer: &cdn, CdnCache: &enabled, CdnCacheDir: &root, ServerAddress: &listen}
	config.StaticDataPath = root + "/static/"
	for index, path := range []string{"/static/whole-with-range", "/static_map/partial-in-metapack"} {
		request := httptest.NewRequest("GET", "http://"+alias+path, nil)
		request.Header.Set("Range", "bytes=0-3")
		name := "private-origin-retention-" + string(rune('a'+index))
		result := ensureLocalFile(name, request)
		if _, err := os.Stat(result); !os.IsNotExist(err) {
			t.Fatal("a redirected self-pack was stored")
		}
	}
	if targetContacts != 0 {
		t.Fatal("locked download lost its request origin and contacted the listener alias")
	}
}

type installedModPack struct {
	Name            string `json:"name"`
	Path            string `json:"path"`
	SHA256          string `json:"sha256"`
	Role            string `json:"role"`
	PlaintextSHA256 string `json:"plaintext_sha256"`
}

type installedCDNFixture struct {
	Root              string             `json:"root"`
	AssetDB           string             `json:"asset_db"`
	PacksDir          string             `json:"packs_dir"`
	ConfigPath        string             `json:"config_path"`
	ConfigSHA256      string             `json:"config_sha256"`
	SourceCDN         string             `json:"source_cdn"`
	ModPacks          []installedModPack `json:"mod_packs"`
	HQActualCLI       bool               `json:"hq_actual_cli_installed"`
	HQRendererReceipt json.RawMessage    `json:"hq_renderer_receipt"`
	OriginalPacks     []struct {
		Name        string
		BytesBase64 string `json:"bytes_base64"`
		SHA256      string
	} `json:"original_packs"`
}

func TestSelectiveCDNRealInstalledCostumeProtocol(t *testing.T) {
	_, source, _, _ := runtime.Caller(0)
	repo := filepath.Clean(filepath.Join(filepath.Dir(source), "../.."))
	root := t.TempDir()
	var fixture installedCDNFixture
	manifest := os.Getenv("ELICHIKA_CDN_TEST_INSTALLED_FIXTURE")
	preinstalled := manifest != ""
	if preinstalled {
		raw, err := os.ReadFile(manifest)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(raw, &fixture); err != nil {
			t.Fatal(err)
		}
	}
	var upstreamMu sync.Mutex
	upstreamFiles := map[string][]byte{}
	upstreamReads := []string{}
	upstream := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamMu.Lock()
		upstreamReads = append(upstreamReads, r.URL.Path)
		raw, exists := upstreamFiles[strings.TrimPrefix(r.URL.Path, "/static/")]
		upstreamMu.Unlock()
		if !exists {
			http.NotFound(w, r)
			return
		}
		http.ServeContent(w, r, "pack", time.Time{}, bytes.NewReader(raw))
	}))
	if preinstalled {
		address, err := url.Parse(fixture.SourceCDN)
		if err != nil || address.Scheme != "http" || address.Hostname() != "127.0.0.1" {
			t.Fatal("preinstalled fixture must use its private loopback CDN")
		}
		listener, err := net.Listen("tcp", address.Host)
		if err != nil {
			t.Fatal(err)
		}
		upstream.Listener.Close()
		upstream.Listener = listener
	}
	upstream.Start()
	defer upstream.Close()
	python := os.Getenv("ELICHIKA_CDN_TEST_PYTHON")
	if python == "" {
		python = "python3"
	}
	if !preinstalled {
		manifest = filepath.Join(root, "fixture.json")
		command := exec.Command(python, "-B", filepath.Join(repo, "tests/test_added_content_cdn_protocol.py"),
			"--fixture-root", filepath.Join(root, "installed"), "--manifest", manifest, "--source-cdn", upstream.URL+"/static")
		command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1")
		if os.Getenv("ELICHIKA_CDN_TEST_HQ_BROWSER") == "1" {
			command = exec.Command("node", filepath.Join(repo, "tests/adminui_costume_thumbnail_install_browser.js"),
				"--fixture-root", filepath.Join(root, "installed"), "--manifest", manifest, "--source-cdn", upstream.URL+"/static")
			artifacts := filepath.Join(root, "hq-install")
			if evidence := os.Getenv("ELICHIKA_CDN_TEST_EVIDENCE"); evidence != "" {
				artifacts = filepath.Join(filepath.Dir(evidence), "genuine-hq-install")
			}
			command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1", "ELICHIKA_CDN_TEST_PYTHON="+python, "EVIDENCE_DIR="+artifacts)
		}
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("real costume installation failed: %v\n%s", err, output)
		}
		raw, err := os.ReadFile(manifest)
		if err != nil {
			t.Fatal(err)
		}
		if err = json.Unmarshal(raw, &fixture); err != nil {
			t.Fatal(err)
		}
	}
	if fixture.SourceCDN != upstream.URL+"/static" {
		t.Fatal("the fixture source CDN changed between installation and download")
	}
	if len(fixture.ModPacks) == 0 {
		t.Fatal("actual installer published no packs")
	}
	if os.Getenv("ELICHIKA_CDN_TEST_HQ_BROWSER") == "1" || preinstalled {
		var receipt struct {
			SHA256 string `json:"sha256"`
		}
		if err := json.Unmarshal(fixture.HQRendererReceipt, &receipt); err != nil || !fixture.HQActualCLI || len(fixture.ModPacks) != 2 {
			t.Fatal("genuine HQ render/CLI body+thumbnail fixture is incomplete")
		}
		matched := false
		for _, pack := range fixture.ModPacks {
			if pack.Role == "thumbnail" && pack.PlaintextSHA256 == receipt.SHA256 {
				matched = true
			}
		}
		if !matched {
			t.Fatal("installed thumbnail PNG does not match the actual renderer receipt")
		}
	}
	for _, pack := range fixture.OriginalPacks {
		data, err := base64.StdEncoding.DecodeString(pack.BytesBase64)
		if err != nil {
			t.Fatal(err)
		}
		upstreamFiles[pack.Name] = data
	}
	configBefore, err := os.ReadFile(fixture.ConfigPath)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(configBefore)
	if hex.EncodeToString(digest[:]) != fixture.ConfigSHA256 {
		t.Fatal("installer changed source config bytes")
	}
	previousConfig, previousStatic, previousRoot := config.Conf, config.StaticDataPath, config.RootPath
	previousPack, previousMeta, previousLocale := assetdata.Pack, assetdata.Metapack, assetdata.NameToLocale
	t.Cleanup(func() {
		config.Conf, config.StaticDataPath, config.RootPath = previousConfig, previousStatic, previousRoot
		assetdata.Pack, assetdata.Metapack, assetdata.NameToLocale = previousPack, previousMeta, previousLocale
		packIndex, packIndexOnce = nil, sync.Once{}
	})
	assetdata.Pack, assetdata.Metapack, assetdata.NameToLocale = map[string]*assetdata.PackType{}, map[string]*assetdata.MetapackType{}, map[string]string{}
	engine, err := xorm.NewEngine("sqlite", fixture.AssetDB)
	if err != nil {
		t.Fatal(err)
	}
	defer engine.Close()
	assetdata.Init("en", engine)
	cdn, capability, cache, listen := upstream.URL+"/static", "nothing", false, "127.0.0.1:1"
	config.Conf = &config.RuntimeConfig{CdnServer: &cdn, CdnPartialFileCapability: &capability, CdnCache: &cache,
		CdnCacheDir: &fixture.PacksDir, ServerAddress: &listen}
	config.StaticDataPath, config.RootPath = filepath.Join(fixture.Root, "static")+"/", fixture.Root+"/"
	packIndex, packIndexOnce = nil, sync.Once{}
	router := gin.New()
	router.POST("/asset/getPackUrl", func(ctx *gin.Context) {
		body, err := io.ReadAll(ctx.Request.Body)
		if err != nil {
			t.Fatal(err)
		}
		message := json.RawMessage(body)
		ctx.Set("reqBody", &message)
		ctx.Set("session", (*userdata.Session)(nil))
		ctx.Set("sign_key", []byte("private-fixture-response-sign-key"))
		ctx.Set("locale", &locale.Locale{MasterVersion: "private-cdn-fixture"})
		ctx.Set("ep", "/asset/getPackUrl")
		getPackUrl(ctx)
	})
	router.GET("/static/*fileName", staticWhole)
	router.GET("/static_map/:fileName", staticMap)
	router.GET("/static_virtual/:fileName", staticVirtual)
	local := httptest.NewServer(router)
	defer local.Close()
	localURL, _ := url.Parse(local.URL)
	listen = localURL.Host
	transfers := []map[string]any{}
	getURLs := func(names []string, remoteHost string) []string {
		body, _ := json.Marshal(map[string]any{"pack_names": names})
		request, _ := http.NewRequest("POST", local.URL+"/asset/getPackUrl", bytes.NewReader(body))
		if remoteHost != "" {
			request.Host = remoteHost
		}
		request.Header.Set("Content-Type", "application/json")
		response, err := http.DefaultClient.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		payload, _ := io.ReadAll(response.Body)
		if response.StatusCode != 200 {
			t.Fatalf("pack URL protocol failed (%d): %s", response.StatusCode, payload)
		}
		var envelope []json.RawMessage
		if err := json.Unmarshal(payload, &envelope); err != nil || len(envelope) != 5 {
			t.Fatalf("invalid signed game envelope: %s", payload)
		}
		var answer struct {
			URLs []string `json:"url_list"`
		}
		if err := json.Unmarshal(envelope[3], &answer); err != nil || len(answer.URLs) != len(names) {
			t.Fatalf("invalid URL list: %s", payload)
		}
		var signature string
		if err := json.Unmarshal(envelope[4], &signature); err != nil {
			t.Fatal(err)
		}
		signed := strings.Join([]string{string(envelope[0]), string(envelope[1]), string(envelope[2]), string(envelope[3])}, ",")
		if signature != encrypt.HMAC_SHA1_Encrypt([]byte("/asset/getPackUrl "+signed), []byte("private-fixture-response-sign-key")) {
			t.Fatal("the actual game-protocol response signature is invalid")
		}
		return answer.URLs
	}
	fetch := func(target string, want []byte, status int) {
		response, err := http.Get(target)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		got, _ := io.ReadAll(response.Body)
		if response.StatusCode != status || status == 200 && !bytes.Equal(got, want) {
			t.Fatalf("client fetch failed %s: status=%d bytes=%d", target, response.StatusCode, len(got))
		}
		digest := sha256.Sum256(got)
		transfers = append(transfers, map[string]any{"url": target, "status": response.StatusCode,
			"bytes": len(got), "sha256": hex.EncodeToString(digest[:]), "cache_enabled": cache})
	}
	mod := fixture.ModPacks[0]
	modNames, modBytes := []string{}, map[string][]byte{}
	for _, pack := range fixture.ModPacks {
		if assetdata.Pack[pack.Name] == nil {
			t.Fatal("the genuine installed pack is missing from the real catalog: " + pack.Name)
		}
		data, err := os.ReadFile(pack.Path)
		if err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256(data)
		if hex.EncodeToString(digest[:]) != pack.SHA256 {
			t.Fatal("installed pack hash mismatch")
		}
		modNames, modBytes[pack.Name] = append(modNames, pack.Name), data
	}
	names := append([]string{"original-loose"}, modNames...)
	names = append(names, "original-slice", "missing-original", "cached-original")
	sliceIndex := len(modNames) + 1
	for _, enabled := range []bool{false, true} {
		cache = enabled
		urls := getURLs(names, "")
		for index, name := range modNames {
			if !strings.HasPrefix(urls[index+1], local.URL+"/static/") {
				t.Fatalf("new pack was not routed to Elichika: %v", urls)
			}
			fetch(urls[index+1], modBytes[name], 200)
		}
		if !enabled && !strings.HasPrefix(urls[0], upstream.URL+"/static/") {
			t.Fatal("cache OFF replaced owner's original CDN")
		}
		if enabled && !strings.HasPrefix(urls[0], local.URL+"/static/") {
			t.Fatal("cache ON did not retain local cache behavior")
		}
		fetch(urls[0], upstreamFiles["original-loose"], 200)
		slice := assetdata.GetDownloadData("original-slice")
		fetch(urls[sliceIndex], upstreamFiles[slice.File][slice.Start:slice.Start+slice.Size], 200)
		fetch(urls[sliceIndex+1], nil, 404)
		if !strings.HasPrefix(urls[sliceIndex+2], local.URL+"/static/") {
			t.Fatal("an explicitly downloaded original cache was ignored")
		}
		fetch(urls[sliceIndex+2], upstreamFiles["cached-original"], 200)
	}
	remote := getURLs(modNames, "192.0.2.25:8080")
	for index, name := range modNames {
		if remote[index] != "http://192.0.2.25:8080/static/"+escapedAssetPath(name) {
			t.Fatalf("remote game got loopback address: %v", remote)
		}
	}
	after, _ := os.ReadFile(fixture.ConfigPath)
	if !bytes.Equal(after, configBefore) {
		t.Fatal("URL routing or cache changed configuration on disk")
	}
	upstreamMu.Lock()
	reads := append([]string{}, upstreamReads...)
	upstreamMu.Unlock()
	for _, path := range reads {
		for _, name := range modNames {
			if strings.Contains(path, name) {
				t.Fatal("installed mod was requested from original CDN")
			}
		}
	}
	if len(reads) == 0 {
		t.Fatal("no actual upstream transfers occurred")
	}
	if evidence := os.Getenv("ELICHIKA_CDN_TEST_EVIDENCE"); evidence != "" {
		payload, err := json.MarshalIndent(map[string]any{
			"status": "PASS", "scope": "Actual neutral serialized-Unity costume installer, real SQLite catalog, genuine signed GetPackUrl handler and HTTP downloads of its returned URLs. Test middleware supplies a private session/signing context; actual game UI was not launched.",
			"source_cdn": cdn, "configuration_sha256": fixture.ConfigSHA256, "configuration_bytes_unchanged": true,
			"installed_mod": mod, "installed_catalog_loaded": true, "response_hmac_verified": true,
			"installed_mods": fixture.ModPacks, "genuine_hq_browser_and_cli": fixture.HQActualCLI, "hq_renderer_receipt": fixture.HQRendererReceipt,
			"transfers": transfers, "upstream_requests": reads, "mod_requested_from_upstream": false,
			"remote_device_mod_url": remote[0], "external_network_access": false,
		}, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(filepath.Dir(evidence), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(evidence, payload, 0644); err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("real installer pack %s SHA256=%s; signed GetPackUrl mixed hosts, cache OFF/ON, original range, missing original, remote Host and unchanged config verified; upstream requests=%v", mod.Name, mod.SHA256, reads)
}
