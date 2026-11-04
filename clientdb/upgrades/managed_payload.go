package upgrades

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// A managed installer has already merged the APK's initialized GL catalog into
// the retained databases. Reimporting the retained JP databases would also copy
// JP-only owner mods into GL, and can reject valid custom columns. The committed
// installer contract separates that operation from ordinary standalone imports.
type managedContentState struct {
	ContractVersion   int                            `json:"contract_version"`
	PayloadVersion    string                         `json:"payload_version"`
	Algorithm         string                         `json:"jp_global_algorithm"`
	Integrated        bool                           `json:"jp_global_integrated"`
	BaselineFormat    int                            `json:"baseline_format"`
	BaselineIndex     string                         `json:"baseline_index"`
	IncomingDatabases map[string]managedContentInput `json:"incoming_databases"`
	Coverage          []managedContentCoverage       `json:"jp_global_coverage"`
}

type managedContentInput struct {
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}

type managedContentCoverage struct {
	Source    string `json:"source"`
	Target    string `json:"target"`
	SourceSHA string `json:"source_sha256"`
	Algorithm string `json:"algorithm_version"`
}

func managedContentRead(path string, limit int64) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > limit {
		return nil, fmt.Errorf("managed payload metadata must be a bounded regular file")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, fmt.Errorf("cannot read managed payload metadata")
	}
	return data, nil
}

func managedContentDatabase(root, relative string) (os.FileInfo, error) {
	path := filepath.Join(root, filepath.FromSlash(relative))
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() < 100 {
		return nil, fmt.Errorf("managed payload database missing or invalid: %s", relative)
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("cannot read managed payload database: %s", relative)
	}
	defer f.Close()
	header := make([]byte, 16)
	if _, err = io.ReadFull(f, header); err != nil || string(header) != "SQLite format 3\x00" {
		return nil, fmt.Errorf("managed payload database header invalid: %s", relative)
	}
	return info, nil
}

func managedContentSHA(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == 32
}

func managedJapaneseContent(assetRoot, algorithm string) (bool, error) {
	root := filepath.Clean(filepath.Join(assetRoot, ".."))
	if _, err := os.Lstat(filepath.Join(root, ".payload-upgrade", "needs-rebase")); err == nil {
		return false, fmt.Errorf("restored managed databases require APK setup before startup")
	} else if !os.IsNotExist(err) {
		return false, fmt.Errorf("cannot inspect managed database restore state")
	}
	path := filepath.Join(root, ".payload-upgrade", "current.json")
	data, err := managedContentRead(path, 1024*1024)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("managed payload state is unreadable: %w", err)
	}
	var state managedContentState
	decoder := json.NewDecoder(bytes.NewReader(data))
	if err = decoder.Decode(&state); err != nil {
		return false, fmt.Errorf("managed payload state is invalid")
	}
	if err = decoder.Decode(new(any)); err != io.EOF {
		return false, fmt.Errorf("managed payload state contains trailing data")
	}
	installed, err := managedContentRead(filepath.Join(root, "installed_version"), 4096)
	if err != nil || state.PayloadVersion == "" || strings.TrimSpace(string(installed)) != state.PayloadVersion {
		return false, fmt.Errorf("managed payload version is not committed; run APK setup recovery")
	}
	if state.ContractVersion != 1 || state.BaselineFormat != 1 ||
		state.Algorithm != algorithm || !state.Integrated ||
		state.BaselineIndex != ".payload-upgrade/baseline.sqlite" {
		return false, fmt.Errorf("managed payload content contract is incompatible or incomplete")
	}
	if _, err = managedContentDatabase(root, state.BaselineIndex); err != nil {
		return false, err
	}
	expected := map[string]string{"assets/db/gl/masterdata.db": "assets/db/jp/masterdata.db"}
	for _, platform := range []string{"a", "i"} {
		for _, language := range []string{"en", "ko", "zh"} {
			expected["assets/db/gl/asset_"+platform+"_"+language+".db"] = "assets/db/jp/asset_" + platform + "_ja.db"
		}
	}
	if len(state.Coverage) != len(expected) {
		return false, fmt.Errorf("managed payload content coverage is incomplete")
	}
	checked := map[string]os.FileInfo{}
	checkInput := func(relative string) (os.FileInfo, error) {
		if info, ok := checked[relative]; ok {
			return info, nil
		}
		input, ok := state.IncomingDatabases[relative]
		if !ok || !managedContentSHA(input.SHA256) || input.Bytes < 100 {
			return nil, fmt.Errorf("managed payload baseline provenance missing: %s", relative)
		}
		info, err := managedContentDatabase(root, relative)
		if err == nil {
			checked[relative] = info
		}
		return info, err
	}
	seen := map[string]bool{}
	for _, coverage := range state.Coverage {
		source, ok := expected[coverage.Target]
		if !ok || seen[coverage.Target] || coverage.Source != source || coverage.Algorithm != algorithm {
			return false, fmt.Errorf("managed payload content coverage is invalid")
		}
		seen[coverage.Target] = true
		sourceInfo, err := checkInput(source)
		if err != nil {
			return false, err
		}
		targetInfo, err := checkInput(coverage.Target)
		if err != nil {
			return false, err
		}
		if os.SameFile(sourceInfo, targetInfo) ||
			coverage.SourceSHA != state.IncomingDatabases[source].SHA256 {
			return false, fmt.Errorf("managed payload content provenance is invalid")
		}
	}
	// These required dictionaries accompany the initialized catalog. Their current
	// hashes intentionally need not match stock: users can install further mods.
	for _, language := range []string{"ja", "en", "ko", "zh"} {
		region := "gl"
		if language == "ja" {
			region = "jp"
		}
		if _, err = checkInput("assets/db/" + region + "/dictionary_" + language + "_k.db"); err != nil {
			return false, err
		}
	}
	return true, nil
}
