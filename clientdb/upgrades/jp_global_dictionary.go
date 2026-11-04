package upgrades

import (
	"database/sql"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

// NaufalFajri contributed the translations and original suit handling in PR #57.
// Keep the data separate so the original multilingual strings remain reviewable.
//
//go:embed jp_global_translations.json
var jpGlobalTranslationsJSON []byte

type jpGlobalLocalizedText struct {
	JA string `json:"ja"`
	EN string `json:"en"`
	KO string `json:"ko"`
	ZH string `json:"zh"`
}

func (text jpGlobalLocalizedText) forLanguage(language string) string {
	switch language {
	case "en":
		return text.EN
	case "ko":
		return text.KO
	case "zh":
		return text.ZH
	}
	return ""
}

type jpGlobalDictionaryTranslations struct {
	Attribution  string                           `json:"attribution"`
	Accessories  map[string]jpGlobalLocalizedText `json:"accessories"`
	SuitPrefixes []jpGlobalLocalizedText          `json:"suit_prefixes"`
	Songs        map[string]jpGlobalLocalizedText `json:"songs"`
}

type jpGlobalDictionaryRow struct {
	id      string
	message sql.NullString
}

type jpGlobalDictionaryPlan struct {
	path               string
	rows               []jpGlobalDictionaryRow
	translations       map[string]string
	legacyTranslations map[string]string
}

// validateJPGlobalDictionaries lets the caller check dictionary inputs before
// writing any other global DB. Missing optional suffix pairs are simply skipped.
func validateJPGlobalDictionaries(assetRoot string) error {
	_, err := prepareJPGlobalDictionaries(assetRoot)
	return err
}

func mergeJPGlobalDictionaries(assetRoot string) (int64, error) {
	plans, err := prepareJPGlobalDictionaries(assetRoot)
	if err != nil {
		return 0, err
	}
	var changed int64
	for _, plan := range plans {
		count, err := applyJPGlobalDictionary(plan)
		changed += count
		if err != nil {
			return changed, fmt.Errorf("%s: %w", plan.path, err)
		}
	}
	return changed, nil
}

func prepareJPGlobalDictionaries(assetRoot string) ([]jpGlobalDictionaryPlan, error) {
	var translations jpGlobalDictionaryTranslations
	if err := json.Unmarshal(jpGlobalTranslationsJSON, &translations); err != nil {
		return nil, fmt.Errorf("JP dictionary translations: %w", err)
	}
	jpRoot, glRoot := filepath.Join(assetRoot, "db", "jp"), filepath.Join(assetRoot, "db", "gl")
	// Discover every input first. SQLite must never create an empty missing DB,
	// and an absent required locale must be detected before any locale is changed.
	var plans []jpGlobalDictionaryPlan
	sources := make(map[string][]jpGlobalDictionaryRow)
	for _, suffix := range []string{"k", "m", "dummy", "v"} {
		sourcePath := filepath.Join(jpRoot, "dictionary_ja_"+suffix+".db")
		sourceExists, err := jpGlobalDictionaryFileExists(sourcePath)
		if err != nil {
			return nil, err
		}
		if !sourceExists && suffix == "k" {
			return nil, fmt.Errorf("missing required JP dictionary: %s", sourcePath)
		}
		paired := false
		for _, language := range []string{"en", "ko", "zh"} {
			path := filepath.Join(glRoot, "dictionary_"+language+"_"+suffix+".db")
			exists, err := jpGlobalDictionaryFileExists(path)
			if err != nil {
				return nil, err
			}
			if !exists && suffix == "k" {
				return nil, fmt.Errorf("missing required global dictionary: %s", path)
			}
			if sourceExists && exists {
				// A writable GL alias must not turn the read-only JP source
				// into a translation target. Check before any DB is changed.
				sourceInfo, err := os.Stat(sourcePath)
				if err != nil {
					return nil, err
				}
				targetInfo, err := os.Stat(path)
				if err != nil {
					return nil, err
				}
				if os.SameFile(sourceInfo, targetInfo) {
					return nil, fmt.Errorf("%s: JP source and GL target must be different files", path)
				}
				plans = append(plans, jpGlobalDictionaryPlan{path: path})
				paired = true
			}
		}
		if paired {
			rows, err := readJPGlobalDictionary(sourcePath)
			if err != nil {
				return nil, err
			}
			sources[suffix] = rows
		}
	}

	suits, err := readJPGlobalSuits(filepath.Join(jpRoot, "masterdata.db"))
	if err != nil {
		return nil, err
	}
	jpNames := make(map[string]sql.NullString)
	for _, row := range sources["k"] {
		jpNames[row.id] = row.message
	}
	for i := range plans {
		plan := &plans[i]
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(plan.path), "dictionary_"), ".db")
		language, suffix, _ := strings.Cut(name, "_")
		plan.rows = sources[suffix]
		destination, err := readJPGlobalDictionary(plan.path)
		if err != nil {
			return nil, err
		}
		glNames := make(map[string]sql.NullString)
		for _, row := range destination {
			glNames[row.id] = row.message
		}
		if suffix != "k" {
			plan.retainNeededRows(glNames)
			continue
		}
		plan.translations = make(map[string]string)
		plan.legacyTranslations = make(map[string]string)
		for key, text := range translations.Accessories {
			plan.translations[key] = text.forLanguage(language)
		}
		for key, text := range translations.Songs {
			plan.translations[key] = text.forLanguage(language)
		}
		for _, suit := range suits {
			key := strings.TrimPrefix(suit.nameKey, "k.")
			japanese := jpNames[key]
			if !japanese.Valid {
				continue
			}
			memberName := jpGlobalSuitMemberName(suit.memberID, glNames, jpNames)
			if memberName == "" {
				continue // Preserve the full JP name when no member name is available.
			}
			for _, prefix := range translations.SuitPrefixes {
				if strings.Contains(japanese.String, prefix.JA) {
					// The suit owner is authoritative; some JP name keys mention
					// the opposite member. Never infer ownership from that text.
					localizedPrefix := prefix.forLanguage(language) + " "
					plan.translations[key] = localizedPrefix + memberName
					// Recognize only the exact wrong title emitted by the old
					// JP-name-based override, so custom titles remain untouched.
					oldMemberID := suit.memberID
					if strings.Contains(japanese.String, "ミア・テイラー") {
						oldMemberID = 212
					} else if strings.Contains(japanese.String, "ショウ・ランジュ") {
						oldMemberID = 211
					}
					if oldMemberID != suit.memberID && (suit.memberID == 211 || suit.memberID == 212) {
						if oldName := jpGlobalSuitMemberName(oldMemberID, glNames, jpNames); oldName != "" {
							plan.legacyTranslations[key] = localizedPrefix + oldName
						}
					}
					break
				}
			}
		}
		plan.retainNeededRows(glNames)
	}
	return plans, nil
}

func jpGlobalSuitMemberName(memberID int, global, japanese map[string]sql.NullString) string {
	key := fmt.Sprintf("m_dic_member_name_%d", memberID)
	if name := global[key]; name.Valid && name.String != "" {
		return name.String
	}
	return japanese[key].String
}

func (plan jpGlobalDictionaryPlan) acceptsReplacement(row jpGlobalDictionaryRow, current sql.NullString) bool {
	translated, known := plan.translations[row.id]
	if !known || !current.Valid || current.String == translated {
		return false
	}
	if row.message.Valid && current.String == row.message.String {
		return true
	}
	legacy, knownLegacy := plan.legacyTranslations[row.id]
	return knownLegacy && current.String == legacy
}

func (plan *jpGlobalDictionaryPlan) retainNeededRows(existing map[string]sql.NullString) {
	// Keep only candidates rather than issuing a query for every imported key
	// on every rebuild. The transaction still checks each candidate's guard.
	var needed []jpGlobalDictionaryRow
	for _, row := range plan.rows {
		current, exists := existing[row.id]
		if !exists || plan.acceptsReplacement(row, current) {
			needed = append(needed, row)
		}
	}
	plan.rows = needed
}

func jpGlobalDictionaryFileExists(path string) (bool, error) {
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !info.Mode().IsRegular() {
		return false, fmt.Errorf("dictionary input is not a regular file: %s", path)
	}
	return true, nil
}

func openJPDictionaryReadOnly(path string) (*sql.DB, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	uri := databaseFileURL(filepath.ToSlash(absPath))
	uri.RawQuery = url.Values{"mode": {"ro"}, "_pragma": {"busy_timeout(5000)"}}.Encode()
	database, err := sql.Open("sqlite", uri.String())
	if err == nil {
		database.SetMaxOpenConns(1)
	}
	return database, err
}

func readJPGlobalDictionary(path string) ([]jpGlobalDictionaryRow, error) {
	database, err := openJPDictionaryReadOnly(path)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	defer database.Close()
	var exists bool
	if err := database.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'm_dictionary' COLLATE NOCASE)").Scan(&exists); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if !exists {
		return nil, fmt.Errorf("%s: missing m_dictionary table", path)
	}
	rows, err := database.Query("SELECT id, message FROM m_dictionary ORDER BY id")
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	defer rows.Close()
	var result []jpGlobalDictionaryRow
	for rows.Next() {
		var row jpGlobalDictionaryRow
		if err := rows.Scan(&row.id, &row.message); err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
		result = append(result, row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return result, nil
}

type jpGlobalSuit struct {
	memberID int
	nameKey  string
}

func readJPGlobalSuits(path string) ([]jpGlobalSuit, error) {
	database, err := openJPDictionaryReadOnly(path)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	defer database.Close()
	var exists bool
	if err := database.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'm_suit' COLLATE NOCASE)").Scan(&exists); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if !exists {
		return nil, nil
	}
	rows, err := database.Query("SELECT member_m_id, name FROM m_suit ORDER BY id")
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	defer rows.Close()
	var suits []jpGlobalSuit
	for rows.Next() {
		var suit jpGlobalSuit
		if err := rows.Scan(&suit.memberID, &suit.nameKey); err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
		suits = append(suits, suit)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return suits, nil
}

func applyJPGlobalDictionary(plan jpGlobalDictionaryPlan) (int64, error) {
	if len(plan.rows) == 0 {
		return 0, nil
	}
	database, err := openExisting(plan.path)
	if err != nil {
		return 0, err
	}
	defer database.Close()
	// Check before locking, and again within the transaction. A second run needs
	// no writes, preserving database bytes and working with read-only GL files.
	needed, err := jpGlobalDictionaryNeedsChanges(database, plan)
	if err != nil || !needed {
		return 0, err
	}
	tx, err := database.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	var changed int64
	for _, row := range plan.rows {
		var current sql.NullString
		err := tx.QueryRow("SELECT message FROM m_dictionary WHERE id = ?", row.id).Scan(&current)
		translated, known := plan.translations[row.id]
		var result sql.Result
		switch {
		case err == sql.ErrNoRows:
			message := row.message
			if known {
				message = sql.NullString{String: translated, Valid: true}
			}
			result, err = tx.Exec("INSERT INTO m_dictionary (id, message) VALUES (?, ?)", row.id, message)
		case err != nil:
			return 0, fmt.Errorf("dictionary key %q: %w", row.id, err)
		case plan.acceptsReplacement(row, current):
			// Repair only exact JP fallbacks or the known historical suit title.
			result, err = tx.Exec("UPDATE m_dictionary SET message = ? WHERE id = ? AND message = ?", translated, row.id, current.String)
		default:
			continue
		}
		if err != nil {
			return 0, fmt.Errorf("dictionary key %q: %w", row.id, err)
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
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return changed, nil
}

func jpGlobalDictionaryNeedsChanges(database *sql.DB, plan jpGlobalDictionaryPlan) (bool, error) {
	for _, row := range plan.rows {
		var current sql.NullString
		err := database.QueryRow("SELECT message FROM m_dictionary WHERE id = ?", row.id).Scan(&current)
		if err == sql.ErrNoRows {
			return true, nil
		}
		if err != nil {
			return false, err
		}
		if plan.acceptsReplacement(row, current) {
			return true, nil
		}
	}
	return false, nil
}
