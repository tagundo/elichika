//go:build elichika_inprocess

// Package iosbridge embeds the actual Elichika router and data services into
// one host process. It owns no application signals, subprocesses, or cwd.
package iosbridge

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"path/filepath"
	"strconv"
)

type Options struct {
	Schema          int    `json:"schema"`
	ResourcesRoot   string `json:"resources_root"`
	DataRoot        string `json:"data_root"`
	PacksRoot       string `json:"packs_root"`
	ListenAddress   string `json:"listen_address"`
	Region          string `json:"region"`
	Language        string `json:"language"`
	ReadyToken      string `json:"ready_token"`
	WebToken        string `json:"web_token"`
	LocalWebUIToken string `json:"local_webui_token,omitempty"`
}

func decodeJSON(input string, target any) error {
	if len(input) > 64*1024 {
		return fmt.Errorf("JSON input exceeds 64 KiB")
	}
	decoder := json.NewDecoder(bytes.NewBufferString(input))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return fmt.Errorf("expected one JSON object")
	}
	return nil
}

func parseOptions(input string) (Options, error) {
	var options Options
	if err := decodeJSON(input, &options); err != nil {
		return options, err
	}
	if options.Schema != 0 && options.Schema != 1 {
		return options, fmt.Errorf("unsupported schema")
	}
	if !filepath.IsAbs(options.DataRoot) {
		return options, fmt.Errorf("data_root must be absolute")
	}
	if options.ResourcesRoot != "" && !filepath.IsAbs(options.ResourcesRoot) {
		return options, fmt.Errorf("resources_root must be absolute")
	}
	if options.PacksRoot != "" && !filepath.IsAbs(options.PacksRoot) {
		return options, fmt.Errorf("packs_root must be absolute")
	}
	if options.ListenAddress == "" {
		options.ListenAddress = "127.0.0.1:8080"
	}
	host, port, err := net.SplitHostPort(options.ListenAddress)
	if err != nil {
		return options, fmt.Errorf("listen_address must be loopback IP:port")
	}
	ip := net.ParseIP(host)
	portNumber, portError := strconv.Atoi(port)
	lan := host == "0.0.0.0" && portNumber == 8080
	if ip == nil || (!ip.IsLoopback() && !lan) || portError != nil || portNumber < 0 || portNumber > 65535 {
		return options, fmt.Errorf("listen_address must be a loopback IP and port 0-65535, or opt-in 0.0.0.0:8080")
	}
	if options.Region != "" && options.Region != "gl" && options.Region != "jp" {
		return options, fmt.Errorf("region must be gl or jp")
	}
	switch options.Language {
	case "", "en", "ko", "zh", "ja":
	default:
		return options, fmt.Errorf("unsupported language")
	}
	if options.Region == "jp" && options.Language != "" && options.Language != "ja" {
		return options, fmt.Errorf("JP requires Japanese game data")
	}
	if options.WebToken == "" {
		options.WebToken = options.LocalWebUIToken
	}
	for _, token := range []*string{&options.ReadyToken, &options.WebToken} {
		if *token == "" {
			value := make([]byte, 16)
			if _, err := rand.Read(value); err != nil {
				return options, err
			}
			*token = hex.EncodeToString(value)
		}
		value, err := hex.DecodeString(*token)
		if err != nil || len(value) != 16 || hex.EncodeToString(value) != *token {
			return options, fmt.Errorf("tokens must be 32 lowercase hexadecimal characters")
		}
	}
	return options, nil
}
