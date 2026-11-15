//go:build elichika_inprocess

package runtimeinit

import (
	"errors"
	"strings"
	"testing"
)

func TestExplicitInitializePreservesOrderAndNamesFailure(t *testing.T) {
	original := initializers
	defer func() { initializers = original }()
	initializers = nil
	var order []string
	Register("config", func() { order = append(order, "config") })
	Register("database", func() { order = append(order, "database"); panic("bad schema") })
	if len(order) != 0 {
		t.Fatal("registration performed eager I/O")
	}
	err := Initialize()
	if err == nil || !strings.Contains(err.Error(), "database: bad schema") || strings.Join(order, ",") != "config,database" {
		t.Fatalf("%v, %v", err, order)
	}
}

func TestCloseRunsInReverseAndContinuesAfterFailure(t *testing.T) {
	original := closers
	defer func() { closers = original }()
	closers = nil
	var order []int
	TrackCloser(func() error { order = append(order, 1); return errors.New("first") })
	TrackCloser(func() error { order = append(order, 2); panic("second") })
	err := Close()
	if err == nil || !strings.Contains(err.Error(), "first") || !strings.Contains(err.Error(), "second") || len(order) != 2 || order[0] != 2 || order[1] != 1 {
		t.Fatalf("%v, %v", err, order)
	}
	if len(closers) != 0 {
		t.Fatal("closed resources retained")
	}
}
