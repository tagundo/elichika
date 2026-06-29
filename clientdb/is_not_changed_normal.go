//go:build !embedded

package clientdb

import (
	"elichika/config"
	"elichika/log"

	"os/exec"
)

func isNotChanged(file string) bool {
	cmd := exec.Command("git", "diff", "--exit-code", "--quiet", file)
	cmd.Dir = config.AssetPath
	err := cmd.Run()
	if err == nil {
		return true // exit code is 0
	}
	exitError, ok := err.(*exec.ExitError)
	if !ok {
		// git could not be run at all (e.g. the standalone Android app has no git
		// binary in PATH). Fall back to the packaged-build behaviour and treat the
		// file as unchanged, matching is_not_changed_embedded.go, instead of crashing.
		return true
	}
	if exitError.ExitCode() != 1 {
		log.Panic(err)
	}
	return false
}
