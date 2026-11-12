// Package managementmode identifies the app-owned, offline WebUI process.
package managementmode

import (
	"io"
	"os"
	"sync"
)

var lifetime io.Closer
var lock sync.Mutex

// Enabled never accepts a listener address or arbitrary command arguments.
func Enabled() bool { return len(os.Args) == 2 && os.Args[1] == "management" }

// Acquire runs before config/database initialization. The lease is compatible
// with Python's database_maintenance.guard and remains held until process exit.
func Acquire(root string) error {
	lock.Lock()
	defer lock.Unlock()
	if lifetime != nil {
		return nil
	}
	lease, err := acquire(root)
	if err == nil {
		lifetime = lease
	}
	return err
}

func Release() {
	lock.Lock()
	defer lock.Unlock()
	if lifetime != nil {
		_ = lifetime.Close()
		lifetime = nil
	}
}
