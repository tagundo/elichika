//go:build !embedded

package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"

	"elichika/assetdata"
	"elichika/config"
	"elichika/handler/asset"
)

// The app adapters and standalone command share the same publication pin and
// verifier so a release cannot send them to different Archive snapshots.
//
//go:embed archive-hosted-catalog.json
var archivePin string

//go:embed archive_profile_download.py
var archiveProvider string

//go:embed archive_profile_download_bridge.py
var archiveBridge string

func archiveScope(args []string) (assetdata.DownloadSelection, bool, error) {
	missing := len(args) > 0 && args[len(args)-1] == "--missing"
	if missing {
		args = args[:len(args)-1]
	}
	fields := []string{"both", "both", "all"}
	if len(args) > len(fields) {
		return assetdata.DownloadSelection{}, false, fmt.Errorf("usage: download_archive [region] [platform] [language] [--missing]")
	}
	for index, arg := range args {
		if arg == "" || strings.HasPrefix(arg, "-") {
			return assetdata.DownloadSelection{}, false, fmt.Errorf("invalid Archive scope %q", arg)
		}
		fields[index] = arg
	}
	scope := assetdata.DownloadSelection{Region: assetdata.Region(fields[0]), Platform: assetdata.Platform(fields[1]), Language: assetdata.Language(fields[2])}
	return scope, missing, scope.Validate()
}

func archiveRequired(scope assetdata.DownloadSelection) ([]string, error) {
	selected, err := asset.SelectedDownloadFiles(scope)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(selected))
	for name := range selected {
		names = append(names, name)
	}
	sort.Strings(names)
	return names, nil
}

func writeArchiveRequired(writer io.Writer, args []string) error {
	if len(args) != 3 {
		return fmt.Errorf("archive_required expects region, platform, and language")
	}
	scope, missing, err := archiveScope(args)
	if err != nil || missing {
		return fmt.Errorf("invalid required Archive scope")
	}
	names, err := archiveRequired(scope)
	if err != nil {
		return err
	}
	body, err := json.Marshal(names)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(writer, "ELICHIKA_ARCHIVE_REQUIRED=%s\n", body)
	return err
}

func runArchiveDownload(args []string) error {
	scope, missing, err := archiveScope(args)
	if err != nil {
		return err
	}
	var names []string
	if missing {
		names, err = archiveRequired(scope)
		if err != nil {
			return err
		}
	}
	namesJSON, err := json.Marshal(names)
	if err != nil {
		return err
	}
	var python string
	for _, candidate := range []string{"python3", "python"} {
		if path, err := exec.LookPath(candidate); err == nil {
			python = path
			break
		}
	}
	if python == "" {
		return fmt.Errorf("install Python 3.10 or newer for the Archive download command")
	}
	entry := `import json, sys, types
def bundled_module(name, source):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    exec(compile(source, name + ".py", "exec"), mod.__dict__)
    return mod
provider = bundled_module("archive_profile_download", ` + strconv.Quote(archiveProvider) + `)
bridge = bundled_module("archive_profile_download_bridge", ` + strconv.Quote(archiveBridge) + `)
def progress(packet):
    phase = packet["stage"]
    if phase in ("files", "complete"):
        print(f'Archive {phase}: {packet["completed_files"]}/{packet["total_files"]} files'
              f' ({bridge.byte_label(packet["completed_bytes"])} / {bridge.byte_label(packet["total_bytes"])}),'
              f' {packet["reused_files"]} reused', flush=True)
try:
    source = bridge.source_from_json(` + strconv.Quote(archivePin) + `)
    packs, static, region, platform, language = sys.argv[1:]
    provider.download(source, packs, static_packs=static, region=region, platform=platform,
                      language=language, required_names=json.loads(` + strconv.Quote(string(namesJSON)) + `), progress=progress)
except provider.DownloadError as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    sys.exit(130)
`
	process := exec.Command(python, "-I", "-B", "-", config.CdnPackDirectory(), config.StaticDataPath,
		string(scope.Region), string(scope.Platform), string(scope.Language))
	process.Stdin = strings.NewReader(entry)
	process.Stdout, process.Stderr = os.Stdout, os.Stderr
	return process.Run()
}
