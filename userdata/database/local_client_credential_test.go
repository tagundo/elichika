package database

import (
	"bytes"
	"elichika/subsystem/managedcredential"
	"path/filepath"
	"testing"

	"xorm.io/xorm"
)

func TestExistingAccountDatabaseAddsManagedCredentialTableWithoutChangingAuthentication(t *testing.T) {
	engine, err := xorm.NewEngine("sqlite", filepath.Join(t.TempDir(), "existing-userdata.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer engine.Close()
	engine.SetMaxOpenConns(1)
	// Start with the legacy account tables and bytes, then run the same
	// initializer used at startup twice to check an existing installation.
	for _, table := range []string{"u_pass_word", "u_authentication"} {
		if err = engine.Table(table).CreateTable(UserDataTableNameToInterface[table]); err != nil {
			t.Fatal(err)
		}
	}
	type legacyPassword struct {
		UserId int32 `xorm:"pk 'user_id'"`
		Hash   []byte
	}
	type legacyAuthentication struct {
		UserId             int32 `xorm:"pk 'user_id'"`
		UserAuthentication `xorm:"extends"`
	}
	hash := []byte("unchanged-legacy-bcrypt-bytes")
	auth := UserAuthentication{AuthorizationKey: []byte("authorization"), SessionKey: []byte("session"), AuthorizationCount: 8, CommandId: 21}
	if _, err = engine.Table("u_pass_word").Insert(&legacyPassword{UserId: 123, Hash: hash}); err != nil {
		t.Fatal(err)
	}
	if _, err = engine.Table("u_authentication").Insert(&legacyAuthentication{UserId: 123, UserAuthentication: auth}); err != nil {
		t.Fatal(err)
	}
	InitTables(engine)
	InitTables(engine)
	exists, err := engine.IsTableExist(managedcredential.Table)
	if err != nil || !exists {
		t.Fatal("startup did not add the local managed credential table")
	}
	count, err := engine.Table(managedcredential.Table).Count(&managedcredential.Record{})
	if err != nil || count != 0 {
		t.Fatal("migration created credentials without explicit user action")
	}
	var gotPassword UserPassWord
	var gotAuth UserAuthentication
	if _, err = engine.Table("u_pass_word").Where("user_id = ?", 123).Get(&gotPassword); err != nil {
		t.Fatal(err)
	}
	if _, err = engine.Table("u_authentication").Where("user_id = ?", 123).Get(&gotAuth); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(gotPassword.Hash, hash) || !bytes.Equal(gotAuth.AuthorizationKey, auth.AuthorizationKey) || !bytes.Equal(gotAuth.SessionKey, auth.SessionKey) || gotAuth.AuthorizationCount != auth.AuthorizationCount || gotAuth.CommandId != auth.CommandId {
		t.Fatal("schema migration changed the existing password or authentication")
	}
}
