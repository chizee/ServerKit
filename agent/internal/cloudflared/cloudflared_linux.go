//go:build linux

package cloudflared

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// New returns a Linux Manager that drives `cloudflared`.
func New() Manager { return &linuxManager{} }

type linuxManager struct{}

// validNameRegex constrains tunnel names to characters that won't
// trip cloudflared or shell escaping. Matches the cloudflared docs:
// up to 32 chars, alphanumeric + dash + underscore.
var validNameRegex = regexp.MustCompile(`^[A-Za-z0-9_\-]{1,32}$`)

// validHostnameRegex is a permissive FQDN check — no protocol, no
// path, no spaces. Cloudflare itself does the authoritative check.
var validHostnameRegex = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+$`)

// certSearchPaths covers the two install patterns: the user ran
// `cloudflared tunnel login` as a regular user (~/.cloudflared) or as
// root / via the official install (/etc/cloudflared).
func certSearchPaths() []string {
	paths := []string{"/etc/cloudflared/cert.pem"}
	if home, err := os.UserHomeDir(); err == nil {
		paths = append(paths, filepath.Join(home, ".cloudflared", "cert.pem"))
	}
	return paths
}

func findCert() (string, bool) {
	for _, p := range certSearchPaths() {
		if _, err := os.Stat(p); err == nil {
			return p, true
		}
	}
	return "", false
}

func (l *linuxManager) Status(ctx context.Context) (*Status, error) {
	binPath, ok := hasCloudflared()
	if !ok {
		return &Status{
			Available: false,
			Reason:    "cloudflared not installed on host",
			LoginHint: "Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/",
		}, nil
	}

	cert, authed := findCert()

	// Best-effort version probe — failure is non-fatal, we still
	// report Available=true based on PATH.
	verCmd := exec.CommandContext(ctx, binPath, "--version")
	verOut, _ := verCmd.Output()
	version := strings.TrimSpace(strings.SplitN(string(verOut), "\n", 2)[0])

	st := &Status{
		Available:     true,
		Authenticated: authed,
		CertPath:      cert,
		Version:       version,
	}
	if !authed {
		st.LoginHint = "Run on the server: sudo cloudflared tunnel login"
	}
	return st, nil
}

// runTunnel runs `cloudflared tunnel <args>` and returns
// (stdout, error). Errors include the full stderr because the user
// will likely see them in the panel UI when something goes wrong.
func (l *linuxManager) runTunnel(ctx context.Context, args ...string) ([]byte, error) {
	args = append([]string{"tunnel"}, args...)
	cmd := exec.CommandContext(ctx, "cloudflared", args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("cloudflared %s: %w (%s)",
			strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return stdout.Bytes(), nil
}

func (l *linuxManager) List(ctx context.Context) ([]Tunnel, error) {
	out, err := l.runTunnel(ctx, "list", "--output", "json")
	if err != nil {
		return nil, err
	}

	// cloudflared prints `[]` (sometimes with trailing whitespace) when
	// no tunnels exist; json.Unmarshal handles both. Tunnel rows have
	// more fields than we surface — we cherry-pick id, name,
	// created_at, connections.
	var raw []struct {
		ID          string                   `json:"id"`
		Name        string                   `json:"name"`
		CreatedAt   string                   `json:"created_at"`
		Connections []map[string]interface{} `json:"connections"`
	}
	if err := json.Unmarshal(bytes.TrimSpace(out), &raw); err != nil {
		return nil, fmt.Errorf("parse tunnel list: %w", err)
	}

	out2 := make([]Tunnel, 0, len(raw))
	for _, r := range raw {
		conns := make([]string, 0, len(r.Connections))
		for _, c := range r.Connections {
			if origin, ok := c["origin_ip"].(string); ok && origin != "" {
				conns = append(conns, origin)
			}
		}
		out2 = append(out2, Tunnel{
			ID: r.ID, Name: r.Name, CreatedAt: r.CreatedAt, Connections: conns,
		})
	}
	return out2, nil
}

func (l *linuxManager) Create(ctx context.Context, req CreateRequest) (*Tunnel, error) {
	if !validNameRegex.MatchString(req.Name) {
		return nil, fmt.Errorf("invalid tunnel name (alphanumeric, -, _, max 32 chars)")
	}
	// `cloudflared tunnel create <name>` prints something like:
	//   Created tunnel <name> with id <UUID>
	// Newer versions also have --output json on create; we parse the
	// stdout text to be portable across versions.
	out, err := l.runTunnel(ctx, "create", req.Name)
	if err != nil {
		return nil, err
	}
	// Look up by name afterwards so we have the full Tunnel record
	// (the create stdout is informational, not structured JSON across
	// all cloudflared versions).
	_ = out
	tunnels, err := l.List(ctx)
	if err != nil {
		return nil, err
	}
	for _, t := range tunnels {
		if t.Name == req.Name {
			return &t, nil
		}
	}
	return nil, fmt.Errorf("tunnel created but not found in list")
}

func (l *linuxManager) Route(ctx context.Context, req RouteRequest) error {
	if req.TunnelRef == "" {
		return fmt.Errorf("tunnel_ref is required")
	}
	if !validHostnameRegex.MatchString(req.Hostname) {
		return fmt.Errorf("invalid hostname")
	}
	// `cloudflared tunnel route dns <tunnel> <hostname>` creates the
	// CNAME in Cloudflare DNS.
	_, err := l.runTunnel(ctx, "route", "dns", req.TunnelRef, req.Hostname)
	return err
}

func (l *linuxManager) Delete(ctx context.Context, ref string) error {
	if ref == "" {
		return fmt.Errorf("ref is required")
	}
	// -f forces deletion when the tunnel still has active connections;
	// safer default for a panel-driven flow.
	_, err := l.runTunnel(ctx, "delete", "-f", ref)
	return err
}
