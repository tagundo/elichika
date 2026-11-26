package userdata

import (
	"elichika/config"
	"elichika/userdata/database"

	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"xorm.io/xorm"
)

// DeleteAccount removes one account completely: its rows in every user table
// (login included) and the other users' friend rows that point at it. A full
// snapshot of userdata.db is taken first, so a mistaken delete is undone by
// putting that file back. ListAccounts feeds the admin user manager.

type Account struct {
	UserId      int32  `xorm:"'user_id'"`
	Name        string `xorm:"'name'"`
	LastLoginAt int64  `xorm:"'last_login_at'"`
}

var ErrAccountNotFound = errors.New("account not found")

func ListAccounts(engine *xorm.Engine) ([]Account, error) {
	users := []Account{}
	err := engine.SQL(`SELECT ids.user_id AS user_id, COALESCE(s.name, '') AS name, COALESCE(s.last_login_at, 0) AS last_login_at
		FROM (SELECT user_id FROM u_authentication UNION SELECT user_id FROM u_status) ids
		LEFT JOIN u_status s ON s.user_id = ids.user_id ORDER BY ids.user_id`).Find(&users)
	return users, err
}

// DeletedAccountBackupDir follows the database backup tool: SUKUSTA_BACKUP_ROOT when
// set (the Android app's shared Download folder), otherwise backup_db.
func DeletedAccountBackupDir() string {
	root := os.Getenv("SUKUSTA_BACKUP_ROOT")
	if root == "" {
		root = config.RootPath + "backup_db"
	}
	return filepath.Join(root, "deleted_users")
}

func DeleteAccount(engine *xorm.Engine, userId int32, backupDir string, now time.Time) (string, error) {
	exists := 0
	for _, table := range []string{"u_authentication", "u_status"} {
		count, err := engine.Table(table).Where("user_id = ?", userId).Count()
		if err != nil {
			return "", err
		}
		exists += int(count)
	}
	if exists == 0 {
		return "", ErrAccountNotFound
	}
	if err := os.MkdirAll(backupDir, 0o755); err != nil {
		return "", err
	}
	backup := filepath.Join(backupDir, fmt.Sprintf("userdata_before_deleting_%d_%s.db", userId, now.Format("20060102_150405")))
	// No snapshot, no delete.
	if _, err := engine.Exec("VACUUM INTO ?", backup); err != nil {
		os.Remove(backup)
		return "", fmt.Errorf("backup failed: %w", err)
	}
	tables := make([]string, 0, len(database.UserDataTableNameToInterface))
	for table := range database.UserDataTableNameToInterface {
		tables = append(tables, table)
	}
	sort.Strings(tables)
	session := engine.NewSession()
	defer session.Close()
	if err := session.Begin(); err != nil {
		return "", err
	}
	for _, table := range tables {
		// A few tables (e.g. u_member_guild_daily_coop_point) are not keyed by user.
		if _, err := session.Exec("DELETE FROM "+table+" WHERE user_id = ?", userId); err != nil &&
			!strings.Contains(err.Error(), "no such column") {
			session.Rollback()
			return "", err
		}
	}
	if _, err := session.Exec("DELETE FROM u_friend_status WHERE other_user_id = ?", userId); err != nil {
		session.Rollback()
		return "", err
	}
	return backup, session.Commit()
}
