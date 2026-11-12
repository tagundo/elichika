//go:build unix

package managementmode

import (
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/sys/unix"
)

func TestLifetimeLeaseUsesSharedNonblockingMaintenanceProtocol(t *testing.T) {
	root := t.TempDir()
	lease, err := acquire(root)
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Close()
	path := filepath.Join(root, ".database-maintenance.lock")
	other, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if err := unix.Flock(int(other.Fd()), unix.LOCK_EX|unix.LOCK_NB); err == nil {
		t.Fatal("another database writer acquired an active management lease")
	}
	if _, err := acquire(root); err == nil || err.Error() != "DATABASE_MAINTENANCE_BUSY" {
		t.Fatalf("second management process must refuse promptly: %v", err)
	}
	if err := lease.Close(); err != nil {
		t.Fatal(err)
	}
	if err := unix.Flock(int(other.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		t.Fatalf("lease was not released after management exit: %v", err)
	}
}

func TestUnsafeMaintenanceFilesAreRefused(t *testing.T) {
	for _, kind := range []string{"symlink", "hardlink", "public", "directory"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, ".database-maintenance.lock")
			target := filepath.Join(root, "owner-data")
			if err := os.WriteFile(target, []byte("retain"), 0600); err != nil {
				t.Fatal(err)
			}
			var err error
			switch kind {
			case "symlink":
				err = os.Symlink(target, path)
			case "hardlink":
				err = os.Link(target, path)
			case "public":
				err = os.WriteFile(path, nil, 0644)
				if err == nil {
					err = os.Chmod(path, 0644)
				}
			case "directory":
				err = os.Mkdir(path, 0700)
			}
			if err != nil {
				t.Fatal(err)
			}
			if lease, err := acquire(root); err == nil {
				lease.Close()
				t.Fatal("unsafe maintenance file was accepted")
			}
			if raw, _ := os.ReadFile(target); string(raw) != "retain" {
				t.Fatal("refused lock path changed unrelated owner data")
			}
		})
	}
}

func TestManagementModeAcceptsOnlyFixedArgv(t *testing.T) {
	before := os.Args
	defer func() { os.Args = before }()
	for _, arguments := range [][]string{{"elichika"}, {"elichika", "management"}, {"elichika", "management", "0.0.0.0:8080"}, {"elichika", "reset_accounts"}} {
		os.Args = arguments
		want := len(arguments) == 2 && arguments[1] == "management"
		if Enabled() != want {
			t.Fatalf("unexpected management admission for %q", arguments)
		}
	}
}
