"""HTML-sink sweep guard — proving test (plan 55 Phase 1, D4).

Mirrors scripts/check-html-sinks.mjs in Python so the sweep stays swept inside
the backend suite (the authoritative gate) even where node isn't available: every
raw-HTML sink in frontend/src or backend/app must reference an allowlisted
sanitizer/escaper or carry a `sink-safe:` annotation. A new unannotated sink
fails this test.
"""
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FRONTEND_SINK = re.compile(
    r'dangerouslySetInnerHTML|\.innerHTML\s*=[^=]|insertAdjacentHTML'
    r'|new\s+Function\s*\(|\beval\s*\(')
BACKEND_SINK = re.compile(r'\|\s*safe\b|\bMarkup\s*\(|render_template_string')
ALLOWLISTED_SANITIZERS = re.compile(r'sanitizeSvgInner|renderMarkdownToHtml|highlightLine|hlSql')
ANNOTATION = re.compile(r'sink-safe:')
_COMMENT_PREFIXES = ('//', '*', '/*', '#')


def _walk(root, exts):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ('node_modules', 'dist', '__pycache__')]
        for name in filenames:
            if name.endswith(exts):
                yield os.path.join(dirpath, name)


def _scan(path, sink_re, allow_sanitizer):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.read().split('\n')
    violations = []
    for i, line in enumerate(lines):
        if not sink_re.search(line):
            continue
        if line.strip().startswith(_COMMENT_PREFIXES):
            continue  # a comment that merely mentions a sink keyword
        window = '\n'.join(lines[max(0, i - 3):i + 1])
        cleared = (allow_sanitizer and ALLOWLISTED_SANITIZERS.search(line)) \
            or ANNOTATION.search(window)
        if not cleared:
            violations.append(f'{os.path.relpath(path, _REPO_ROOT)}:{i + 1}  {line.strip()}')
    return violations


def test_no_unannotated_html_sinks():
    violations = []
    fe = os.path.join(_REPO_ROOT, 'frontend', 'src')
    for path in _walk(fe, ('.js', '.jsx', '.ts', '.tsx')):
        violations += _scan(path, FRONTEND_SINK, allow_sanitizer=True)
    be = os.path.join(_REPO_ROOT, 'backend', 'app')
    for path in _walk(be, ('.py', '.html')):
        violations += _scan(path, BACKEND_SINK, allow_sanitizer=False)

    assert not violations, (
        'Unannotated raw-HTML sink(s) — each must reference a sanitizer/escaper '
        'or carry a `sink-safe:` comment (see scripts/check-html-sinks.mjs):\n'
        + '\n'.join(violations))
