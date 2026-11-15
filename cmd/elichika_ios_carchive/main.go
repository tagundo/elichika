//go:build cgo && elichika_inprocess

package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"elichika/iosbridge"
	"unsafe"
)

//export ElichikaServerStart
func ElichikaServerStart(optionsJSON *C.char) *C.char {
	input := ""
	if optionsJSON != nil {
		input = C.GoString(optionsJSON)
	}
	return C.CString(iosbridge.StartJSON(input))
}

//export ElichikaServerStatus
func ElichikaServerStatus() *C.char { return C.CString(iosbridge.StatusJSON()) }

//export ElichikaServerStop
func ElichikaServerStop() *C.char { return C.CString(iosbridge.StopJSON()) }

//export ElichikaServerCommand
func ElichikaServerCommand(commandJSON *C.char) *C.char {
	input := ""
	if commandJSON != nil {
		input = C.GoString(commandJSON)
	}
	return C.CString(iosbridge.CommandJSON(input))
}

//export ElichikaServerFree
func ElichikaServerFree(result *C.char) { C.free(unsafe.Pointer(result)) }

func main() {}
