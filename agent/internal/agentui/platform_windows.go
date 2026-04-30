//go:build windows

package agentui

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

// runServiceCmd issues sc.exe verb against ServerKitAgent. The MSI grants
// BUILTIN\Users start/stop/configure rights so this works as the regular
// user with no UAC prompt.
func runServiceCmd(verb string) error {
	cmd := exec.Command("sc.exe", verb, "ServerKitAgent")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("sc %s: %w (output: %s)", verb, err, string(out))
	}
	return nil
}

// openTarget hands a path or URL to Explorer / the default browser via
// rundll32 + url.dll, which is the canonical "open this thing" entry point
// on Windows. Faster than shelling out to cmd /c start.
func openTarget(target string) error {
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", target)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Start()
}

// exeForSpawn returns the path to the currently running agent binary so the
// wizard re-launch can spawn another instance of the same exe.
func exeForSpawn() (string, error) {
	return os.Executable()
}
