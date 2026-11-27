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
	// The asset's stage fields before the override (stage column {"original": {...}}), when it has one.
	originalStage map[string]any
	// The source MV's packs a cross-slot override added to live:<asset> (extras column {schema: [pack
	// names]}, the JP schemas asset_a_ja and asset_i_ja). They are JP stock packs of live:<source>.
	extras map[string][]string
}

// jpGlobalStageFields are the m_live_3d_asset stage fields an override may swap (mv_studio_stock.STAGE_FIELDS).
var jpGlobalStageFields = []string{"live_stage_master_id", "stage_effect_asset_path", "live_prop_skeleton_asset_path",
	"quality_setitng_set_id", "shader_variant_asset_path"}

type jpGlobalOverrides struct {
	items []jpGlobalOverride
	keys  []string // override timeline keys (live_timeline, live_timeline_dependency asset_path)
	packs []string // override pack names (m_asset_package_mapping, m_asset_pack pack_name)
	// schema is the JP asset catalog of the merge pair (asset_a_ja, asset_i_ja); "" for masterdata.
	schema string
}

// jpGlobalMasterPath is the JP masterdata of a merge pair: the source itself, or the masterdata
// next to a JP asset catalog.
func jpGlobalMasterPath(pair jpGlobalPair) string {
	if !pair.asset {
		return pair.source
	}
	return filepath.Join(filepath.Dir(pair.source), "masterdata.db")
}

// readJPGlobalPairOverrides lists the JP overrides for one merge pair (its catalog's extras).
func readJPGlobalPairOverrides(pair jpGlobalPair) (jpGlobalOverrides, error) {
	overrides, err := readJPGlobalOverrides(jpGlobalMasterPath(pair))
	if err == nil && pair.asset {
		overrides.schema = strings.TrimSuffix(filepath.Base(pair.source), filepath.Ext(pair.source))
	}
	return overrides, err
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
	// Overrides written before the cross-slot version have no stage column.
	var hasStage bool
	if err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM pragma_table_info(?) WHERE name = 'stage')", jpGlobalStockTimelines).Scan(&hasStage); err != nil {
		return result, err
	}
	stageColumn := "'{}'"
	if hasStage {
		stageColumn = "stage"
	}
	var hasExtras bool
	if err = db.QueryRow("SELECT EXISTS(SELECT 1 FROM pragma_table_info(?) WHERE name = 'extras')", jpGlobalStockTimelines).Scan(&hasExtras); err != nil {
		return result, err
	}
	extrasColumn := "'{}'"
	if hasExtras {
		extrasColumn = "extras"
	}
	rows, err := db.Query("SELECT asset_id, stock_key, timeline_key, packs, " + stageColumn + ", " + extrasColumn + " FROM " + quoteJPGlobalIdentifier(jpGlobalStockTimelines) + " ORDER BY asset_id")
	if err != nil {
		return result, fmt.Errorf("%s: %w", jpGlobalStockTimelines, err)
	}
	defer rows.Close()
	keys, packs := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var item jpGlobalOverride
		var encoded, stage, extras string
		if err = rows.Scan(&item.asset, &item.stockKey, &item.timelineKey, &encoded, &stage, &extras); err != nil {
			return result, fmt.Errorf("%s: %w", jpGlobalStockTimelines, err)
		}
		if err = json.Unmarshal([]byte(extras), &item.extras); err != nil {
			return result, fmt.Errorf("%s: asset %d extras: %w", jpGlobalStockTimelines, item.asset, err)
		}
		for _, names := range item.extras {
			for _, name := range names {
				if name == "" {
					return result, fmt.Errorf("%s: asset %d has an invalid extra pack name", jpGlobalStockTimelines, item.asset)
				}
			}
		}
		var stages struct {
			Original map[string]any `json:"original"`
		}
		if stage != "" && json.Unmarshal([]byte(stage), &stages) == nil {
			item.originalStage = stages.Original
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

// exclusion is the extra WHERE condition that keeps a JP override's rows out of one table's insert:
// its keys and packs, and the source packs it added to live:<asset>. Those source packs stay in
// live:<source> (they are its stock packs) and their m_asset_pack rows are copied as usual: only
// the live:<asset> mapping rows of that asset are left out, so GL's live:<asset> header and
// downloads do not change.
func (o jpGlobalOverrides) exclusion(table jpGlobalTable) (string, []any) {
	condition, args := o.packExclusion(table)
	if !strings.EqualFold(table.name, "m_asset_package_mapping") || o.schema == "" {
		return condition, args
	}
	packageColumn, packColumn := jpGlobalColumnName(table, "package_key"), jpGlobalColumnName(table, "pack_name")
	if packageColumn == "" || packColumn == "" {
		return condition, args
	}
	for _, item := range o.items {
		var names []string
		for schema, values := range item.extras {
			if strings.EqualFold(schema, o.schema) {
				names = append(names, values...)
			}
		}
		if len(names) == 0 {
			continue
		}
		sort.Strings(names)
		condition += " AND NOT (" + packageColumn + " = ? AND " + packColumn + " IN (" +
			strings.TrimSuffix(strings.Repeat("?, ", len(names)), ", ") + "))"
		args = append(args, fmt.Sprintf("live:%d", item.asset))
		for _, name := range names {
			args = append(args, name)
		}
	}
	return condition, args
}

// jpGlobalColumnName is the quoted name of one of the table's columns, or "" when it has none.
func jpGlobalColumnName(table jpGlobalTable, name string) string {
	for _, column := range table.columns {
		if strings.EqualFold(column.name, name) {
			return quoteJPGlobalIdentifier(column.name)
		}
	}
	return ""
}

// packExclusion keeps a JP override's own timeline keys and packs out of one table's insert.
func (o jpGlobalOverrides) packExclusion(table jpGlobalTable) (string, []any) {
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
// at its stock key, and puts back the stage fields the override swapped. An MV with GL's own
// override keeps it.
//
// A stage-only override (the timeline key is the stock key, mv_studio_stock writes one when only the
// stage changes) has no key of its own to find the copied row by: its stage fields are put back
// only on a row the merge copied from JP, never on one GL had before (glAssets).
func (o jpGlobalOverrides) restoreStockTimelines(tx *sql.Tx, plan []jpGlobalTable, glAssets map[int64]bool) error {
	if len(o.items) == 0 {
		return nil
	}
	found := false
	columns := map[string]bool{}
	for _, table := range plan {
		if strings.EqualFold(table.name, "m_live_3d_asset") {
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
		stageOnly := item.timelineKey == item.stockKey
		if stageOnly && (len(item.originalStage) == 0 || glAssets[item.asset]) {
			continue
		}
		var sets []string
		var args []any
		if !stageOnly {
			sets, args = append(sets, "timeline = ?"), append(args, item.stockKey)
		}
		for _, field := range jpGlobalStageFields {
			if value, ok := item.originalStage[field]; ok && columns[field] {
				if number, isNumber := value.(float64); isNumber {
					value = int64(number)
				}
				sets = append(sets, quoteJPGlobalIdentifier(field)+" = ?")
				args = append(args, value)
			}
		}
		if len(sets) == 0 {
			continue
		}
		query := "UPDATE main.m_live_3d_asset SET " + strings.Join(sets, ", ") + " WHERE id = ? AND timeline = ?"
		if own {
			query += " AND NOT EXISTS (SELECT 1 FROM main." + quoteJPGlobalIdentifier(jpGlobalStockTimelines) + " WHERE asset_id = ?)"
		}
		args = append(args, item.asset, item.timelineKey)
		if own {
			args = append(args, item.asset)
		}
		if _, err := tx.Exec(query, args...); err != nil {
			return fmt.Errorf("m_live_3d_asset: %w", err)
		}
	}
	return nil
}

// glAssets lists the stage-only overridden assets GL's m_live_3d_asset has before the merge
// inserts JP's rows (restoreStockTimelines leaves those rows as GL has them).
func (o jpGlobalOverrides) glAssets(tx *sql.Tx, plan []jpGlobalTable) (map[int64]bool, error) {
	assets := map[int64]bool{}
	found := false
	for _, table := range plan {
		found = found || strings.EqualFold(table.name, "m_live_3d_asset")
	}
	if !found {
		return assets, nil
	}
	for _, item := range o.items {
		if item.timelineKey != item.stockKey || len(item.originalStage) == 0 {
			continue
		}
		var exists bool
		if err := tx.QueryRow("SELECT EXISTS(SELECT 1 FROM main.m_live_3d_asset WHERE id = ?)", item.asset).Scan(&exists); err != nil {
			return nil, fmt.Errorf("m_live_3d_asset: %w", err)
		}
		assets[item.asset] = exists
	}
	return assets, nil
}
