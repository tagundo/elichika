//go:build unix

package managementmode

import (
	"errors"
	"io"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

func acquire(root string) (io.Closer, error) {
	path := filepath.Join(root, ".database-maintenance.lock")
	descriptor, err := unix.Open(path, unix.O_CREAT|unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, errors.New("DATABASE_MAINTENANCE_LOCK_FAILED")
	}
	file := os.NewFile(uintptr(descriptor), path)
	refuse := func() (io.Closer, error) {
		_ = file.Close()
		return nil, errors.New("DATABASE_MAINTENANCE_LOCK_FAILED")
	}
	opened, err := file.Stat()
	if err != nil {
		return refuse()
	}
	named, err := os.Lstat(path)
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(opened, named) || opened.Mode().Perm()&0077 != 0 {
		return refuse()
	}
	var info unix.Stat_t
	if unix.Fstat(descriptor, &info) != nil || info.Nlink != 1 {
		return refuse()
	}
	if err = unix.Flock(descriptor, unix.LOCK_EX|unix.LOCK_NB); err != nil {
		_ = file.Close()
		if errors.Is(err, unix.EWOULDBLOCK) || errors.Is(err, unix.EAGAIN) {
			return nil, errors.New("DATABASE_MAINTENANCE_BUSY")
		}
		return nil, errors.New("DATABASE_MAINTENANCE_LOCK_FAILED")
	}
	return file, nil
}
