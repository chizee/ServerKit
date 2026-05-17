# ServerKit E2E Test Harness

One-click full-stack test that spins up fresh Linux VMs on your Windows box,
installs ServerKit from your **local working tree** (uncommitted changes
included), and runs an API harness against the live panel. Aggregates
everything into a single HTML report.

Designed for the "I'm about to merge a huge PR and want to be sure the
installer actually works on multiple distros" use case.

## Prerequisites (one-time)

1. **Multipass** — https://multipass.run/download/windows
   ```powershell
   winget install Canonical.Multipass
   ```
2. **Python 3** on PATH (for the HTML report generator; tests run inside the VMs).
3. **WSL2 / Hyper-V** enabled (Multipass uses this — installer prompts you).

## Usage

From the repo root, in PowerShell:

```powershell
.\scripts\test\full-stack-test.ps1
```

That's it. Goes and makes coffee. ~1-2 hours on first run (cloud images
download), 15-30 min after that. When it finishes, your browser opens to the
HTML report.

### Options

```powershell
# Only test Ubuntu 24.04
.\scripts\test\full-stack-test.ps1 -Only ubuntu24

# Keep VMs running so you can shell in and poke around
.\scripts\test\full-stack-test.ps1 -Keep

# Bigger VMs (default 2 CPU / 4 GB RAM / 15 GB disk)
.\scripts\test\full-stack-test.ps1 -Cpus 4 -MemoryGB 8
```

### Agent pairing test (optional)

After running with `-Keep`:

```powershell
.\scripts\test\agent-test.ps1
```

Exercises the agent <-> panel pairing API end-to-end (enroll → claim).

## What it does

1. Tar your local repo (excluding `.git`, `node_modules`, venvs, `dist/`).
2. `multipass launch` three VMs in parallel: Ubuntu 22.04, Ubuntu 24.04, Debian 12.
3. On each VM, in parallel:
   - Upload the tarball + `vm-install.sh`.
   - Run `install.sh` (real public installer — clones from GitHub, installs
     Python, Node, Docker, nginx, builds frontend, starts systemd unit).
   - Overlay your local working tree on top of `/opt/serverkit`, rebuild
     frontend, restart `serverkit` systemd unit. This is what makes us test
     **your code**, not what's on `main`.
   - Wait for `/api/v1/system/health` to return 200.
   - Push the pytest harness and run it against the live panel.
   - Capture install log + journalctl regardless of outcome.
4. Generate one self-contained `report.html` with green/red per VM, per test,
   plus full logs inline.
5. Tear down VMs (unless `-Keep`).

## Output

```
scripts/test/output/<run-id>/
  report.html                     <- open this
  serverkit-src.tar.gz
  sk-test-ubuntu22-<id>/
    install.log
    vm-install.log
    journalctl.log
    install-status                ("OK" or "FAIL")
    pytest.log
    pytest-report.json
  sk-test-ubuntu24-<id>/ ...
  sk-test-debian12-<id>/ ...
```

## Extending the harness

Add new tests under `harness/test_*.py` — they're plain pytest using a
session-scoped `admin_token` fixture and a `base_url` fixture. The orchestrator
auto-copies every file in `harness/` to each VM, so just dropping in a new
`test_05_whatever.py` is enough.

Currently covered:
- `test_01_health.py` — backend health, frontend reachable
- `test_02_auth.py` — setup-status, register, login, JWT-authed request
- `test_03_plugins.py` — list plugins (install-from-URL test is `@skipif`'d
  until a stable test plugin repo exists; flip when ready)
- `test_04_smoke.py` — sample of authed endpoints must not return 5xx

## Limitations

- Doesn't test bare-metal-only stuff (hardware drivers, real partitioning).
- Agent ARM64 MSI installer isn't exercised (no ARM hardware).
- UI smoke (Playwright) is not wired up yet — easy to add as a follow-up if
  the API surface stops catching everything.
- Fedora/Rocky not in the default distro list because Multipass focuses on
  Ubuntu; add via Vagrant + libvirt if you need those.

## Troubleshooting

**"multipass: command not found"** — install Multipass and restart PowerShell.

**Launch fails with timeout** — first launch downloads ~600 MB per distro
image; let it run. If it times out repeatedly, increase Multipass timeout:
`multipass set local.driver=hyperv`.

**Health check never passes** — open `report.html`, expand "Install log" and
"journalctl" for that VM. Most common: missing system package on a distro the
installer doesn't handle, or `frontend build` OOM (bump `-MemoryGB`).

**Want to debug a failing VM** — re-run with `-Keep`, then:
```powershell
multipass shell sk-test-ubuntu24-<id>
sudo journalctl -u serverkit -f
```
