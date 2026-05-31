# Changelog

All notable changes to ServerKit are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Scope:** This changelog tracks the **control panel** (Flask backend + React
> frontend). The cross-platform **agent** ships on its own cadence and is tagged
> separately (`agent-vX.Y.Z`) — see [`agent/README.md`](agent/README.md) for its
> install and release notes.
>
> Commit-level history lives in `git log`; this file curates the user-facing
> changes by theme.

## [Unreleased]

The `dev` branch is well ahead of the last `main` release. The headline work
awaiting a stable release:

### Added

- **Multi-platform agent & fleet management** — native Go agent for Linux,
  Windows, and macOS with HMAC-SHA256 auth and WebSocket + HTTP-poll transports,
  plus a fleet dashboard (inventory, connection status, approval queue,
  discovery, rollouts, and command queue).
- **Native Windows agent** — Windows service, desktop setup wizard (WebView2),
  system tray, and MSI installer; also `.deb`/`.rpm` packages and ARM64 builds.
- **Agent pairing** — short-code and passphrase pairing flows with keypair
  enrollment, the `sk1` connection-string format, and automatic fallback to
  polling when WebSocket connections flap.
- **Remote operations over the agent** — files, packages, services, cron, sudo,
  Docker, Cloudflare tunnels, and streamed job progress on connected servers.
- **Plugin / extension system** — plugin SDK, contribution points, capabilities
  and permissions, marketplace UI, built-in extensions, and a GUI plugin
  (`serverkit-gui`).
- **Status pages** — public status pages with HTTP/TCP/DNS/Ping checks,
  component monitoring, and incident management.
- **Cloud provisioning** — provision servers on DigitalOcean, Hetzner, Vultr,
  and Linode with cost tracking.
- **Git-based services** — GitHub source connections, repository picker,
  manifest detection, and "New Service from repo" (Git extension canonical at
  `/git`).
- **RHEL-family support** — the installer now covers Rocky, AlmaLinux, RHEL, and
  CentOS in addition to Ubuntu/Debian/Fedora.

### Changed

- Overhauled the Docker UI (bulk container stats, compose listing) and migrated
  the frontend design system to SCSS `.ui-*` components.
- Unified the local dev launcher (`dev.sh` / `dev.ps1`).
- Agent capabilities and system info are cached to the database, surfaced in the
  System Status card, and re-sent on a periodic cadence.

### Fixed

- Resolved systemic silent failures: empty logs, dead WebSocket connections, and
  locked-out agents; stale "online" status is now auto-corrected.
- Hardened the installer: Docker install on Fedora/RHEL, SELinux + nginx
  reverse-proxy configuration, and low-RAM swap setup.
- Stopped dropping capability/sysinfo payloads on transient `/poll` failures.

### Testing & Infra

- Added a Vagrant + Hyper-V runner (Debian/Fedora/Rocky) and a Multipass-based
  end-to-end harness that runs on Windows.

---

## Released

Current development version: **1.6.7**. Recent point releases (`1.4.x` → `1.6.7`)
delivered the agent fleet, plugin system, and installer hardening listed above.
Until tagged panel releases land, consult `git log` and the
[GitHub releases page](https://github.com/jhd3197/ServerKit/releases) for the
detailed history.
