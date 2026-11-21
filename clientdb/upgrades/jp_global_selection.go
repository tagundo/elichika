package upgrades

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
)

// Generated from the initialized GL catalogs and reviewed targeted JP migration.
//
//go:embed jp_global_selection.json.gz
var globalSelectionProof []byte

type globalCatalogSelection struct {
	Version             int    `json:"version"`
	MasterSHA256        string `json:"master_sha256"`
	MasterContentSHA256 string `json:"master_content_sha256"`
	CompatibleMasters   []struct {
		SHA256        string `json:"sha256"`
		ContentSHA256 string `json:"content_sha256"`
	} `json:"compatible_masters"`
	Catalogs map[string]globalCatalogDelta `json:"catalogs"`
}

type globalCatalogDelta struct {
	SourceSHA256        string                             `json:"source_sha256"`
	SourceContentSHA256 string                             `json:"source_content_sha256"`
	Tables              map[string]globalCatalogTableDelta `json:"tables"`
	ProtectedFiles      []string                           `json:"protected_files"`
}

type globalCatalogTableDelta struct {
	Columns []string `json:"columns"`
	Remove  [][]any  `json:"remove"`
	Add     [][]any  `json:"add"`
}

func loadGlobalCatalogSelection() (*globalCatalogSelection, error) {
	reader, err := gzip.NewReader(bytes.NewReader(globalSelectionProof))
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	decoder := json.NewDecoder(reader)
	decoder.UseNumber()
	var selection globalCatalogSelection
	if err = decoder.Decode(&selection); err != nil {
		return nil, err
	}
	if selection.Version != 1 || len(selection.Catalogs) != 6 {
		return nil, fmt.Errorf("unsupported GL catalog selection version %d", selection.Version)
	}
	return &selection, nil
}

func matchesGlobalCatalog(path, raw, content string) (bool, error) {
	quiet, err := quietCatalogFile(path)
	if err != nil || !quiet {
		return false, err
	}
	digest, err := jpGlobalFingerprint(path)
	if err != nil || digest == raw {
		return digest == raw, err
	}
	if content == "" {
		return false, nil
	}
	digest, err = globalCatalogContentFingerprint(path)
	return digest == content, err
}

// Managed updates use SQLite backups. Hash the schema and typed rows when
// the database page layout or the SQLite version in its header has changed.
func globalCatalogContentFingerprint(path string) (string, error) {
	db, err := openJPGlobalReadOnly(path)
	if err != nil {
		return "", err
	}
	defer db.Close()
	rows, err := db.Query(`SELECT name, type, COALESCE(sql, '') FROM main.sqlite_schema
		WHERE substr(name,1,7) <> 'sqlite_' ORDER BY type,name`)
	if err != nil {
		return "", err
	}
	defer rows.Close()
	hash := sha256.New()
	var tables []string
	for rows.Next() {
		var name, kind, definition string
		if err = rows.Scan(&name, &kind, &definition); err != nil {
			return "", err
		}
		io.WriteString(hash, name+"\x00"+kind+"\x00"+definition+"\x00")
		if kind == "table" {
			tables = append(tables, name)
		}
	}
	if err = rows.Err(); err != nil {
		return "", err
	}
	rows.Close()
	for _, table := range tables {
		if err = hashGlobalCatalogTable(db, hash, table); err != nil {
			return "", err
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func hashGlobalCatalogTable(db *sql.DB, hash io.Writer, table string) error {
	columns, err := jpGlobalColumns(db, "main", table)
	if err != nil {
		return err
	}
	var encoded, order []string
	keys := make([]string, len(columns))
	for _, column := range columns {
		name := quoteJPGlobalIdentifier(column.name)
		encoded = append(encoded, "(typeof("+name+") || ':' || hex(CAST("+name+" AS BLOB)) || ',')")
		order = append(order, name)
		if column.primaryKey != 0 {
			keys[column.primaryKey-1] = name
		}
	}
	for len(keys) > 0 && keys[len(keys)-1] == "" {
		keys = keys[:len(keys)-1]
	}
	if len(keys) > 0 {
		order = keys
	}
	query := "SELECT " + strings.Join(encoded, " || ") + " FROM main." + quoteJPGlobalIdentifier(table) +
		" ORDER BY " + strings.Join(order, ", ") + ", 1"
	rows, err := db.Query(query)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var row string
		if err = rows.Scan(&row); err != nil {
			return err
		}
		io.WriteString(hash, row+"\n")
	}
	return rows.Err()
}

func applyGlobalCatalogSelection(path string, selection globalCatalogDelta) (int64, error) {
	db, err := openExisting(path)
	if err != nil {
		return 0, err
	}
	defer db.Close()
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	var hasTriggers bool
	if err = tx.QueryRow("SELECT EXISTS(SELECT 1 FROM main.sqlite_schema WHERE type = 'trigger')").Scan(&hasTriggers); err != nil {
		return 0, err
	}
	if hasTriggers {
		return 0, fmt.Errorf("unexpected triggers in the stock GL catalog")
	}
	tables := make([]string, 0, len(selection.Tables))
	for table := range selection.Tables {
		tables = append(tables, table)
	}
	slices.Sort(tables)
	for _, table := range tables {
		if err = applyGlobalCatalogRows(tx, table, selection.Tables[table]); err != nil {
			return 0, fmt.Errorf("%s: %w", table, err)
		}
	}
	var inconsistent bool
	err = tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM m_asset_package AS p
		LEFT JOIN (SELECT package_key, COUNT(*) AS count FROM m_asset_package_mapping GROUP BY package_key) AS m USING (package_key)
		WHERE p.pack_num IS NOT COALESCE(m.count, 0))
		OR EXISTS(SELECT 1 FROM m_asset_package_mapping AS m LEFT JOIN m_asset_package AS p USING (package_key)
		WHERE p.package_key IS NULL)`).Scan(&inconsistent)
	if err != nil {
		return 0, err
	}
	if inconsistent {
		return 0, fmt.Errorf("inconsistent GL package counts")
	}
	var integrity string
	if err = tx.QueryRow("PRAGMA quick_check").Scan(&integrity); err != nil {
		return 0, err
	}
	if integrity != "ok" {
		return 0, fmt.Errorf("GL catalog integrity check: %s", integrity)
	}
	count := int64(len(selection.Tables["m_asset_package_mapping"].Remove))
	if count == 0 {
		return 0, nil
	}
	if err = tx.Commit(); err != nil {
		return 0, err
	}
	// Compact the disposable copy so B-tree free space and cell placement
	// cannot give identical catalog contents a different manifest on restart.
	if _, err = db.Exec("VACUUM"); err != nil {
		return 0, err
	}
	return count, nil
}

func applyGlobalCatalogRows(tx *sql.Tx, table string, delta globalCatalogTableDelta) error {
	columns, err := jpGlobalColumns(tx, "main", table)
	if err != nil {
		return err
	}
	var names, quoted, matches, placeholders []string
	for _, column := range columns {
		names = append(names, column.name)
		name := quoteJPGlobalIdentifier(column.name)
		quoted = append(quoted, name)
		matches = append(matches, name+" IS ?")
		placeholders = append(placeholders, "?")
	}
	if len(names) == 0 || !slices.Equal(names, delta.Columns) {
		return fmt.Errorf("unexpected column layout")
	}
	destination := "main." + quoteJPGlobalIdentifier(table)
	if err = writeGlobalCatalogRows(tx, "DELETE FROM "+destination+" WHERE "+strings.Join(matches, " AND "), delta.Remove); err != nil {
		return err
	}
	return writeGlobalCatalogRows(tx, "INSERT INTO "+destination+" ("+strings.Join(quoted, ", ")+
		") VALUES ("+strings.Join(placeholders, ", ")+")", delta.Add)
}

func writeGlobalCatalogRows(tx *sql.Tx, query string, rows [][]any) error {
	if len(rows) == 0 {
		return nil
	}
	stmt, err := tx.Prepare(query)
	if err != nil {
		return err
	}
	defer stmt.Close()
	for _, row := range rows {
		args := slices.Clone(row)
		for index, arg := range args {
			if number, ok := arg.(json.Number); ok {
				args[index], err = number.Int64()
				if err != nil {
					return fmt.Errorf("invalid catalog integer: %w", err)
				}
			}
		}
		result, err := stmt.Exec(args...)
		if err != nil {
			return err
		}
		count, err := result.RowsAffected()
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("expected one exact catalog row, changed %d", count)
		}
	}
	return nil
}

// Protect a local replacement of a lookup removed from the stock catalog.
// The same pack library may be bucketed or reached through directory links.
func localGlobalCatalogOverrides(roots []string, names map[string]bool) (map[string]bool, error) {
	found, seen := make(map[string]bool), make(map[string]bool)
	var scan func(string) error
	scan = func(root string) error {
		resolved, err := filepath.EvalSymlinks(root)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil || seen[resolved] {
			return err
		}
		seen[resolved] = true
		entries, err := os.ReadDir(resolved)
		if err != nil {
			return err
		}
		for _, entry := range entries {
			path := filepath.Join(resolved, entry.Name())
			kind := entry.Type()
			if kind&os.ModeSymlink != 0 {
				info, err := os.Stat(path)
				if os.IsNotExist(err) {
					continue
				}
				if err != nil {
					return err
				}
				kind = info.Mode().Type()
			}
			if kind.IsDir() {
				if err = scan(path); err != nil {
					return err
				}
			} else if kind.IsRegular() && names[entry.Name()] {
				found[entry.Name()] = true
			}
		}
		return nil
	}
	for _, root := range roots {
		if root != "" {
			if err := scan(root); err != nil {
				return nil, err
			}
		}
	}
	return found, nil
}
