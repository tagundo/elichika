package userdata

import (
	"elichika/client"
	"elichika/generic"
	"elichika/userdata/database"

	"os"
	"testing"
	"time"

	"xorm.io/xorm"
)

func userManagerFixture(t *testing.T) *xorm.Engine {
	t.Helper()
	engine, err := xorm.NewEngine("sqlite", t.TempDir()+"/userdata.db")
	if err != nil {
		t.Fatal(err)
	}
	engine.SetMaxOpenConns(1)
	t.Cleanup(func() { engine.Close() })
	database.InitTables(engine)
	for _, id := range []int32{101, 202} {
		status := client.UserStatus{LastLoginAt: 1700000000 + int64(id)}
		status.Name.DotUnderText = map[int32]string{101: "Ayumu", 202: "Setsuna"}[id]
		card := client.UserCard{CardMasterId: 100000 + id}
		rows := []struct {
			table string
			value any
		}{
			{"u_status", generic.UserIdWrapper[client.UserStatus]{UserId: id, Object: &status}},
			{"u_card", generic.UserIdWrapper[client.UserCard]{UserId: id, Object: &card}},
			{"u_authentication", generic.UserIdWrapper[database.UserAuthentication]{UserId: id,
				Object: &database.UserAuthentication{AuthorizationKey: []byte("key")}}},
			{"u_pass_word", generic.UserIdWrapper[database.UserPassWord]{UserId: id,
				Object: &database.UserPassWord{Hash: []byte("hash")}}},
		}
		for _, row := range rows {
			if _, err := engine.Table(row.table).Insert(row.value); err != nil {
				t.Fatal(row.table, err)
			}
		}
	}
	for _, pair := range [][2]int32{{101, 202}, {202, 101}} {
		if _, err := engine.Exec("INSERT INTO u_friend_status (user_id, other_user_id, request_status) VALUES (?, ?, 1)",
			pair[0], pair[1]); err != nil {
			t.Fatal(err)
		}
	}
	return engine
}

func countRows(t *testing.T, engine *xorm.Engine, query string, args ...any) int {
	t.Helper()
	rows, err := engine.QueryInterface(append([]any{query}, args...)...)
	if err != nil {
		t.Fatal(err)
	}
	return len(rows)
}

func TestDeleteAccountRemovesEveryRowAndKeepsTheOthers(t *testing.T) {
	engine := userManagerFixture(t)
	users, err := ListAccounts(engine)
	if err != nil || len(users) != 2 || users[0].UserId != 101 || users[0].Name != "Ayumu" || users[0].LastLoginAt != 1700000101 {
		t.Fatalf("listed %+v, %v", users, err)
	}
	backupDir := t.TempDir() + "/deleted_users"
	backup, err := DeleteAccount(engine, 101, backupDir, time.Date(2026, 11, 26, 1, 2, 3, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for table := range database.UserDataTableNameToInterface {
		if table == "u_member_guild_daily_coop_point" {
			continue
		}
		if n := countRows(t, engine, "SELECT 1 FROM "+table+" WHERE user_id = ?", 101); n != 0 {
			t.Errorf("%s still has %d rows for the deleted user", table, n)
		}
	}
	if n := countRows(t, engine, "SELECT 1 FROM u_friend_status WHERE other_user_id = ?", 101); n != 0 {
		t.Errorf("another user still lists the deleted user as a friend")
	}
	for _, table := range []string{"u_status", "u_card", "u_authentication", "u_pass_word"} {
		if n := countRows(t, engine, "SELECT 1 FROM "+table+" WHERE user_id = ?", 202); n != 1 {
			t.Errorf("%s lost the other user's row", table)
		}
	}
	users, _ = ListAccounts(engine)
	if len(users) != 1 || users[0].UserId != 202 {
		t.Fatalf("listed %+v after delete", users)
	}

	// The snapshot is the whole database from before the delete.
	if backup != backupDir+"/userdata_before_deleting_101_20261126_010203.db" {
		t.Fatalf("backup path %s", backup)
	}
	if _, err := os.Stat(backup); err != nil {
		t.Fatal(err)
	}
	snapshot, err := xorm.NewEngine("sqlite", backup)
	if err != nil {
		t.Fatal(err)
	}
	defer snapshot.Close()
	if n := countRows(t, snapshot, "SELECT 1 FROM u_authentication WHERE user_id = ?", 101); n != 1 {
		t.Fatal("the backup does not hold the deleted account")
	}
	if n := countRows(t, snapshot, "SELECT 1 FROM u_friend_status"); n != 2 {
		t.Fatal("the backup does not hold both friend rows")
	}
}

func TestDeleteAccountRefusesAnUnknownAccountWithoutABackup(t *testing.T) {
	engine := userManagerFixture(t)
	backupDir := t.TempDir() + "/deleted_users"
	if _, err := DeleteAccount(engine, 999, backupDir, time.Now()); err != ErrAccountNotFound {
		t.Fatalf("got %v", err)
	}
	if _, err := os.Stat(backupDir); !os.IsNotExist(err) {
		t.Fatal("a backup folder was made for an unknown account")
	}
	if users, _ := ListAccounts(engine); len(users) != 2 {
		t.Fatal("an unknown delete changed the accounts")
	}
}
