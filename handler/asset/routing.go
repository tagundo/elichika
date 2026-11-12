package asset

import (
	"elichika/assetdata"
	"elichika/config"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"unicode"
)

func validAssetPath(value string, nested bool) bool {
	if value == "" || (!nested && strings.Contains(value, "/")) {
		return false
	}
	for _, part := range strings.Split(value, "/") {
		if part == "" || len(part) > 256 || part == "." || part == ".." {
			return false
		}
		for _, character := range part {
			if !unicode.IsLetter(character) && !unicode.IsDigit(character) && !strings.ContainsRune("._-", character) {
				return false
			}
		}
	}
	return true
}

func escapedAssetPath(value string) string {
	parts := strings.Split(value, "/")
	for index := range parts {
		parts[index] = url.PathEscape(parts[index])
	}
	return strings.Join(parts, "/")
}

func validAssetHost(host string) bool {
	if host == "" || strings.HasSuffix(host, ":") || strings.ContainsAny(host, " /\\?#@%\t\r\n") {
		return false
	}
	parsed, err := url.Parse("http://" + host)
	if err != nil || parsed.Host != host || parsed.Hostname() == "" || parsed.User != nil {
		return false
	}
	if port := parsed.Port(); port != "" {
		if value, err := strconv.Atoi(port); err != nil || value < 1 || value > 65535 {
			return false
		}
	}
	hostname := parsed.Hostname()
	if net.ParseIP(hostname) != nil {
		return true
	}
	for _, label := range strings.Split(hostname, ".") {
		if label == "" || len(label) > 63 || strings.HasPrefix(label, "-") || strings.HasSuffix(label, "-") {
			return false
		}
		for _, letter := range label {
			if !(letter >= 'a' && letter <= 'z' || letter >= 'A' && letter <= 'Z' || letter >= '0' && letter <= '9' || letter == '-') {
				return false
			}
		}
	}
	return true
}

// Forwarding headers are capabilities of explicitly configured proxies, never
// of arbitrary clients (including games connecting over loopback).
func trustedAssetProxy(remote string) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		return false
	}
	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}
	for _, entry := range strings.Split(os.Getenv("ELICHIKA_TRUSTED_PROXIES"), ",") {
		entry = strings.TrimSpace(entry)
		if trusted := net.ParseIP(entry); trusted != nil && trusted.Equal(ip) {
			return true
		}
		if _, network, err := net.ParseCIDR(entry); err == nil && network.Contains(ip) {
			return true
		}
	}
	return false
}

func clientAssetBase(request *http.Request) (string, error) {
	proto, host := "http", request.Host
	if request.TLS != nil {
		proto = "https"
	}
	if trustedAssetProxy(request.RemoteAddr) {
		if values := request.Header.Values("X-Forwarded-Host"); len(values) == 1 && validAssetHost(values[0]) {
			host = values[0]
		}
		if values := request.Header.Values("X-Forwarded-Proto"); len(values) == 1 && (values[0] == "http" || values[0] == "https") {
			proto = values[0]
		}
	}
	if !validAssetHost(host) {
		return "", fmt.Errorf("invalid game-server host")
	}
	return proto + "://" + host + "/static", nil
}

func assetURLPort(value *url.URL) string {
	if value.Port() != "" {
		return value.Port()
	}
	if value.Scheme == "https" {
		return "443"
	}
	return "80"
}

// sourceCDNURL never invents an upstream. A self-referencing legacy override
// must be corrected explicitly rather than recursively proxying this server.
func sourceCDNURL(base, file string, request *http.Request) (string, error) {
	parsed, err := url.Parse(base)
	if err != nil || parsed == nil || (parsed.Scheme != "http" && parsed.Scheme != "https") ||
		!validAssetHost(parsed.Host) || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" ||
		!validAssetPath(file, true) {
		return "", fmt.Errorf("configure a valid original-game source CDN")
	}
	if request != nil {
		self, err := clientAssetBase(request)
		if err != nil {
			return "", err
		}
		own, _ := url.Parse(self)
		if strings.EqualFold(own.Hostname(), parsed.Hostname()) && assetURLPort(own) == assetURLPort(parsed) {
			return "", fmt.Errorf("the source CDN points to this game server; choose the default source CDN or your previous upstream")
		}
	}
	if config.Conf.ServerAddress != nil {
		listenHost, listenPort, err := net.SplitHostPort(*config.Conf.ServerAddress)
		if err == nil && listenPort == assetURLPort(parsed) {
			upstreamIP := net.ParseIP(parsed.Hostname())
			loopback := strings.EqualFold(parsed.Hostname(), "localhost") || upstreamIP != nil && upstreamIP.IsLoopback()
			listenIP := net.ParseIP(listenHost)
			if strings.EqualFold(listenHost, parsed.Hostname()) || loopback &&
				(listenHost == "" || listenHost == "0.0.0.0" || listenHost == "::" || listenHost == "localhost" || listenIP != nil && listenIP.IsLoopback()) {
				return "", fmt.Errorf("the source CDN points to this game server; choose an upstream source CDN")
			}
		}
	}
	return strings.TrimRight(parsed.String(), "/") + "/" + escapedAssetPath(file), nil
}

func cdnHTTPClient(request *http.Request) *http.Client {
	client := *httpClient
	client.CheckRedirect = func(next *http.Request, previous []*http.Request) error {
		if len(previous) >= 10 {
			return fmt.Errorf("too many source CDN redirects")
		}
		// Signed CDN redirect queries remain valid; only the destination is
		// checked here. A redirect must never re-enter this game server.
		target := *next.URL
		target.RawQuery, target.Fragment = "", ""
		if _, err := sourceCDNURL(target.String(), "redirect-check", request); err != nil {
			return err
		}
		if httpClient.CheckRedirect != nil {
			return httpClient.CheckRedirect(next, previous)
		}
		return nil
	}
	return &client
}

func packDownloadURL(pack, self string, request *http.Request) (string, error) {
	if !validAssetPath(pack, false) {
		return "", fmt.Errorf("invalid asset pack name")
	}
	data := assetdata.GetDownloadData(pack)
	if !validAssetPath(data.File, false) {
		return "", fmt.Errorf("invalid asset metapack name")
	}
	local := selfServeStatic()
	if !local {
		_, local = localPath(data.File)
	}
	base := strings.TrimRight(*config.Conf.CdnServer, "/")
	if local {
		base = self
	}
	if data.IsEntireFile {
		if local {
			return base + "/" + escapedAssetPath(pack), nil
		}
		return sourceCDNURL(base, pack, request)
	}
	capability := *config.Conf.CdnPartialFileCapability
	if local {
		capability = "mapped_file"
	}
	if !local && capability != "nothing" {
		if _, err := sourceCDNURL(base, pack, request); err != nil {
			return "", err
		}
	}
	switch capability {
	case "static_file":
		return base + "/" + escapedAssetPath(pack), nil
	case "mapped_file":
		return base + "_map/" + escapedAssetPath(pack), nil
	case "has_range_api":
		return fmt.Sprintf("%s_api?file=%s&start=%d&size=%d", base, url.QueryEscape(data.File), data.Start, data.Size), nil
	case "nothing":
		return self + "_virtual/" + escapedAssetPath(pack), nil
	default:
		return "", fmt.Errorf("invalid source CDN partial-file capability")
	}
}
