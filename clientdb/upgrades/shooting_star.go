// Package upgrades applies narrowly scoped additions to already patched client DBs.
package upgrades

import (
	"bufio"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite"
)

const shootingStarTable = "m_lesson_skill_shooting_star"

// LessonShootingStars installs optional animation metadata only when it is absent.
// Existing tables (including deliberately empty or customized ones) are preserved.
// The asset repository supplies the data; its original, non-idempotent migrations
// must never be replayed on an already patched DB.
func LessonShootingStars(databasePath, scriptPath string) (bool, error) {
	absPath, err := filepath.Abs(databasePath)
	if err != nil {
		return false, err
	}
	// mode=rw prevents a missing DB from silently becoming an empty SQLite file.
	// Immediate transactions serialize competing upgrades before the second guard.
	dsn := (&url.URL{Scheme: "file", Path: absPath, RawQuery: url.Values{
		"mode":    {"rw"},
		"_txlock": {"immediate"},
		"_pragma": {"busy_timeout(5000)"},
	}.Encode()}).String()
	database, err := sql.Open("sqlite", dsn)
	if err != nil {
		return false, err
	}
	defer database.Close()
	database.SetMaxOpenConns(1)

	// Checking before opening a write transaction also permits read-only DBs that
	// already have the metadata. Any named object is an explicit customization.
	var exists bool
	if err = database.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name = ? COLLATE NOCASE)", shootingStarTable).Scan(&exists); err != nil {
		return false, err
	}
	if exists {
		return false, nil
	}
	if err = database.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'm_lesson_skill_content')").Scan(&exists); err != nil {
		return false, err
	}
	if !exists {
		// Asset DBs predating recovered training skills keep their old behavior.
		return false, nil
	}
	script, err := os.ReadFile(scriptPath)
	if os.IsNotExist(err) {
		// Older/custom asset repositories are allowed to omit this optional upgrade.
		return false, nil
	}
	if err != nil {
		return false, err
	}

	tx, err := database.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	if err = tx.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name = ? COLLATE NOCASE)", shootingStarTable).Scan(&exists); err != nil {
		return false, err
	}
	if exists {
		return false, nil
	}

	// Like the original asset migrations, each statement occupies a single line.
	scanner := bufio.NewScanner(strings.NewReader(string(script)))
	line := 0
	for scanner.Scan() {
		line++
		statement := strings.TrimSpace(scanner.Text())
		if statement == "" || strings.HasPrefix(statement, "--") {
			continue
		}
		if _, err = tx.Exec(statement); err != nil {
			return false, fmt.Errorf("%s:%d: %w", scriptPath, line, err)
		}
	}
	if err = scanner.Err(); err != nil {
		return false, fmt.Errorf("%s: %w", scriptPath, err)
	}
	if err = tx.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE)", shootingStarTable).Scan(&exists); err != nil {
		return false, err
	}
	if !exists {
		return false, fmt.Errorf("%s did not create %s", scriptPath, shootingStarTable)
	}
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return true, nil
}
