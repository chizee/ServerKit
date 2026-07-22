/**
 * HTML-sink guard (plan 55 Phase 1, Decision D4).
 *
 * Keeps the XSS-sink sweep swept: every raw-HTML sink must sit behind a known
 * sanitizer/escaper OR carry an explicit `sink-safe:` annotation naming why it's
 * safe. A new unannotated sink fails this check, so the sweep can't silently
 * regress (the plan-41 completeness-script pattern).
 *
 *   node scripts/check-html-sinks.mjs          # exit 1 on any uncleared sink
 *
 * Scans:
 *   - frontend/src   for  dangerouslySetInnerHTML | .innerHTML= | insertAdjacentHTML
 *                          | new Function( | eval(
 *   - backend/app    for  |safe | Markup( | render_template_string
 *
 * A sink LINE is cleared when it either references an allowlisted sanitizer
 * (frontend only) or a `sink-safe:` comment appears on it or within the 3 lines
 * above it. Allowlisted sanitizers live in frontend/src/utils + lib + the
 * escape-first highlighters; extend ALLOWLISTED_SANITIZERS only alongside a real
 * escaper/sanitizer.
 */
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const FRONTEND_SINK = /dangerouslySetInnerHTML|\.innerHTML\s*=[^=]|insertAdjacentHTML|new\s+Function\s*\(|\beval\s*\(/;
const BACKEND_SINK = /\|\s*safe\b|\bMarkup\s*\(|render_template_string/;
// Escapers/sanitizers that make a raw-HTML sink safe by construction.
const ALLOWLISTED_SANITIZERS = /sanitizeSvgInner|renderMarkdownToHtml|highlightLine|hlSql/;
const ANNOTATION = /sink-safe:/;

async function walk(dir, exts) {
    const out = [];
    let entries;
    try {
        entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
        return out;
    }
    for (const e of entries) {
        if (e.name === 'node_modules' || e.name === 'dist' || e.name === '__pycache__') continue;
        const full = path.join(dir, e.name);
        if (e.isDirectory()) {
            out.push(...await walk(full, exts));
        } else if (exts.some((x) => e.name.endsWith(x))) {
            out.push(full);
        }
    }
    return out;
}

function scanFile(rel, text, sinkRe, allowSanitizer) {
    const lines = text.split('\n');
    const violations = [];
    for (let i = 0; i < lines.length; i++) {
        if (!sinkRe.test(lines[i])) continue;
        // Skip comment-only lines: a doc comment that merely *mentions* a sink
        // keyword isn't a sink (e.g. "// dangerouslySetInnerHTML is safe here").
        const trimmed = lines[i].trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')
            || trimmed.startsWith('/*') || trimmed.startsWith('#')) continue;
        const window = lines.slice(Math.max(0, i - 3), i + 1).join('\n');
        const cleared = (allowSanitizer && ALLOWLISTED_SANITIZERS.test(lines[i]))
            || ANNOTATION.test(window);
        if (!cleared) {
            violations.push({ file: rel, line: i + 1, text: lines[i].trim() });
        }
    }
    return violations;
}

async function main() {
    const violations = [];
    let sinkCount = 0;

    const feFiles = await walk(path.join(ROOT, 'frontend', 'src'), ['.js', '.jsx', '.ts', '.tsx']);
    for (const f of feFiles) {
        const text = await fs.readFile(f, 'utf8');
        const rel = path.relative(ROOT, f);
        for (const line of text.split('\n')) if (FRONTEND_SINK.test(line)) sinkCount++;
        violations.push(...scanFile(rel, text, FRONTEND_SINK, true));
    }

    const beFiles = await walk(path.join(ROOT, 'backend', 'app'), ['.py', '.html']);
    for (const f of beFiles) {
        const text = await fs.readFile(f, 'utf8');
        const rel = path.relative(ROOT, f);
        for (const line of text.split('\n')) if (BACKEND_SINK.test(line)) sinkCount++;
        violations.push(...scanFile(rel, text, BACKEND_SINK, false));
    }

    if (violations.length) {
        console.error('\n✖ HTML-sink guard: unannotated raw-HTML sink(s) found.\n');
        for (const v of violations) {
            console.error(`  ${v.file}:${v.line}  ${v.text}`);
        }
        console.error('\nEach raw-HTML sink must reference a sanitizer/escaper or carry a');
        console.error('`sink-safe: <sanitizer> — <why>` comment (on the line or up to 3 above).');
        console.error('See scripts/check-html-sinks.mjs and SECURITY.md.\n');
        process.exit(1);
    }

    console.log(`✓ html-sinks: ${sinkCount} raw-HTML sink(s), all sanitized or annotated.`);
}

main().catch((e) => {
    console.error(e);
    process.exit(2);
});
