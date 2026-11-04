package config

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

const resourceStartupCase = "ELICHIKA_TEST_RESOURCE_STARTUP_MODE"

func TestResourceModesDuringPackageInitialization(t *testing.T) {
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"free", "comfortable", "original", "unknown-mode"} {
		t.Run(mode, func(t *testing.T) {
			directory := t.TempDir()
			contents, err := json.Marshal(map[string]string{"resource_config_type": mode, "time_zone": "UTC"})
			if err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(filepath.Join(directory, "config.json"), contents, 0600); err != nil {
				t.Fatal(err)
			}
			// A normal call to Load after package initialization misses this bug.
			// Start a fresh process with the config already present before init.
			command := exec.Command(binary, "-test.run=^TestResourceStartupChild$")
			command.Dir = directory
			command.Env = append(os.Environ(), resourceStartupCase+"="+mode)
			if output, err := command.CombinedOutput(); err != nil {
				t.Fatalf("startup with %q: %v\n%s", mode, err, output)
			}
		})
	}
}

func TestResourceStartupChild(t *testing.T) {
	requested := os.Getenv(resourceStartupCase)
	if requested == "" {
		t.Skip("only run in a fresh startup subprocess")
	}
	wanted := requested
	if wanted == "unknown-mode" {
		wanted = "free"
	}
	if *Conf.ResourceConfigType != wanted {
		t.Fatalf("startup changed resource mode from %q to %q; want %q", requested, *Conf.ResourceConfigType, wanted)
	}
	preset := Conf.ResourceConfig()
	if preset == nil || preset.ConsumePracticeItems != (wanted != "free") || preset.ConsumeLp != (wanted == "original") {
		t.Fatalf("wrong startup resource preset for %q: %+v", wanted, preset)
	}
	contents, err := os.ReadFile("config.json")
	if err != nil {
		t.Fatal(err)
	}
	var persisted struct {
		Mode string `json:"resource_config_type"`
	}
	if err = json.Unmarshal(contents, &persisted); err != nil {
		t.Fatal(err)
	}
	if persisted.Mode != wanted {
		t.Fatalf("persisted mode is %q, want %q", persisted.Mode, wanted)
	}
}
