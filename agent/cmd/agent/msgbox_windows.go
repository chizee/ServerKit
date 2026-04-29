//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

func showFatalError(err error) {
	user32 := syscall.NewLazyDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")
	title, _ := syscall.UTF16PtrFromString("ServerKit Agent")
	body, _ := syscall.UTF16PtrFromString("Setup failed:\n\n" + err.Error())
	const MB_ICONERROR = 0x00000010
	_, _, _ = messageBox.Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), MB_ICONERROR)
}
