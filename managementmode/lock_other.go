//go:build !unix

package managementmode

import (
	"errors"
	"io"
)

func acquire(string) (io.Closer, error) {
	return nil, errors.New("MANAGEMENT_MODE_UNSUPPORTED_PLATFORM")
}
