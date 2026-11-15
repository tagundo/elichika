//go:build elichika_inprocess

package iosbridge

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeTestKeys(t *testing.T, root string, key *rsa.PrivateKey) {
	t.Helper()
	private, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	public, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range map[string][]byte{
		"privatekey.pem": pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: private}),
		"publickey.pem":  pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: public}),
	} {
		if err := os.WriteFile(filepath.Join(root, name), data, 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestKeysRejectWritablePairAndBundledClientMismatches(t *testing.T) {
	root, seed := t.TempDir(), t.TempDir()
	first, err := rsa.GenerateKey(rand.Reader, 1024)
	if err != nil {
		t.Fatal(err)
	}
	second, err := rsa.GenerateKey(rand.Reader, 1024)
	if err != nil {
		t.Fatal(err)
	}
	writeTestKeys(t, root, first)
	writeTestKeys(t, seed, first)
	options := Options{DataRoot: root, ResourcesRoot: seed}
	if err := validateKeys(options); err != nil {
		t.Fatal(err)
	}
	pkcs1 := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(first)})
	if err := os.WriteFile(filepath.Join(root, "privatekey.pem"), pkcs1, 0600); err != nil {
		t.Fatal(err)
	}
	if err := validateKeys(options); err == nil || !strings.Contains(err.Error(), "PKCS#8") {
		t.Fatalf("PKCS#1 accepted by PKCS#8 game handler gate: %v", err)
	}
	writeTestKeys(t, root, first)
	writeTestKeys(t, seed, second)
	if err := validateKeys(options); err == nil || !strings.Contains(err.Error(), "bundled client key") {
		t.Fatalf("expected seed mismatch, got %v", err)
	}
	public, err := os.ReadFile(filepath.Join(seed, "publickey.pem"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "publickey.pem"), public, 0600); err != nil {
		t.Fatal(err)
	}
	if err := validateKeys(options); err == nil || !strings.Contains(err.Error(), "do not match") {
		t.Fatalf("expected pair mismatch, got %v", err)
	}
}

func TestConfiguredAsianTimezonesResolve(t *testing.T) {
	for _, name := range []string{"Asia/Tokyo", "Asia/Seoul"} {
		zone, err := time.LoadLocation(name)
		if err != nil {
			t.Fatal(err)
		}
		_, offset := time.Date(2026, 11, 15, 12, 0, 0, 0, zone).Zone()
		if offset != 9*60*60 {
			t.Fatalf("%s offset=%d", name, offset)
		}
	}
}
