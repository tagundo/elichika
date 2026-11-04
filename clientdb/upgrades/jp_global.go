package upgrades

import (
	"crypto/sha1"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const jpGlobalMarker = "elichika_jp_global_merge"
const jpGlobalAlgorithm = "jp-global-content-v1"

// JapaneseContentReport counts inserted content rows and changed package headers.
// A missing optional installation is reported through SkippedReason, without writes.
type JapaneseContentReport struct {
	MasterRows      int64
	AssetRows       int64
	DictionaryRows  int64
	PackagesUpdated int64
	SkippedReason   string
}

type jpGlobalPair struct {
	source, target string
	asset          bool
}

type jpGlobalColumn struct {
	name, kind string
	notNull    int
	primaryKey int
}

type jpGlobalTable struct {
	name, sourceName string
	columns          []jpGlobalColumn
}

type jpGlobalQueryer interface {
	Query(string, ...any) (*sql.Rows, error)
	QueryRow(string, ...any) *sql.Row
}

// ManagedJapaneseContent recognizes a complete installer transaction. Call this
// before historical migrations: those SQL files describe pristine databases and
// must never be replayed against a retained, managed mod installation.
func ManagedJapaneseContent(assetRoot string) (bool, error) {
	return managedJapaneseContent(assetRoot, jpGlobalAlgorithm)
}

// JapaneseContent imports missing Japanese content into the initialized Global
// databases. Each target commits independently so an interrupted run can resume.
// Existing Global rows, including custom translations and assets, always win.
func JapaneseContent(assetRoot string) (JapaneseContentReport, error) {
	var report JapaneseContentReport
	if managed, err := ManagedJapaneseContent(assetRoot); err != nil {
		return report, err
	} else if managed {
		report.SkippedReason = "initialized APK content was merged by the managed installer; retained regional mods are preserved"
		return report, nil
	}
	jp := filepath.Join(assetRoot, "db", "jp")
	gl := filepath.Join(assetRoot, "db", "gl")
	pairs := []jpGlobalPair{{source: filepath.Join(jp, "masterdata.db"), target: filepath.Join(gl, "masterdata.db")}}
	for _, platform := range []string{"a", "i"} {
		for _, language := range []string{"en", "ko", "zh"} {
			pairs = append(pairs, jpGlobalPair{
				source: filepath.Join(jp, "asset_"+platform+"_ja.db"),
				target: filepath.Join(gl, "asset_"+platform+"_"+language+".db"), asset: true,
			})
		}
	}
	// Check the entire required installation before opening any writable database.
	paths := []string{filepath.Join(jp, "dictionary_ja_k.db")}
	for _, language := range []string{"en", "ko", "zh"} {
		paths = append(paths, filepath.Join(gl, "dictionary_"+language+"_k.db"))
	}
	for _, pair := range pairs {
		paths = append(paths, pair.source, pair.target)
	}
	for _, path := range paths {
		info, err := os.Stat(path)
		if os.IsNotExist(err) {
			report.SkippedReason = "Japanese content requires initialized JP and GL databases; missing " + path
			return report, nil
		}
		if err != nil {
			return report, err
		}
		if !info.Mode().IsRegular() {
			return report, fmt.Errorf("Japanese content database is not a regular file: %s", path)
		}
	}
	for index, pair := range pairs {
		ready, err := preflightJPGlobalPair(pair, index == 0)
		if err != nil {
			return report, fmt.Errorf("%s: %w", pair.target, err)
		}
		if !ready {
			report.SkippedReason = "Japanese content requires initialized lesson databases (m_lesson_drop_amount): " + pair.target
			return report, nil
		}
	}
	if err := validateJPGlobalDictionaries(assetRoot); err != nil {
		return report, err
	}
	// Hash each source once, even when three language targets share it. A marker
	// is committed with its content, avoiding full asset scans on later startups.
	fingerprints := map[string]string{}
	for _, pair := range pairs {
		fingerprint, ok := fingerprints[pair.source]
		if !ok {
			var err error
			fingerprint, err = jpGlobalFingerprint(pair.source)
			if err != nil {
				return report, err
			}
			fingerprints[pair.source] = fingerprint
		}
		rows, packages, err := mergeJPGlobalPair(pair, fingerprint)
		if err != nil {
			return report, fmt.Errorf("%s: %w", pair.target, err)
		}
		if pair.asset {
			report.AssetRows += rows
		} else {
			report.MasterRows += rows
		}
		report.PackagesUpdated += packages
	}
	var err error
	report.DictionaryRows, err = mergeJPGlobalDictionaries(assetRoot)
	return report, err
}

func openJPGlobalReadOnly(path string) (*sql.DB, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	uri := databaseFileURL(filepath.ToSlash(abs))
	uri.RawQuery = url.Values{"mode": {"ro"}}.Encode()
	db, err := sql.Open("sqlite", uri.String())
	if err == nil {
		db.SetMaxOpenConns(1)
	}
	return db, err
}

func preflightJPGlobalPair(pair jpGlobalPair, master bool) (bool, error) {
	sourceInfo, err := os.Stat(pair.source)
	if err != nil {
		return false, err
	}
	targetInfo, err := os.Stat(pair.target)
	if err != nil {
		return false, err
	}
	if os.SameFile(sourceInfo, targetInfo) {
		return false, fmt.Errorf("JP source and GL target must be different files")
	}
	source, err := openJPGlobalReadOnly(pair.source)
	if err != nil {
		return false, err
	}
	defer source.Close()
	target, err := openJPGlobalReadOnly(pair.target)
	if err != nil {
		return false, err
	}
	defer target.Close()
	if master {
		for _, db := range []*sql.DB{source, target} {
			var exists bool
			if err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'm_lesson_drop_amount' COLLATE NOCASE)").Scan(&exists); err != nil {
				return false, err
			}
			if !exists {
				return false, nil
			}
		}
	}
	_, err = jpGlobalPlan(target, "main", source, "main", pair.asset)
	return err == nil, err
}

func quoteJPGlobalIdentifier(identifier string) string {
	return `"` + strings.ReplaceAll(identifier, `"`, `""`) + `"`
}

func jpGlobalTables(query jpGlobalQueryer, schema string) (map[string]string, error) {
	rows, err := query.Query("SELECT name FROM " + quoteJPGlobalIdentifier(schema) + ".sqlite_master WHERE type = 'table' ORDER BY name")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	tables := map[string]string{}
	for rows.Next() {
		var name string
		if err = rows.Scan(&name); err != nil {
			return nil, err
		}
		key := strings.ToLower(name)
		if strings.HasPrefix(key, "sqlite_") || key == "assetversion" || key == jpGlobalMarker {
			continue
		}
		tables[key] = name
	}
	return tables, rows.Err()
}

func jpGlobalColumns(query jpGlobalQueryer, schema, table string) ([]jpGlobalColumn, error) {
	rows, err := query.Query("PRAGMA " + quoteJPGlobalIdentifier(schema) + ".table_xinfo(" + quoteJPGlobalIdentifier(table) + ")")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var columns []jpGlobalColumn
	for rows.Next() {
		var column jpGlobalColumn
		var ordinal, hidden int
		var defaultValue sql.NullString
		if err = rows.Scan(&ordinal, &column.name, &column.kind, &column.notNull, &defaultValue, &column.primaryKey, &hidden); err != nil {
			return nil, err
		}
		if hidden != 0 {
			return nil, fmt.Errorf("%s: generated/hidden columns are unsupported", table)
		}
		column.kind = strings.ToUpper(strings.TrimSpace(column.kind))
		columns = append(columns, column)
	}
	return columns, rows.Err()
}

func jpGlobalPlan(target jpGlobalQueryer, targetSchema string, source jpGlobalQueryer, sourceSchema string, asset bool) ([]jpGlobalTable, error) {
	targetTables, err := jpGlobalTables(target, targetSchema)
	if err != nil {
		return nil, err
	}
	sourceTables, err := jpGlobalTables(source, sourceSchema)
	if err != nil {
		return nil, err
	}
	if asset {
		for _, name := range []string{"m_asset_package", "m_asset_package_mapping"} {
			if targetTables[name] == "" || sourceTables[name] == "" {
				return nil, fmt.Errorf("missing required asset table %s", name)
			}
		}
	}
	var names []string
	for name := range targetTables {
		if sourceTables[name] != "" {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	var plan []jpGlobalTable
	for _, name := range names {
		columns, err := jpGlobalColumns(target, targetSchema, targetTables[name])
		if err != nil {
			return nil, err
		}
		sourceColumns, err := jpGlobalColumns(source, sourceSchema, sourceTables[name])
		if err != nil {
			return nil, err
		}
		targetHasPrimaryKey, sourceHasPrimaryKey := false, false
		for _, column := range columns {
			targetHasPrimaryKey = targetHasPrimaryKey || column.primaryKey > 0
		}
		for _, column := range sourceColumns {
			sourceHasPrimaryKey = sourceHasPrimaryKey || column.primaryKey > 0
		}
		if !targetHasPrimaryKey && !sourceHasPrimaryKey {
			// Initialization adds unkeyed configuration rowsets such as
			// m_lesson_drop_amount. They have no row identity for a safe merge;
			// preserve GL's complete configured/custom rowset instead.
			continue
		}
		if len(columns) == 0 || len(columns) != len(sourceColumns) {
			return nil, fmt.Errorf("%s: incompatible column count", name)
		}
		byName := map[string]jpGlobalColumn{}
		for _, column := range sourceColumns {
			byName[strings.ToLower(column.name)] = column
		}
		for _, column := range columns {
			src, exists := byName[strings.ToLower(column.name)]
			if !exists || src.kind != column.kind || src.notNull != column.notNull || src.primaryKey != column.primaryKey {
				return nil, fmt.Errorf("%s.%s: incompatible column schema", name, column.name)
			}
		}
		if asset {
			required := map[string][]string{"m_asset_package": {"package_key", "version", "pack_num"}, "m_asset_package_mapping": {"package_key", "pack_name"}}
			for _, column := range required[name] {
				if _, exists := byName[column]; !exists {
					return nil, fmt.Errorf("%s: missing required column %s", name, column)
				}
			}
		}
		plan = append(plan, jpGlobalTable{name: targetTables[name], sourceName: sourceTables[name], columns: columns})
	}
	if len(plan) == 0 {
		return nil, fmt.Errorf("no compatible content tables")
	}
	return plan, nil
}

func jpGlobalFingerprint(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err = io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func jpGlobalAlreadyMerged(query jpGlobalQueryer, fingerprint string) (bool, error) {
	var exists bool
	if err := query.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?)", jpGlobalMarker).Scan(&exists); err != nil || !exists {
		return false, err
	}
	var matched bool
	err := query.QueryRow("SELECT EXISTS(SELECT 1 FROM "+quoteJPGlobalIdentifier(jpGlobalMarker)+" WHERE id = 1 AND source_sha = ? AND algorithm_version = ?)", fingerprint, jpGlobalAlgorithm).Scan(&matched)
	return matched, err
}

func mergeJPGlobalPair(pair jpGlobalPair, fingerprint string) (int64, int64, error) {
	db, err := openExisting(pair.target)
	if err != nil {
		return 0, 0, err
	}
	defer db.Close()
	if done, err := jpGlobalAlreadyMerged(db, fingerprint); done || err != nil {
		return 0, 0, err
	}
	abs, err := filepath.Abs(pair.source)
	if err != nil {
		return 0, 0, err
	}
	uri := databaseFileURL(filepath.ToSlash(abs))
	uri.RawQuery = url.Values{"mode": {"ro"}}.Encode()
	if _, err = db.Exec("ATTACH DATABASE ? AS jp_content", uri.String()); err != nil {
		return 0, 0, err
	}
	tx, err := db.Begin()
	if err != nil {
		return 0, 0, err
	}
	defer tx.Rollback()
	if done, err := jpGlobalAlreadyMerged(tx, fingerprint); done || err != nil {
		return 0, 0, err
	}
	plan, err := jpGlobalPlan(tx, "main", tx, "jp_content", pair.asset)
	if err != nil {
		return 0, 0, err
	}
	before := map[string]int64{}
	if pair.asset {
		rows, err := tx.Query("SELECT package_key, COUNT(*) FROM main.m_asset_package_mapping GROUP BY package_key")
		if err != nil {
			return 0, 0, err
		}
		for rows.Next() {
			var key string
			var count int64
			if err = rows.Scan(&key, &count); err != nil {
				rows.Close()
				return 0, 0, err
			}
			before[key] = count
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return 0, 0, err
		}
	}
	var inserted int64
	for _, table := range plan {
		var columns []string
		for _, column := range table.columns {
			columns = append(columns, quoteJPGlobalIdentifier(column.name))
		}
		list := strings.Join(columns, ", ")
		result, err := tx.Exec("INSERT INTO main." + quoteJPGlobalIdentifier(table.name) + " (" + list + ") SELECT " + list + " FROM jp_content." + quoteJPGlobalIdentifier(table.sourceName) + " WHERE true ON CONFLICT DO NOTHING")
		if err != nil {
			return 0, 0, fmt.Errorf("%s: %w", table.name, err)
		}
		count, err := result.RowsAffected()
		if err != nil {
			return 0, 0, err
		}
		inserted += count
	}
	var packages int64
	if pair.asset {
		packages, err = updateJPGlobalPackages(tx, plan, before)
		if err != nil {
			return 0, 0, err
		}
	}
	if _, err = tx.Exec("CREATE TABLE IF NOT EXISTS " + quoteJPGlobalIdentifier(jpGlobalMarker) + " (id INTEGER PRIMARY KEY CHECK(id = 1), source_sha TEXT NOT NULL, algorithm_version TEXT NOT NULL)"); err != nil {
		return 0, 0, err
	}
	if _, err = tx.Exec("INSERT INTO "+quoteJPGlobalIdentifier(jpGlobalMarker)+" (id, source_sha, algorithm_version) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET source_sha = excluded.source_sha, algorithm_version = excluded.algorithm_version", fingerprint, jpGlobalAlgorithm); err != nil {
		return 0, 0, err
	}
	if err = tx.Commit(); err != nil {
		return 0, 0, err
	}
	return inserted, packages, nil
}

func updateJPGlobalPackages(tx *sql.Tx, plan []jpGlobalTable, before map[string]int64) (int64, error) {
	rows, err := tx.Query("SELECT package_key, COUNT(*) FROM m_asset_package_mapping GROUP BY package_key ORDER BY package_key")
	if err != nil {
		return 0, err
	}
	type changedPackage struct {
		key   string
		count int64
	}
	var changed []changedPackage
	for rows.Next() {
		var item changedPackage
		if err = rows.Scan(&item.key, &item.count); err != nil {
			rows.Close()
			return 0, err
		}
		if item.count > before[item.key] {
			changed = append(changed, item)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return 0, err
	}
	var columns []string
	for _, table := range plan {
		if strings.EqualFold(table.name, "m_asset_package_mapping") {
			for _, column := range table.columns {
				columns = append(columns, quoteJPGlobalIdentifier(column.name))
			}
		}
	}
	list := strings.Join(columns, ", ")
	for _, item := range changed {
		rows, err := tx.Query("SELECT "+list+" FROM m_asset_package_mapping WHERE package_key = ? ORDER BY "+list, item.key)
		if err != nil {
			return 0, err
		}
		hash := sha1.New() // Client package versions are 40 hexadecimal characters.
		io.WriteString(hash, jpGlobalAlgorithm+"\n"+list+"\n")
		for rows.Next() {
			values := make([]any, len(columns))
			pointers := make([]any, len(values))
			for index := range values {
				pointers[index] = &values[index]
			}
			if err = rows.Scan(pointers...); err != nil {
				rows.Close()
				return 0, err
			}
			encoded, err := json.Marshal(values)
			if err != nil {
				rows.Close()
				return 0, err
			}
			hash.Write(encoded)
			hash.Write([]byte{'\n'})
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return 0, err
		}
		result, err := tx.Exec("UPDATE m_asset_package SET version = ?, pack_num = ? WHERE package_key = ?", hex.EncodeToString(hash.Sum(nil)), item.count, item.key)
		if err != nil {
			return 0, err
		}
		count, err := result.RowsAffected()
		if err != nil {
			return 0, err
		}
		if count != 1 {
			return 0, fmt.Errorf("package mappings have no unique package header: %s", item.key)
		}
	}
	return int64(len(changed)), nil
}
