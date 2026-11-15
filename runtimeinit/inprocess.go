//go:build elichika_inprocess

package runtimeinit

import (
	"errors"
	"fmt"
)

const InProcess = true

var RebuildAssets bool

type initializer struct {
	name string
	run  func()
}

// Registration happens during Go package initialization, in dependency order.
// The host serializes Initialize/Close after assigning the writable data root.
var initializers []initializer
var closers []func() error

// Progress is assigned by the serialized host before initializing services.
var Progress func(string)

func Register(name string, initialize func()) {
	initializers = append(initializers, initializer{name, initialize})
}

func Initialize() (err error) {
	name := "initialization"
	defer func() {
		if failure := recover(); failure != nil {
			err = fmt.Errorf("%s: %v", name, failure)
		}
	}()
	for _, item := range initializers {
		name = item.name
		if Progress != nil {
			Progress(name)
		}
		item.run()
	}
	return nil
}

func TrackCloser(close func() error) { closers = append(closers, close) }

func Close() error {
	var failures []error
	for i := len(closers) - 1; i >= 0; i-- {
		if err := safelyClose(closers[i]); err != nil {
			failures = append(failures, err)
		}
	}
	closers = nil
	return errors.Join(failures...)
}

func safelyClose(close func() error) (err error) {
	defer func() {
		if failure := recover(); failure != nil {
			err = fmt.Errorf("close: %v", failure)
		}
	}()
	return close()
}
