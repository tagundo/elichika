// Read-only source-bound consumers. Run from the exact product Go module to use
// the product modernc.org/sqlite version, rather than Python's SQLite planner.
// This is supplemental to compare_sqlite.py; it never allows changed DB values.
package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"sort"

	_ "modernc.org/sqlite"
)

type MemberGroup struct {
	Language  string   `json:"language"`
	TheaterID int64    `json:"daily_theater_id"`
	Members   []int64  `json:"members"`
	Plan      []string `json:"query_plan"`
}

type Snapshot struct {
	Path             string                       `json:"path"`
	FileSHA256       string                       `json:"file_sha256"`
	SQLiteVersion    string                       `json:"sqlite_version"`
	DictionaryHashes map[string]string            `json:"dictionary_key_text_map_sha256"`
	DictionaryCounts map[string]int               `json:"dictionary_key_counts"`
	Dictionaries     map[string]map[string]string `json:"-"`
	Groups           []MemberGroup                `json:"daily_theater_member_groups"`
}

func check(err error) {
	if err != nil {
		panic(err)
	}
}
func hashBytes(b []byte) string  { value := sha256.Sum256(b); return hex.EncodeToString(value[:]) }
func hashValue(value any) string { b, err := json.Marshal(value); check(err); return hashBytes(b) }

func capture(path string) Snapshot {
	absolute, err := filepath.Abs(path)
	check(err)
	before, err := os.ReadFile(absolute)
	check(err)
	for _, suffix := range []string{"-wal", "-journal"} {
		if info, err := os.Stat(absolute + suffix); err == nil && info.Size() > 0 {
			panic("nonempty SQLite sidecar: " + absolute + suffix)
		} else if err != nil && !os.IsNotExist(err) {
			panic(err)
		}
	}
	u := url.URL{Scheme: "file", Path: filepath.ToSlash(absolute), RawQuery: "mode=ro&immutable=1"}
	db, err := sql.Open("sqlite", u.String())
	check(err)
	db.SetMaxOpenConns(1)
	defer db.Close()
	_, err = db.Exec("PRAGMA query_only=ON")
	check(err)
	result := Snapshot{Path: absolute, FileSHA256: hashBytes(before),
		DictionaryHashes: map[string]string{}, DictionaryCounts: map[string]int{},
		Dictionaries: map[string]map[string]string{}}
	check(db.QueryRow("SELECT sqlite_version()").Scan(&result.SQLiteVersion))
	for _, language := range []string{"ja", "en", "ko", "zh"} {
		// dictionary.Init constructs a Go map from these PK-unique rows; scan order
		// is not consumed by dictionary.ServerResolve/UniversalResolve.
		rows, err := db.Query("SELECT id,message FROM s_dictionary_" + language)
		check(err)
		pairs := map[string]string{}
		for rows.Next() {
			var key, value string
			check(rows.Scan(&key, &value))
			if _, exists := pairs[key]; exists {
				panic("duplicate dictionary key")
			}
			pairs[key] = value
		}
		check(rows.Err())
		check(rows.Close())
		result.Dictionaries[language] = pairs
		result.DictionaryHashes[language] = hashValue(pairs)
		result.DictionaryCounts[language] = len(pairs)
	}
	rows, err := db.Query("SELECT DISTINCT lang,daily_theater_id FROM s_daily_theater_member ORDER BY lang,daily_theater_id")
	check(err)
	var keys []MemberGroup
	for rows.Next() {
		var group MemberGroup
		check(rows.Scan(&group.Language, &group.TheaterID))
		keys = append(keys, group)
	}
	check(rows.Err())
	check(rows.Close())
	for _, group := range keys {
		// Exactly the unordered projection consumed by loadDailyTheater.
		query := "SELECT member_master_id FROM s_daily_theater_member WHERE lang=? AND daily_theater_id=?"
		members, err := db.Query(query, group.Language, group.TheaterID)
		check(err)
		group.Members = []int64{}
		for members.Next() {
			var member int64
			check(members.Scan(&member))
			group.Members = append(group.Members, member)
		}
		check(members.Err())
		check(members.Close())
		plans, err := db.Query("EXPLAIN QUERY PLAN "+query, group.Language, group.TheaterID)
		check(err)
		for plans.Next() {
			var id, parent, aux int64
			var detail string
			check(plans.Scan(&id, &parent, &aux, &detail))
			group.Plan = append(group.Plan, detail)
		}
		check(plans.Err())
		check(plans.Close())
		result.Groups = append(result.Groups, group)
	}
	after, err := os.ReadFile(absolute)
	check(err)
	if hashBytes(before) != hashBytes(after) {
		panic("database changed during consumer comparison")
	}
	return result
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: consumer left.db right.db report.json")
		os.Exit(2)
	}
	left, right := capture(os.Args[1]), capture(os.Args[2])
	dictEqual := reflect.DeepEqual(left.Dictionaries, right.Dictionaries)
	memberEqual := true
	planEqual := true
	var differences []string
	if len(left.Groups) != len(right.Groups) {
		memberEqual = false
		planEqual = false
	}
	for index, group := range left.Groups {
		if index >= len(right.Groups) {
			break
		}
		other := right.Groups[index]
		if group.Language != other.Language || group.TheaterID != other.TheaterID || !reflect.DeepEqual(group.Members, other.Members) {
			memberEqual = false
			differences = append(differences, fmt.Sprintf("%s:%d", group.Language, group.TheaterID))
		}
		if !reflect.DeepEqual(group.Plan, other.Plan) {
			planEqual = false
		}
	}
	sort.Strings(differences)
	passed := dictEqual && memberEqual && planEqual && left.SQLiteVersion == right.SQLiteVersion
	status := "FAIL_CONSUMED_RESULTS_OR_PLAN_CHANGED"
	if passed {
		status = "PASS_SOURCE_BOUND_CONSUMER_RESULTS"
	}
	output := map[string]any{
		"status": status, "dictionary_key_text_maps_equal": dictEqual,
		"daily_theater_member_exact_sequences_equal": memberEqual,
		"daily_theater_query_plans_equal":            planEqual, "differing_group_keys": differences,
		"left": left, "right": right,
		"sql_without_order_by_is_tested_on_product_driver_not_a_sql_ordering_guarantee": true,
		"requires_separate_full_schema_typed_row_and_unexpected_rowid_delta_gate":       true,
	}
	b, err := json.MarshalIndent(output, "", "  ")
	check(err)
	check(os.WriteFile(os.Args[3], append(b, '\n'), 0600))
	fmt.Println(status)
	if !passed {
		os.Exit(1)
	}
}
