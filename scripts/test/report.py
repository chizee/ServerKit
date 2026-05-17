#!/usr/bin/env python3
"""Aggregate per-VM results into a single self-contained HTML report.

Inputs (from scripts/test/output/<run-id>/):
  <vm-name>/install.log         — captured cloud-init / install output
  <vm-name>/install-status      — "OK" or "FAIL"
  <vm-name>/pytest-report.json  — pytest-json-report output (may be missing if install failed)
  <vm-name>/journalctl.log      — backend logs (best-effort)

Output:
  report.html in the run directory.
"""
import json
import sys
import html
from pathlib import Path
from datetime import datetime


def esc(s):
    return html.escape(str(s) if s is not None else "")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_text(path, limit=200_000):
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data) > limit:
            data = "...[truncated]...\n" + data[-limit:]
        return data
    except Exception:
        return "(file missing)"


def vm_summary(vm_dir: Path):
    name = vm_dir.name
    status_file = vm_dir / "install-status"
    install_ok = status_file.exists() and status_file.read_text().strip() == "OK"
    pytest_json = load_json(vm_dir / "pytest-report.json")

    tests = []
    pass_count = fail_count = skip_count = 0
    if pytest_json and "tests" in pytest_json:
        for t in pytest_json["tests"]:
            outcome = t.get("outcome", "unknown")
            tests.append((t.get("nodeid", "?"), outcome, t.get("call", {}).get("longrepr", "")))
            if outcome == "passed":
                pass_count += 1
            elif outcome == "failed":
                fail_count += 1
            elif outcome == "skipped":
                skip_count += 1

    overall = "PASS" if (install_ok and fail_count == 0 and (pass_count > 0 or pytest_json is None)) else "FAIL"
    if not install_ok:
        overall = "FAIL"

    return {
        "name": name,
        "install_ok": install_ok,
        "overall": overall,
        "tests": tests,
        "pass": pass_count,
        "fail": fail_count,
        "skip": skip_count,
        "install_log": read_text(vm_dir / "install.log"),
        "journal": read_text(vm_dir / "journalctl.log", limit=50_000),
    }


HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>ServerKit E2E Report — {ts}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,sans-serif;margin:24px;background:#0f1115;color:#e6e6e6}}
 h1{{margin-top:0}}
 .vm{{background:#1a1d24;border-radius:8px;padding:16px;margin:16px 0;border-left:6px solid #555}}
 .vm.pass{{border-left-color:#3fb950}}
 .vm.fail{{border-left-color:#f85149}}
 .badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}}
 .badge.pass{{background:#1f6f33;color:#d2f5d8}}
 .badge.fail{{background:#7a2a26;color:#fdd}}
 .badge.skip{{background:#3a3a3a;color:#bbb}}
 details{{margin-top:8px;background:#0c0e13;border-radius:6px;padding:8px}}
 summary{{cursor:pointer;font-weight:600}}
 pre{{white-space:pre-wrap;word-break:break-word;font-size:12px;background:#000;padding:8px;border-radius:4px;max-height:400px;overflow:auto}}
 table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:13px}}
 td,th{{padding:4px 8px;border-bottom:1px solid #2a2d34;text-align:left}}
 .counts span{{margin-right:12px}}
</style></head><body>
<h1>ServerKit E2E Test Report</h1>
<p>Run: <code>{run_id}</code> · {ts}</p>
<p>Overall: <span class="badge {overall_cls}">{overall}</span>
 &nbsp; VMs: {n_vms} &nbsp; Passed: {n_pass} &nbsp; Failed: {n_fail}</p>
{vm_sections}
</body></html>"""

VM_TEMPLATE = """<div class="vm {cls}">
 <h2>{name} <span class="badge {cls}">{overall}</span></h2>
 <div class="counts">
   <span>Install: <b>{install}</b></span>
   <span>Passed: <b>{p}</b></span>
   <span>Failed: <b>{f}</b></span>
   <span>Skipped: <b>{s}</b></span>
 </div>
 {tests_table}
 <details><summary>Install log</summary><pre>{install_log}</pre></details>
 <details><summary>journalctl -u serverkit</summary><pre>{journal}</pre></details>
</div>"""


def render(run_dir: Path) -> Path:
    vm_dirs = sorted([p for p in run_dir.iterdir() if p.is_dir()])
    summaries = [vm_summary(d) for d in vm_dirs]

    n_pass = sum(1 for s in summaries if s["overall"] == "PASS")
    n_fail = sum(1 for s in summaries if s["overall"] != "PASS")
    overall = "PASS" if n_fail == 0 and n_pass > 0 else "FAIL"

    vm_sections = []
    for s in summaries:
        cls = "pass" if s["overall"] == "PASS" else "fail"
        if s["tests"]:
            rows = "".join(
                f"<tr><td>{esc(nid)}</td><td><span class='badge {oc}'>{esc(oc)}</span></td>"
                f"<td><pre style='max-height:120px'>{esc(repr_)}</pre></td></tr>"
                for nid, oc, repr_ in s["tests"]
            )
            tests_table = f"<table><tr><th>Test</th><th>Result</th><th>Details</th></tr>{rows}</table>"
        else:
            tests_table = "<p><i>No pytest results (install likely failed before harness ran).</i></p>"

        vm_sections.append(VM_TEMPLATE.format(
            cls=cls,
            name=esc(s["name"]),
            overall=esc(s["overall"]),
            install="OK" if s["install_ok"] else "FAIL",
            p=s["pass"], f=s["fail"], s=s["skip"],
            tests_table=tests_table,
            install_log=esc(s["install_log"]),
            journal=esc(s["journal"]),
        ))

    out = run_dir / "report.html"
    out.write_text(HTML_TEMPLATE.format(
        ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        run_id=esc(run_dir.name),
        overall=overall,
        overall_cls="pass" if overall == "PASS" else "fail",
        n_vms=len(summaries),
        n_pass=n_pass,
        n_fail=n_fail,
        vm_sections="\n".join(vm_sections),
    ), encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: report.py <run-output-dir>", file=sys.stderr)
        sys.exit(2)
    run_dir = Path(sys.argv[1]).resolve()
    if not run_dir.is_dir():
        print(f"not a directory: {run_dir}", file=sys.stderr)
        sys.exit(2)
    out = render(run_dir)
    print(str(out))
