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
		// binary in PATH). The git check is elichika's "have these SQL migrations
		// already been applied?" flag: a pristine (committed) DB returns true so the
		// migration runs once, after which the modified file returns false and is
		// skipped. The Android APK ships DBs that CI already migrated via
		// rebuild_assets, so without git we must treat them as already-applied and
		// SKIP (return false) — re-running the migrations hits UNIQUE constraint
		// errors (e.g. m_live.live_id). Returning false here, not panicking.
		return false
	}
	if exitError.ExitCode() != 1 {
		log.Panic(err)
	}
	return false
}
