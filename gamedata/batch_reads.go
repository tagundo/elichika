package gamedata

import (
	"strconv"
	"strings"

	"xorm.io/xorm"
)

// batchReadOrderSafe limits grouped startup reads to the indexed row order used
// by the shipped schema. A mod may add/change an index (and therefore the order
// of an unordered Find/Get); retain the original per-owner queries in that case.
// Table and column names below come only from loader constants, never requests.
func batchReadOrderSafe(session *xorm.Session, table string, primaryKey []string, uniqueKeys ...[]string) (bool, error) {
	columns, err := session.QueryString("PRAGMA table_info(" + table + ")")
	if err != nil {
		return false, err
	}
	key := make([]string, len(primaryKey))
	count := 0
	for _, column := range columns {
		position, err := strconv.Atoi(column["pk"])
		if err != nil {
			return false, err
		}
		if position == 0 {
			continue
		}
		if position > len(key) || !strings.EqualFold(column["type"], "INTEGER") {
			return false, nil
		}
		key[position-1] = column["name"]
		count++
	}
	if count != len(key) || strings.Join(key, ",") != strings.Join(primaryKey, ",") {
		return false, nil
	}
	indexes, err := session.QueryString("PRAGMA index_list(" + table + ")")
	if err != nil {
		return false, err
	}
	for _, index := range indexes {
		if index["origin"] != "pk" && index["origin"] != "u" {
			return false, nil
		}
		// A single INTEGER primary key must remain SQLite's rowid alias.
		if index["origin"] == "pk" && len(primaryKey) == 1 {
			return false, nil
		}
		parts, err := session.QueryString("PRAGMA index_xinfo('" + strings.ReplaceAll(index["name"], "'", "''") + "')")
		if err != nil {
			return false, err
		}
		var names []string
		for _, part := range parts {
			if part["key"] == "0" {
				continue
			}
			if part["desc"] != "0" || part["coll"] != "BINARY" {
				return false, nil
			}
			names = append(names, part["name"])
		}
		if index["origin"] == "pk" {
			if strings.Join(names, ",") != strings.Join(primaryKey, ",") {
				return false, nil
			}
			continue
		}
		allowed := false
		for _, uniqueKey := range uniqueKeys {
			if strings.Join(names, ",") == strings.Join(uniqueKey, ",") {
				allowed = true
				break
			}
		}
		if !allowed {
			return false, nil
		}
	}
	return true, nil
}

// The related gameplay tables are small enough for one compact slice. Find
// avoids Iterate's per-row reflection/scan setup; the large asset catalog keeps
// its separate streaming path instead.
func batchRows[T any](session *xorm.Session, _ *T, apply xorm.IterFunc) error {
	var rows []T
	if err := session.Find(&rows); err != nil {
		return err
	}
	for i := range rows {
		if err := apply(i, &rows[i]); err != nil {
			return err
		}
	}
	return nil
}
