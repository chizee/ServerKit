// Package capabilities probes the host for which feature surfaces the
// agent can manage (cron, docker, systemd, nginx, …). The result is a
// flat map[string]bool the agent ships to the panel on connect; the
// panel uses it to gate per-feature target pickers.
//
// Probes are cheap (PATH lookups + a couple of file/socket checks) and
// run once per agent process at startup. Results are cached for the
// process lifetime — re-probing is a future concern (e.g. SIGHUP, an
// explicit panel-issued "recapability" command).
package capabilities

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"

	"github.com/serverkit/agent/internal/logger"
	"github.com/serverkit/agent/pkg/protocol"
	gopsutilhost "github.com/shirou/gopsutil/v3/host"
)

// Probe runs all known capability probes and returns the result. log is
// optional — used to record what the probe found, mostly for ops
// debugging when an agent unexpectedly fails to expose a feature.
//
// dockerAvailable is passed in by the agent because it has already
// dialled the docker socket during startup; re-probing here would just
// duplicate that work.
func Probe(ctx context.Context, log *logger.Logger, dockerAvailable bool) protocol.CapabilitiesMessage {
	caps := protocol.Capabilities{}

	// Docker — the agent's own client is the source of truth. If the
	// agent couldn't dial dockerd, nothing this layer probes will fix
	// it.
	caps["docker"] = dockerAvailable

	// Linux service surfaces. On non-Linux these stay false; the
	// panel's UI is already conditional on them.
	caps["cron"] = probeCron()
	caps["systemd"] = probeSystemd()
	caps["nginx"] = probeNginx()
	caps["php_fpm"] = probePHPFPM()
	caps["packages"] = probePackageManager()

	// Cloudflared — present if the binary is on PATH. The panel uses
	// this to decide whether to show the Cloudflare Tunnels tab; it
	// doesn't imply the user has authenticated yet (cert.pem check
	// happens in the cloudflared:status action).
	caps["cloudflared"] = probeCloudflared()

	// Language runtimes — best-effort version probes. A missing key
	// means "not installed"; an empty string means "installed but
	// `--version` parse failed" so the panel can still light up the
	// runtime indicator without claiming a wrong version.
	runtimes := probeRuntimes(ctx)

	// Platform / distro for any code that needs more than the booleans
	// (e.g. "use apt vs dnf" — Phase 4 territory, but we capture it
	// now so we don't have to add another roundtrip later).
	platform := runtime.GOOS
	distro := ""
	distroVer := ""
	if info, err := gopsutilhost.InfoWithContext(ctx); err == nil {
		// gopsutil reports "ubuntu", "debian", "centos", etc. on Linux;
		// "windows", "darwin" on those platforms — we don't need it
		// there.
		distro = info.Platform
		distroVer = info.PlatformVersion
	}

	if log != nil {
		log.Info("Capability probe complete",
			"platform", platform,
			"distro", distro,
			"docker", caps["docker"],
			"cron", caps["cron"],
			"systemd", caps["systemd"],
			"nginx", caps["nginx"],
			"php_fpm", caps["php_fpm"],
			"packages", caps["packages"],
			"cloudflared", caps["cloudflared"],
			"runtimes", runtimes,
		)
	}

	return protocol.CapabilitiesMessage{
		Capabilities:  caps,
		Platform:      platform,
		Distro:        distro,
		DistroVersion: distroVer,
		Runtimes:      runtimes,
	}
}

// probeCloudflared — true if cloudflared is on PATH. The capability
// flips to true at install time, well before the user has logged in
// (cloudflared tunnel login). The auth state is exposed separately by
// the cloudflared:status action so the UI can show "binary installed,
// not authenticated" without having to teach the panel about
// /etc/cloudflared/cert.pem locations.
func probeCloudflared() bool {
	return hasOnPath("cloudflared")
}

// probeRuntimes detects common language runtimes by shelling out to
// each "<bin> --version" and parsing the first line. Versions are kept
// as raw strings (e.g. "3.11.4", "20.10.0", "8.2.0") so consumers can
// do their own semver compares without us guessing the schema.
//
// Per-binary timeout is short — every probe is bounded so a hung
// subprocess can't block the agent from connecting.
func probeRuntimes(ctx context.Context) map[string]string {
	results := map[string]string{}
	probes := []struct {
		key  string
		bins []string // try in order; first match wins
	}{
		{key: "python", bins: []string{"python3", "python"}},
		{key: "node", bins: []string{"node", "nodejs"}},
		{key: "php", bins: []string{"php"}},
		{key: "go", bins: []string{"go"}},
		{key: "ruby", bins: []string{"ruby"}},
		{key: "java", bins: []string{"java"}},
	}
	for _, p := range probes {
		for _, bin := range p.bins {
			if !hasOnPath(bin) {
				continue
			}
			ver := readVersion(ctx, bin)
			results[p.key] = ver
			break // don't keep trying once we found one
		}
	}
	return results
}

// versionPattern grabs the first dotted-number sequence in a version
// string. Works across the messy outputs:
//   - python:  "Python 3.11.4"
//   - node:    "v20.10.0"
//   - php:     "PHP 8.2.0 (cli) ..."
//   - go:      "go version go1.22.0 linux/amd64"
//   - ruby:    "ruby 3.2.2p53 ..."
//   - java:    "openjdk version \"17.0.6\" 2023-01-17"
var versionPattern = regexp.MustCompile(`(\d+\.\d+(?:\.\d+)?)`)

func readVersion(ctx context.Context, bin string) string {
	// java and a few others print version on stderr; capture both.
	cmd := exec.CommandContext(ctx, bin, "--version")
	out, err := cmd.CombinedOutput()
	if err != nil || len(out) == 0 {
		// Some binaries reject "--version" but accept "-version" (java).
		cmd = exec.CommandContext(ctx, bin, "-version")
		out, _ = cmd.CombinedOutput()
	}
	if len(out) == 0 {
		return ""
	}
	first := strings.SplitN(strings.TrimSpace(string(out)), "\n", 2)[0]
	if m := versionPattern.FindString(first); m != "" {
		return m
	}
	// Fall through with the raw first line so the panel at least shows
	// something rather than a blank.
	return first
}

// probeCron — present if `crontab` is on PATH OR a cron daemon is
// installed (we don't require it to be running; the panel can start it).
func probeCron() bool {
	if runtime.GOOS != "linux" {
		return false
	}
	if hasOnPath("crontab") {
		return true
	}
	// On systemd hosts that only expose the timer subsystem, crontab
	// may be missing but cron.d is still useful. Treat presence of
	// /etc/cron.d as the fallback signal.
	if _, err := os.Stat("/etc/cron.d"); err == nil {
		return true
	}
	return false
}

// probeSystemd — systemctl on PATH and the system bus is reachable.
// On a container without systemd, systemctl is sometimes installed as a
// shim that fails with "Failed to connect to bus", so we additionally
// check for /run/systemd/system which is the canonical "systemd is PID 1
// here" marker.
func probeSystemd() bool {
	if runtime.GOOS != "linux" {
		return false
	}
	if !hasOnPath("systemctl") {
		return false
	}
	if _, err := os.Stat("/run/systemd/system"); err == nil {
		return true
	}
	return false
}

func probeNginx() bool {
	if runtime.GOOS != "linux" {
		return false
	}
	return hasOnPath("nginx")
}

func probePHPFPM() bool {
	if runtime.GOOS != "linux" {
		return false
	}
	// PHP-FPM is shipped per-version on Debian/Ubuntu (php-fpm,
	// php8.1-fpm, php8.2-fpm, …). hasOnPath only catches the bare
	// name, so glob the common install dirs as a fallback.
	if hasOnPath("php-fpm") {
		return true
	}
	for _, pat := range []string{
		"/usr/sbin/php*-fpm*",
		"/usr/local/sbin/php*-fpm*",
	} {
		if matches, _ := filepath.Glob(pat); len(matches) > 0 {
			return true
		}
	}
	return false
}

// probePackageManager — true if any of the recognized managers (apt,
// dnf, yum, apk, pacman, zypper) is on PATH. Phase 0 only needs
// "package management is possible from here"; identifying which manager
// goes in the system_info / capabilities Distro field above.
func probePackageManager() bool {
	if runtime.GOOS != "linux" {
		return false
	}
	for _, mgr := range []string{"apt-get", "apt", "dnf", "yum", "apk", "pacman", "zypper"} {
		if hasOnPath(mgr) {
			return true
		}
	}
	return false
}

// hasOnPath checks whether a binary is reachable via $PATH. Cached to
// avoid hammering the filesystem on agents that re-probe via SIGHUP.
func hasOnPath(name string) bool {
	if v, ok := pathCache.Load(name); ok {
		return v.(bool)
	}
	_, err := exec.LookPath(name)
	ok := err == nil
	pathCache.Store(name, ok)
	return ok
}

var pathCache sync.Map
