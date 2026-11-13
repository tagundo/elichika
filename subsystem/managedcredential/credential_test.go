package managedcredential

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/crypto/bcrypt"
	_ "modernc.org/sqlite"
	"xorm.io/xorm"
)

type fixturePassword struct {
	UserId int32 `xorm:"pk 'user_id'"`
	Hash   []byte
}

func credentialFixture(t *testing.T) (*xorm.Engine, string) {
	t.Helper()
	dir := t.TempDir()
	engine, err := xorm.NewEngine("sqlite", filepath.Join(dir, "isolated.db"))
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	if err = engine.Table("u_pass_word").CreateTable(&fixturePassword{}); err != nil {
		t.Fatal(err)
	}
	if err = engine.Table(Table).CreateTable(&Record{}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { engine.Close() })
	return engine, filepath.Join(dir, KeyFile)
}

func TestLegacyHashIsNotRecoverableAndExplicitManagedPasswordPersists(t *testing.T) {
	engine, path := credentialFixture(t)
	type progress struct {
		UserId int32 `xorm:"pk 'user_id'"`
		Rank   int32
		Exp    int64
	}
	type authentication struct {
		UserId           int32 `xorm:"pk 'user_id'"`
		AuthorizationKey []byte
		SessionKey       []byte
		CommandId        int32
	}
	if err := engine.Table("u_status").CreateTable(&progress{}); err != nil {
		t.Fatal(err)
	}
	if err := engine.Table("u_authentication").CreateTable(&authentication{}); err != nil {
		t.Fatal(err)
	}
	state := progress{UserId: 77, Rank: 153, Exp: 987654321}
	auth := authentication{UserId: 77, AuthorizationKey: []byte("existing-authorization-key"), SessionKey: []byte("existing-session-key"), CommandId: 28}
	if _, err := engine.Table("u_status").Insert(&state); err != nil {
		t.Fatal(err)
	}
	if _, err := engine.Table("u_authentication").Insert(&auth); err != nil {
		t.Fatal(err)
	}
	hash, _ := bcrypt.GenerateFromPassword([]byte("legacy-secret"), bcrypt.MinCost)
	if _, err := engine.Table("u_pass_word").Insert(&fixturePassword{UserId: 77, Hash: hash}); err != nil {
		t.Fatal(err)
	}
	db := engine.NewSession()
	defer db.Close()
	if password, err := Reveal(db, 77, path); !errors.Is(err, ErrUnavailable) || password != "" {
		t.Fatal("legacy hash was presented as recoverable")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("read created an install key")
	}
	password, err := Generate()
	if err != nil {
		t.Fatal(err)
	}
	if err = db.Begin(); err != nil {
		t.Fatal(err)
	}
	if err = Set(db, 77, password, path); err != nil {
		t.Fatal(err)
	}
	if err = db.Commit(); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 || info.Size() != 32 {
		t.Fatal("install key was not private random 32 bytes")
	}
	var record Record
	if _, err = db.Table(Table).Where("user_id = ?", 77).Get(&record); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(record.Ciphertext, []byte(password)) {
		t.Fatal("database contains plaintext password")
	}
	db.Close()
	db = engine.NewSession()
	defer db.Close()
	got, err := Reveal(db, 77, path)
	if err != nil || got != password {
		t.Fatal("new managed credential did not survive a new session")
	}
	var current fixturePassword
	if _, err = db.Table("u_pass_word").Where("user_id = ?", 77).Get(&current); err != nil {
		t.Fatal(err)
	}
	if bcrypt.CompareHashAndPassword(current.Hash, []byte(password)) != nil || bcrypt.CompareHashAndPassword(current.Hash, []byte("legacy-secret")) == nil {
		t.Fatal("client hash was not explicitly replaced")
	}
	var gotState progress
	var gotAuth authentication
	if _, err = db.Table("u_status").Where("user_id = ?", 77).Get(&gotState); err != nil {
		t.Fatal(err)
	}
	if _, err = db.Table("u_authentication").Where("user_id = ?", 77).Get(&gotAuth); err != nil {
		t.Fatal(err)
	}
	if gotState != state || gotAuth.CommandId != auth.CommandId || !bytes.Equal(gotAuth.AuthorizationKey, auth.AuthorizationKey) || !bytes.Equal(gotAuth.SessionKey, auth.SessionKey) {
		t.Fatal("setting a login password changed progress or existing authentication/session keys")
	}
	otherHash, _ := bcrypt.GenerateFromPassword([]byte("changed-elsewhere"), bcrypt.MinCost)
	if _, err = db.Table("u_pass_word").Where("user_id = ?", 77).Update(passwordHash{Hash: otherHash}); err != nil {
		t.Fatal(err)
	}
	if value, err := Reveal(db, 77, path); !errors.Is(err, ErrUnavailable) || value != "" {
		t.Fatal("external password change did not invalidate reveal")
	}
}

func TestCredentialCannotBeMovedBetweenUsersOrReadWithAnotherInstallKey(t *testing.T) {
	engine, path := credentialFixture(t)
	db := engine.NewSession()
	defer db.Close()
	db.Begin()
	if err := Set(db, 1, "managed-secret-one", path); err != nil {
		t.Fatal(err)
	}
	if err := Set(db, 2, "managed-secret-two", path); err != nil {
		t.Fatal(err)
	}
	db.Commit()
	var one, two Record
	db.Table(Table).Where("user_id = ?", 1).Get(&one)
	db.Table(Table).Where("user_id = ?", 2).Get(&two)
	db.Table(Table).Where("user_id = ?", 2).Cols("ciphertext").Update(Record{Ciphertext: one.Ciphertext})
	if value, err := Reveal(db, 2, path); !errors.Is(err, ErrUnavailable) || value != "" {
		t.Fatal("cross-account ciphertext was revealed")
	}
	otherPath := filepath.Join(t.TempDir(), KeyFile)
	if _, err := installKey(otherPath, true); err != nil {
		t.Fatal(err)
	}
	if value, err := Reveal(db, 1, otherPath); !errors.Is(err, ErrUnavailable) || value != "" {
		t.Fatal("another install decrypted the password")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err := Reveal(db, 1, path); !errors.Is(err, ErrUnavailable) {
		t.Fatal("missing install key was silently regenerated")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("reveal replaced a missing install key")
	}
}

func TestPasswordWriteRollsBackAndRejectsUnsafeKeys(t *testing.T) {
	engine, path := credentialFixture(t)
	db := engine.NewSession()
	defer db.Close()
	db.Begin()
	if err := Set(db, 1, "rollback-secret", path); err != nil {
		t.Fatal(err)
	}
	db.Rollback()
	if value, err := Reveal(db, 1, path); !errors.Is(err, ErrUnavailable) || value != "" {
		t.Fatal("rollback retained a client credential")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if err := Set(db, 1, "some-new-password", path); err == nil {
		t.Fatal("world-readable key accepted")
	}
	if err := Set(db, 1, "short", path); err == nil {
		t.Fatal("short custom password accepted")
	}
}
