package upgrades

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"unicode/utf8"
)

type dictionaryChange struct {
	ID   string   `json:"id"`
	From []string `json:"from"`
	To   string   `json:"to"`
}

func (change dictionaryChange) accepts(current sql.NullString) bool {
	if !current.Valid || current.String == change.To {
		return false
	}
	for _, previous := range change.From {
		if current.String == previous {
			return true
		}
	}
	return false
}

// DictionaryText replaces only known historical wording and fills missing keys.
// Owner-provided translations and every other table/column remain intact. The
// JSON plan holds exact strings (including line breaks), rather than SQL code.
func DictionaryText(databasePath, planPath string) (int64, error) {
	contents, err := os.ReadFile(planPath)
	if os.IsNotExist(err) {
		return 0, nil // Older/custom asset repositories can omit optional text fixes.
	}
	if err != nil {
		return 0, err
	}
	if !utf8.Valid(contents) {
		return 0, fmt.Errorf("%s: invalid UTF-8", planPath)
	}
	var plan struct {
		Changes []dictionaryChange `json:"changes"`
	}
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&plan); err != nil {
		return 0, fmt.Errorf("%s: %w", planPath, err)
	}
	if err = decoder.Decode(new(any)); err != io.EOF {
		return 0, fmt.Errorf("%s: expected a single JSON plan", planPath)
	}
	if len(plan.Changes) == 0 {
		return 0, fmt.Errorf("%s: no dictionary changes", planPath)
	}
	seen := map[string]bool{}
	for _, change := range plan.Changes {
		if change.ID == "" || change.To == "" || seen[change.ID] {
			return 0, fmt.Errorf("%s: empty or duplicate dictionary key/value: %q", planPath, change.ID)
		}
		seen[change.ID] = true
	}

	database, err := openExisting(databasePath)
	if err != nil {
		return 0, err
	}
	defer database.Close()
	var exists bool
	if err = database.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'm_dictionary' COLLATE NOCASE)").Scan(&exists); err != nil {
		return 0, err
	}
	if !exists {
		return 0, nil
	}
	// Read first so already-correct read-only DBs also work without a write lock.
	needed := false
	for _, change := range plan.Changes {
		var current sql.NullString
		err = database.QueryRow("SELECT message FROM m_dictionary WHERE id = ?", change.ID).Scan(&current)
		if err == sql.ErrNoRows || (err == nil && change.accepts(current)) {
			needed = true
			break
		}
		if err != nil {
			return 0, err
		}
	}
	if !needed {
		return 0, nil
	}
	tx, err := database.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	var changed int64
	for _, change := range plan.Changes {
		var current sql.NullString
		err = tx.QueryRow("SELECT message FROM m_dictionary WHERE id = ?", change.ID).Scan(&current)
		var result sql.Result
		switch {
		case err == sql.ErrNoRows:
			result, err = tx.Exec("INSERT INTO m_dictionary (id, message) VALUES (?, ?)", change.ID, change.To)
		case err != nil:
			return 0, err
		case change.accepts(current):
			result, err = tx.Exec("UPDATE m_dictionary SET message = ? WHERE id = ? AND message = ?", change.To, change.ID, current.String)
		default:
			continue
		}
		if err != nil {
			return 0, fmt.Errorf("%s (%s): %w", planPath, change.ID, err)
		}
		count, err := result.RowsAffected()
		if err != nil {
			return 0, err
		}
		changed += count
	}
	if changed == 0 {
		return 0, nil
	}
	if err = tx.Commit(); err != nil {
		return 0, err
	}
	return changed, nil
}
