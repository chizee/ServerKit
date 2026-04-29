//go:build !windows

package main

import (
	"fmt"
	"os"
)

func showFatalError(err error) {
	fmt.Fprintln(os.Stderr, err)
}
