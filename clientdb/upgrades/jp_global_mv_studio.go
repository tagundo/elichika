package upgrades

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// MV Studio stock timeline overrides are region-local.
//
// MV Studio's "apply to game" (mv_studio_stock.py) makes a stock 3D MV of one region play another
// timeline: a new random timeline key in every asset catalog of that region (live_timeline and
// live_timeline_dependency rows), the override packs added to the asset's own package
// live:<asset> (m_asset_package_mapping, m_asset_pack), m_live_3d_asset.timeline of that asset
// pointed at the new key, and one bookkeeping row in masterdata _elichika_mv_studio_timeline.
//
// None of it belongs to the other region. Copied into GL, it would rewrite GL's live:<asset>
// header (GL clients download a pack that GL never plays), keep the JP pack named by GL catalogs
// so it is never cleaned up, and give GL a bookkeeping row for an MV that GL still plays as stock.
// So the JP to GL merge leaves out the bookkeeping table and every catalog row of a JP override,
// and a JP-only 3D MV copied into GL plays its stock timeline. MV-only songs
// (_elichika_mv_studio_song) keep the merge's usual rules: their ids are region-disjoint by design.
const jpGlobalStockTimelines = "_elichika_mv_studio_timeline"

type jpGlobalOverride struct {
	asset                 int64
	stockKey, timelineKey string
}

type jpGlobalOverrides struct {
	items []jpGlobalOverride
	keys  []string // override timeline keys (live_timeline, live_timeline_dependency asset_path)
	packs []string // override pack names (m_asset_package_mapping, m_asset_pack pack_name)
}

// jpGlobalMasterPath is the JP masterdata of a merge pair: the source itself, or the masterdata
// next to a JP asset catalog.
func jpGlobalMasterPath(pair jpGlobalPair) string {
	if !pair.asset {
		return pair.source
	}
	return filepath.Join(filepath.Dir(pair.source), "masterdata.db")
}

// readJPGlobalOverrides lists the JP region's MV Studio stock overrides. A JP masterdata without
// the bookkeeping table (or without a masterdata next to the catalog) has none.
func readJPGlobalOverrides(path string) (jpGlobalOverrides, error) {
	var result jpGlobalOverrides
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return result, nil
	} else if err != nil {
		return result, err
	}
	db, err := openJPGlobalReadOnly(path)
	if err != nil {
		return result, err
	}
	defer db.Close()
	var exists bool
	if err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE)", jpGlobalStockTimelines).Scan(&exists); err != nil || !exists {
		return result, err
	}
	rows, err := db.Query("SELECT asset_id, stock_key, timeline_key, packs FROM " + quoteJPGlobalIdentifier(jpGlobalStockTimelines) + " ORDER BY asset_id")
	if err != nil {
		return result, fmt.Errorf("%s: %w", jpGlobalStockTimelines, err)
	}
	defer rows.Close()
	keys, packs := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var item jpGlobalOverride
		var encoded string
		if err = rows.Scan(&item.asset, &item.stockKey, &item.timelineKey, &encoded); err != nil {
			return result, fmt.Errorf("%s: %w", jpGlobalStockTimelines, err)
		}
		// {"android": [pack, size] | null, "ios": [pack, size] | null}
		var platforms map[string][]any
		if err = json.Unmarshal([]byte(encoded), &platforms); err != nil {
			return result, fmt.Errorf("%s: asset %d packs: %w", jpGlobalStockTimelines, item.asset, err)
		}
		for _, pack := range platforms {
			if len(pack) == 0 {
				continue
			}
			name, ok := pack[0].(string)
			if !ok || name == "" {
				return result, fmt.Errorf("%s: asset %d has an invalid pack name", jpGlobalStockTimelines, item.asset)
			}
			packs[name] = true
		}
		if item.timelineKey != item.stockKey {
			keys[item.timelineKey] = true
		}
		result.items = append(result.items, item)
	}
	if err = rows.Err(); err != nil {
		return result, err
	}
	for key := range keys {
		result.keys = append(result.keys, key)
	}
	for pack := range packs {
		result.packs = append(result.packs, pack)
	}
	sort.Strings(result.keys)
	sort.Strings(result.packs)
	return result, nil
}

// exclusion is the extra WHERE condition that keeps a JP override's rows out of one table's insert.
func (o jpGlobalOverrides) exclusion(table jpGlobalTable) (string, []any) {
	var column string
	var values []string
	switch strings.ToLower(table.name) {
	case "live_timeline", "live_timeline_dependency":
		column, values = "asset_path", o.keys
	case "m_asset_package_mapping", "m_asset_pack":
		column, values = "pack_name", o.packs
	}
	if len(values) == 0 {
		return "", nil
	}
	for _, item := range table.columns {
		if strings.EqualFold(item.name, column) {
			marks := strings.TrimSuffix(strings.Repeat("?, ", len(values)), ", ")
			args := make([]any, len(values))
			for index, value := range values {
				args[index] = value
			}
			return " AND " + quoteJPGlobalIdentifier(item.name) + " NOT IN (" + marks + ")", args
		}
	}
	return "", nil
}

// restoreStockTimelines points a JP-only 3D MV that the merge copied with its JP override key back
// at its stock key. An MV with GL's own override keeps it.
func (o jpGlobalOverrides) restoreStockTimelines(tx *sql.Tx, plan []jpGlobalTable) error {
	if len(o.items) == 0 {
		return nil
	}
	found := false
	for _, table := range plan {
		if strings.EqualFold(table.name, "m_live_3d_asset") {
			columns := map[string]bool{}
			for _, column := range table.columns {
				columns[strings.ToLower(column.name)] = true
			}
			found = columns["id"] && columns["timeline"]
		}
	}
	if !found {
		return nil
	}
	var own bool
	if err := tx.QueryRow("SELECT EXISTS(SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE)", jpGlobalStockTimelines).Scan(&own); err != nil {
		return err
	}
	for _, item := range o.items {
		if item.timelineKey == item.stockKey {
			continue
		}
		query := "UPDATE main.m_live_3d_asset SET timeline = ? WHERE id = ? AND timeline = ?"
		if own {
			query += " AND NOT EXISTS (SELECT 1 FROM main." + quoteJPGlobalIdentifier(jpGlobalStockTimelines) + " WHERE asset_id = ?)"
		}
		args := []any{item.stockKey, item.asset, item.timelineKey}
		if own {
			args = append(args, item.asset)
		}
		if _, err := tx.Exec(query, args...); err != nil {
			return fmt.Errorf("m_live_3d_asset: %w", err)
		}
	}
	return nil
}
