//go:build !elichika_inprocess

// Package runtimeinit keeps filesystem initialization explicit in embedded hosts.
// Standalone builds retain their existing package initialization order.
package runtimeinit

const InProcess = false

var RebuildAssets bool

func Register(_ string, initialize func()) { initialize() }

func Initialize() error { return nil }

func TrackCloser(_ func() error) {}

func Close() error { return nil }
