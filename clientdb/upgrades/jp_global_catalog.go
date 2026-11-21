package upgrades

import (
	"bytes"
	"compress/gzip"
	"database/sql"
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

// The audited names were absent from the original GL pack catalog. Every JP
// lookup into these packs was covered by a surviving GL lookup. The generator
// is bin/build_jp_global_catalog.py.
//
//go:embed jp_global_catalog.json.gz
var globalCatalogProof []byte

type globalCatalogEvidence struct {
	SourceSHA256 map[string]string   `json:"source_sha256"`
	Catalogs     map[string][]string `json:"catalogs"`
}

// GlobalDownloadCatalogPolicy prepares smaller, client-facing asset databases.
// The installed databases remain the authority for pack routing and mod tools.
type GlobalDownloadCatalogPolicy struct {
	evidence         globalCatalogEvidence
	sources          map[string]string
	masterReferences map[string]bool
	selection        map[string]globalCatalogDelta
}

func GlobalDownloadCatalogs(assetRoot string, packRoots ...string) (*GlobalDownloadCatalogPolicy, error) {
	reader, err := gzip.NewReader(bytes.NewReader(globalCatalogProof))
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	var evidence globalCatalogEvidence
	if err := json.NewDecoder(reader).Decode(&evidence); err != nil {
		return nil, err
	}
	policy, err := newGlobalDownloadCatalogs(assetRoot, evidence)
	if err != nil {
		return nil, err
	}
	if policy == nil {
		policy = &GlobalDownloadCatalogPolicy{}
	}
	policy.selection, err = eligibleGlobalCatalogSelection(filepath.Join(assetRoot, "db", "gl", "masterdata.db"), packRoots)
	if err != nil {
		return nil, err
	}
	if len(policy.selection) == 0 && len(policy.sources) == 0 {
		return nil, nil
	}
	return policy, nil
}

func newGlobalDownloadCatalogs(assetRoot string, evidence globalCatalogEvidence) (*GlobalDownloadCatalogPolicy, error) {
	policy := &GlobalDownloadCatalogPolicy{evidence: evidence, sources: make(map[string]string)}
	knownNames := make(map[string]bool)
	for _, platform := range []string{"a", "i"} {
		if evidence.SourceSHA256[platform] == "" {
			continue
		}
		path := filepath.Join(assetRoot, "db", "jp", "asset_"+platform+"_ja.db")
		quiet, err := quietCatalogFile(path)
		if err != nil {
			return nil, err
		}
		if !quiet {
			continue
		}
		sha, err := jpGlobalFingerprint(path)
		if err != nil {
			return nil, err
		}
		if sha == evidence.SourceSHA256[platform] {
			policy.sources[platform] = path
			for _, language := range []string{"en", "ko", "zh"} {
				for _, name := range evidence.Catalogs["asset_"+platform+"_"+language+".db"] {
					knownNames[name] = true
				}
			}
		}
	}
	if len(knownNames) == 0 {
		return nil, nil
	}

	master := filepath.Join(assetRoot, "db", "gl", "masterdata.db")
	quiet, err := quietCatalogFile(master)
	if err != nil || !quiet {
		return nil, err
	}
	db, err := openJPGlobalReadOnly(master)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	policy.masterReferences, err = globalCatalogReferences(db, knownNames, nil)
	return policy, err
}

// quietCatalogFile excludes missing catalogs and those with an unresolved journal.
func quietCatalogFile(path string) (bool, error) {
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil || !info.Mode().IsRegular() {
		return false, err
	}
	for _, suffix := range []string{"-wal", "-journal"} {
		info, err := os.Stat(path + suffix)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil || info.Size() != 0 {
			return false, err
		}
	}
	return true, nil
}

func (p *GlobalDownloadCatalogPolicy) Prepare(sourcePath, destinationPath string) (int64, error) {
	name := filepath.Base(sourcePath)
	if selection, known := p.selection[name]; known {
		count, err := prepareSelectedGlobalCatalog(sourcePath, destinationPath, selection)
		if count != 0 || err != nil {
			return count, err
		}
	}
	parts := strings.Split(name, "_")
	if len(parts) != 3 || len(p.evidence.Catalogs[name]) == 0 || p.sources[parts[1]] == "" {
		return 0, nil
	}
	quiet, err := quietCatalogFile(sourcePath)
	if err != nil || !quiet {
		return 0, err
	}
	source, err := openJPGlobalReadOnly(sourcePath)
	if err != nil {
		return 0, err
	}
	merged, err := jpGlobalAlreadyMerged(source, p.evidence.SourceSHA256[parts[1]])
	source.Close()
	if err != nil || !merged {
		return 0, err
	}

	if err := copyGlobalCatalog(sourcePath, destinationPath); err != nil {
		return 0, err
	}
	keep := false
	defer func() {
		if !keep {
			os.Remove(destinationPath)
		}
	}()
	official := p.sources[parts[1]]
	removed, err := p.pruneCatalog(destinationPath, official, p.evidence.Catalogs[name])
	if removed == 0 || err != nil {
		return 0, err
	}
	quiet, err = quietCatalogFile(official)
	if err != nil || !quiet {
		return 0, err
	}
	currentSHA, err := jpGlobalFingerprint(official)
	if err != nil || currentSHA != p.evidence.SourceSHA256[parts[1]] {
		return 0, err
	}
	keep = true
	return removed, nil
}

// PreparedGlobalDownloadFiles resolves the whole files referenced by a served
// catalog, including metapacks that the installed catalog lists independently.
func PreparedGlobalDownloadFiles(sourcePath, servedPath string) (map[string]struct{}, error) {
	names := make(map[string]struct{})
	if err := readGlobalDownloadFiles(servedPath, `SELECT DISTINCT COALESCE(metapack_name, pack_name) FROM m_asset_package_mapping`, names); err != nil {
		return nil, err
	}
	independent := make(map[string]struct{})
	if err := readGlobalDownloadFiles(sourcePath, `SELECT metapack_name FROM metapack WHERE metapack_name NOT IN (
		SELECT DISTINCT metapack_name FROM m_asset_package_mapping WHERE metapack_name IS NOT NULL
	)`, independent); err != nil {
		return nil, err
	}
	if len(independent) != 0 {
		registered := make(map[string]struct{})
		if err := readGlobalDownloadFiles(servedPath, "SELECT metapack_name FROM metapack", registered); err != nil {
			return nil, err
		}
		for name := range independent {
			if _, kept := registered[name]; kept {
				names[name] = struct{}{}
			}
		}
	}
	return names, nil
}

func eligibleGlobalCatalogSelection(master string, packRoots []string) (map[string]globalCatalogDelta, error) {
	selection, err := loadGlobalCatalogSelection()
	if err != nil {
		return nil, err
	}
	stock, err := matchesGlobalCatalog(master, selection.MasterSHA256, selection.MasterContentSHA256)
	for _, compatible := range selection.CompatibleMasters {
		if stock || err != nil {
			break
		}
		stock, err = matchesGlobalCatalog(master, compatible.SHA256, compatible.ContentSHA256)
	}
	if err != nil {
		log.Printf("Using the compatibility GL catalog policy: %v", err)
	}
	if !stock {
		return nil, nil
	}
	names := make(map[string]bool)
	for _, catalog := range selection.Catalogs {
		for _, name := range catalog.ProtectedFiles {
			names[name] = true
		}
	}
	found, err := localGlobalCatalogOverrides(packRoots, names)
	if err != nil {
		log.Printf("Using the compatibility GL catalog policy: %v", err)
		return nil, nil
	}
	for profile, catalog := range selection.Catalogs {
		for _, name := range catalog.ProtectedFiles {
			if found[name] {
				delete(selection.Catalogs, profile)
				break
			}
		}
	}
	return selection.Catalogs, nil
}

func prepareSelectedGlobalCatalog(sourcePath, destinationPath string, selection globalCatalogDelta) (int64, error) {
	stock, err := matchesGlobalCatalog(sourcePath, selection.SourceSHA256, selection.SourceContentSHA256)
	if err != nil {
		log.Printf("Using the compatibility GL catalog policy for %s: %v", filepath.Base(sourcePath), err)
	}
	if !stock {
		return 0, nil
	}
	if err = copyGlobalCatalog(sourcePath, destinationPath); err != nil {
		return 0, err
	}
	count, err := applyGlobalCatalogSelection(destinationPath, selection)
	if count == 0 || err != nil {
		os.Remove(destinationPath)
	}
	return count, err
}

func readGlobalDownloadFiles(path, query string, names map[string]struct{}) error {
	db, err := openJPGlobalReadOnly(path)
	if err != nil {
		return err
	}
	defer db.Close()
	rows, err := db.Query(query)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var name sql.NullString
		if err := rows.Scan(&name); err != nil {
			return err
		}
		if name.Valid && name.String != "" {
			names[name.String] = struct{}{}
		}
	}
	return rows.Err()
}

func copyGlobalCatalog(sourcePath, destinationPath string) error {
	source, err := os.Open(sourcePath)
	if err != nil {
		return err
	}
	defer source.Close()
	destination, err := os.OpenFile(destinationPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(destination, source)
	closeErr := destination.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

// Fields which label catalog records, rather than refer to a pack's contents.
var globalCatalogLabels = map[string]map[string]bool{
	"m_asset_package_mapping": {"pack_name": true, "package_key": true},
	"m_asset_package":         {"package_key": true, "version": true},
	"m_asset_pack":            {"pack_name": true},
	"pack_category":           {"pack_name": true},
}

func globalCatalogReferences(db jpGlobalQueryer, names map[string]bool, labels map[string]map[string]bool) (map[string]bool, error) {
	tables, err := jpGlobalTables(db, "main")
	if err != nil {
		return nil, err
	}
	found := make(map[string]bool)
	for table, name := range tables {
		columns, err := jpGlobalColumns(db, "main", name)
		if err != nil {
			return nil, err
		}
		var fields []string
		for _, column := range columns {
			if labels[table][strings.ToLower(column.name)] {
				continue
			}
			kind := column.kind
			if kind != "" && !strings.Contains(kind, "TEXT") && !strings.Contains(kind, "CHAR") &&
				!strings.Contains(kind, "CLOB") && !strings.Contains(kind, "BLOB") {
				continue
			}
			fields = append(fields, quoteJPGlobalIdentifier(column.name))
		}
		if len(fields) == 0 {
			continue
		}
		rows, err := db.Query("SELECT " + strings.Join(fields, ", ") + " FROM main." + quoteJPGlobalIdentifier(name))
		if err != nil {
			return nil, err
		}
		values := make([]sql.RawBytes, len(fields))
		destinations := make([]any, len(fields))
		for index := range values {
			destinations[index] = &values[index]
		}
		for rows.Next() {
			if err := rows.Scan(destinations...); err != nil {
				rows.Close()
				return nil, err
			}
			for _, value := range values {
				markCatalogPackTokens(value, names, found)
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	return found, nil
}

// Some owner references store a path or a token in a larger field.
func markCatalogPackTokens(value []byte, names, found map[string]bool) {
	start := 0
	for end, char := range value {
		if char >= '0' && char <= '9' || char >= 'A' && char <= 'Z' || char >= 'a' && char <= 'z' {
			continue
		}
		if end-start == 6 && names[string(value[start:end])] {
			found[string(value[start:end])] = true
		}
		start = end + 1
	}
	if len(value)-start == 6 && names[string(value[start:])] {
		found[string(value[start:])] = true
	}
}

func (p *GlobalDownloadCatalogPolicy) pruneCatalog(path, officialPath string, approved []string) (int64, error) {
	db, err := openExisting(path)
	if err != nil {
		return 0, err
	}
	defer db.Close()
	absolute, err := filepath.Abs(officialPath)
	if err != nil {
		return 0, err
	}
	uri := databaseFileURL(filepath.ToSlash(absolute))
	uri.RawQuery = url.Values{"mode": {"ro"}, "immutable": {"1"}}.Encode()
	if _, err = db.Exec("ATTACH DATABASE ? AS official", uri.String()); err != nil {
		return 0, err
	}
	tx, err := db.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	plan, err := jpGlobalPlan(tx, "main", tx, "official", true)
	if err != nil {
		// A custom catalog with different columns is outside the audited schema.
		return 0, nil
	}
	officialTables, err := jpGlobalTables(tx, "official")
	if err != nil {
		return 0, err
	}
	if len(plan) != len(officialTables) {
		// A missing source lookup table would make the replacement proof incomplete.
		return 0, nil
	}
	var hasTriggers bool
	if err := tx.QueryRow("SELECT EXISTS(SELECT 1 FROM main.sqlite_master WHERE type = 'trigger')").Scan(&hasTriggers); err != nil || hasTriggers {
		return 0, err
	}
	names := make(map[string]bool, len(approved))
	for _, name := range approved {
		names[name] = true
	}
	references, err := globalCatalogReferences(tx, names, globalCatalogLabels)
	if err != nil {
		return 0, err
	}
	for _, statement := range []string{
		"CREATE TEMP TABLE candidates (pack_name TEXT PRIMARY KEY)",
		"CREATE TEMP TABLE alternatives (pack_name TEXT NOT NULL, replacement TEXT, head INTEGER, size INTEGER)",
		"CREATE TEMP TABLE removals (package_key TEXT NOT NULL, pack_name TEXT NOT NULL, PRIMARY KEY (package_key, pack_name))",
	} {
		if _, err := tx.Exec(statement); err != nil {
			return 0, err
		}
	}
	insert, err := tx.Prepare("INSERT INTO temp.candidates VALUES (?)")
	if err != nil {
		return 0, err
	}
	for _, name := range approved {
		if p.masterReferences[name] || references[name] {
			continue
		}
		if _, err := insert.Exec(name); err != nil {
			insert.Close()
			return 0, err
		}
	}
	if err := insert.Close(); err != nil {
		return 0, err
	}

	for _, table := range plan {
		if !isGlobalCatalogRangeTable(table) {
			continue
		}
		_, err := tx.Exec("INSERT INTO temp.alternatives " +
			"SELECT j.pack_name, g.pack_name, g.head, g.size FROM official." + quoteJPGlobalIdentifier(table.sourceName) +
			" AS j JOIN temp.candidates AS names ON names.pack_name = j.pack_name LEFT JOIN main." +
			quoteJPGlobalIdentifier(table.name) + " AS g ON g.asset_path = j.asset_path")
		if err != nil {
			return 0, fmt.Errorf("%s: %w", table.name, err)
		}
	}
	for _, statement := range globalCatalogRemovalStatements {
		if _, err := tx.Exec(statement); err != nil {
			return 0, err
		}
	}
	changed, err := globalCatalogPackageChanges(tx)
	if err != nil || len(changed) == 0 {
		return 0, err
	}
	result, err := tx.Exec(`DELETE FROM main.m_asset_package_mapping
		WHERE (package_key, pack_name) IN (SELECT package_key, pack_name FROM temp.removals)`)
	if err != nil {
		return 0, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return 0, err
	}
	columns := jpGlobalMappingColumns(plan)
	for _, packageKey := range changed {
		var remaining int64
		if err = tx.QueryRow("SELECT COUNT(*) FROM main.m_asset_package_mapping WHERE package_key = ?", packageKey).Scan(&remaining); err != nil {
			return 0, err
		}
		if err = writeJPGlobalPackage(tx, columns, packageKey, remaining); err != nil {
			return 0, err
		}
	}
	return count, tx.Commit()
}

func isGlobalCatalogRangeTable(table jpGlobalTable) bool {
	columns := make(map[string]bool, len(table.columns))
	for _, column := range table.columns {
		columns[strings.ToLower(column.name)] = true
	}
	return columns["asset_path"] && columns["pack_name"] && columns["head"] && columns["size"]
}

var globalCatalogRemovalStatements = []string{
	"CREATE INDEX temp.alternatives_pack ON alternatives(pack_name)",
	// An owner may have changed a mapping, retained a new membership, or set a
	// different local pack policy. Preserve the pack in every package in that case.
	`DELETE FROM temp.candidates WHERE pack_name IN (
		SELECT g.pack_name FROM main.m_asset_package_mapping AS g
		JOIN temp.candidates AS c ON c.pack_name = g.pack_name
		LEFT JOIN official.m_asset_package_mapping AS j
			ON j.package_key = g.package_key AND j.pack_name = g.pack_name
			AND j.file_size = g.file_size AND j.metapack_name IS g.metapack_name
			AND j.metapack_offset = g.metapack_offset AND j.category = g.category
		WHERE j.pack_name IS NULL
		UNION ALL
		SELECT c.pack_name FROM temp.candidates AS c
		LEFT JOIN main.m_asset_pack AS g ON g.pack_name = c.pack_name
		LEFT JOIN official.m_asset_pack AS j ON j.pack_name = c.pack_name
		WHERE g.auto_delete IS NOT j.auto_delete OR g.pack_name IS NULL
	)`,
	// Every translated lookup must resolve to a distinct, complete file range
	// already selected by this same package. Keep the JP edge on any ambiguity.
	`INSERT INTO temp.removals
		SELECT g.package_key, g.pack_name FROM main.m_asset_package_mapping AS g
		JOIN temp.candidates AS c ON c.pack_name = g.pack_name
		WHERE EXISTS (SELECT 1 FROM temp.alternatives AS a WHERE a.pack_name = g.pack_name)
		AND NOT EXISTS (
			SELECT 1 FROM temp.alternatives AS a
			LEFT JOIN main.m_asset_package_mapping AS keep
				ON keep.package_key = g.package_key AND keep.pack_name = a.replacement
			LEFT JOIN main.metapack AS meta ON meta.metapack_name = keep.metapack_name
			WHERE a.pack_name = g.pack_name AND (
				keep.pack_name IS NULL OR keep.pack_name = g.pack_name
				OR a.head IS NULL OR a.size IS NULL OR a.head < 0 OR a.size <= 0
				OR a.head > keep.file_size - a.size
				OR (keep.metapack_name IS NOT NULL AND (
					meta.metapack_name IS NULL OR keep.metapack_offset < 0
					OR keep.metapack_offset > meta.file_size - keep.file_size
				))
			)
		)`,
}

func globalCatalogPackageChanges(tx *sql.Tx) ([]string, error) {
	rows, err := tx.Query("SELECT DISTINCT package_key FROM temp.removals ORDER BY package_key")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var changed []string
	for rows.Next() {
		var key string
		if err := rows.Scan(&key); err != nil {
			return nil, err
		}
		changed = append(changed, key)
	}
	return changed, rows.Err()
}
