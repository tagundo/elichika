//go:build elichika_inprocess

package iosbridge

import (
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
	"path/filepath"
)

func readPublicKey(path string) (*rsa.PublicKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return nil, fmt.Errorf("public key PEM is invalid")
	}
	var key any
	if block.Type == "RSA PUBLIC KEY" {
		key, err = x509.ParsePKCS1PublicKey(block.Bytes)
	} else {
		key, err = x509.ParsePKIXPublicKey(block.Bytes)
	}
	if err != nil {
		return nil, fmt.Errorf("public key DER is invalid")
	}
	public, ok := key.(*rsa.PublicKey)
	if !ok {
		return nil, fmt.Errorf("game public key must be RSA")
	}
	return public, nil
}

func validateKeys(options Options) error {
	public, err := readPublicKey(filepath.Join(options.DataRoot, "publickey.pem"))
	if err != nil {
		return fmt.Errorf("writable game public key: %w", err)
	}
	data, err := os.ReadFile(filepath.Join(options.DataRoot, "privatekey.pem"))
	if err != nil {
		return fmt.Errorf("writable game private key: %w", err)
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return fmt.Errorf("writable game private key PEM is invalid")
	}
	if block.Type != "PRIVATE KEY" {
		return fmt.Errorf("writable game private key must use PKCS#8 PRIVATE KEY PEM, as required by the game OAEP handler")
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return fmt.Errorf("writable game private key DER is invalid")
	}
	private, ok := key.(*rsa.PrivateKey)
	if !ok || !private.PublicKey.Equal(public) {
		return fmt.Errorf("writable game RSA private/public keys do not match")
	}
	if err := private.Validate(); err != nil {
		return fmt.Errorf("writable game RSA private key is invalid")
	}
	if options.ResourcesRoot != "" {
		seed, err := readPublicKey(filepath.Join(options.ResourcesRoot, "publickey.pem"))
		if err != nil {
			return fmt.Errorf("bundled game public key: %w", err)
		}
		if !public.Equal(seed) {
			return fmt.Errorf("writable game RSA key differs from the bundled client key; migrate the existing data key before launching the game")
		}
	}
	return nil
}
