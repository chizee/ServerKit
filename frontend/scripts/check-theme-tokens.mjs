#!/usr/bin/env node
// Proving guard for the themes platform (plan 60), wired into the frontend
// `lint` script (the frontend has no unit-test runner, so a lint-stage guard is
// the house-consistent check). Exercises the token whitelist + validators, the
// alias expansion, the dark/light skin resolution fallback, and asserts every
// bundled seed theme is valid. Dependency-free ESM.

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

const {
    validateTokenValue,
    sanitizeTokens,
    expandAliases,
    CANONICAL_TOKENS,
    ALIAS_MAP,
} = await import(new URL('../src/data/themeTokens.js', import.meta.url));
const { resolveSkinTokens } = await import(new URL('../src/utils/applySkin.js', import.meta.url));

let failures = 0;
function check(name, cond) {
    if (!cond) {
        console.error(`  ✖ ${name}`);
        failures += 1;
    }
}

// --- value validation: accepts good values ---
check('hex color accepted', validateTokenValue('--surface', '#101218') === '#101218');
check('rgba wash accepted', validateTokenValue('--green-bg', 'rgba(61,220,151,0.12)') !== null);
check('length accepted', validateTokenValue('--radius', '10px') === '10px');
check('font stack accepted', validateTokenValue('--mono', '"IBM Plex Mono", monospace') !== null);
check('shadow accepted', validateTokenValue('--shadow-md', '0 8px 24px -8px rgba(0,0,0,0.55)') !== null);
check('named color accepted', validateTokenValue('--text', 'white') === 'white');

// --- value validation: rejects malicious / malformed / out-of-whitelist ---
check('unknown token rejected', validateTokenValue('--evil', '#fff') === null);
check('url() rejected', validateTokenValue('--surface', 'url(https://x/y.png)') === null);
check('semicolon rejected', validateTokenValue('--surface', '#fff;color:red') === null);
check('brace rejected', validateTokenValue('--surface', '#fff}html{display:none') === null);
check('at-rule rejected', validateTokenValue('--surface', '@import x') === null);
check('expression() rejected', validateTokenValue('--surface', 'expression(alert(1))') === null);
check('non-color in color slot rejected', validateTokenValue('--surface', '10px') === null);
check('non-string rejected', validateTokenValue('--surface', 123) === null);

// --- sanitizeTokens drops unknown/invalid, keeps valid ---
const cleaned = sanitizeTokens({
    '--surface': '#101218',
    '--evil': 'url(x)',
    '--radius': 'not-a-length',
    '--text': '#e9ebf0',
});
check('sanitize keeps valid', cleaned['--surface'] === '#101218' && cleaned['--text'] === '#e9ebf0');
check('sanitize drops unknown', !('--evil' in cleaned));
check('sanitize drops invalid value', !('--radius' in cleaned));

// --- alias expansion fans canonical names out to legacy names ---
const expanded = expandAliases({ '--surface': '#111', '--text': '#eee', '--border': '#222' });
check('alias --surface -> --bg-card', expanded['--bg-card'] === '#111');
check('alias --text -> --text-primary', expanded['--text-primary'] === '#eee');
check('alias --border -> --border-default', expanded['--border-default'] === '#222');
check('canonical retained after expand', expanded['--surface'] === '#111');

// --- every alias target is NOT itself a canonical token (no self-collision) ---
const canonicalSet = new Set(CANONICAL_TOKENS);
for (const [token, aliases] of Object.entries(ALIAS_MAP)) {
    check(`alias source ${token} is canonical`, canonicalSet.has(token));
    for (const a of aliases) check(`alias target ${a} not canonical`, !canonicalSet.has(a));
}

// --- skin resolution + light fallback ---
const darkOnly = { tokens: { dark: { '--surface': '#111' } } };
check('dark resolves dark tokens', resolveSkinTokens(darkOnly, 'dark')?.['--surface'] === '#111');
check('light falls back to stock when no light tokens', resolveSkinTokens(darkOnly, 'light') === null);
const bothModes = { tokens: { dark: { '--surface': '#111' }, light: { '--surface': '#fff' } } };
check('light resolves light tokens', resolveSkinTokens(bothModes, 'light')?.['--surface'] === '#fff');
check('null theme resolves null', resolveSkinTokens(null, 'dark') === null);

// --- every bundled seed theme validates end-to-end ---
const themesDir = resolve(root, 'src/data/themes');
for (const file of readdirSync(themesDir).filter((f) => f.endsWith('.json'))) {
    const theme = JSON.parse(readFileSync(resolve(themesDir, file), 'utf8'));
    check(`${file}: has slug`, typeof theme.slug === 'string' && theme.slug.length > 0);
    check(`${file}: preview has 4 swatches`, Array.isArray(theme.preview) && theme.preview.length === 4);
    for (const mode of Object.keys(theme.tokens || {})) {
        const raw = theme.tokens[mode];
        const clean = sanitizeTokens(raw);
        const dropped = Object.keys(raw).filter((k) => !(k in clean));
        check(`${file}[${mode}]: all tokens valid (dropped: ${dropped.join(',') || 'none'})`, dropped.length === 0);
    }
}

if (failures) {
    console.error(`\n✖ theme-tokens check failed: ${failures} assertion(s)\n`);
    process.exit(1);
}
console.log('✓ theme-tokens: validators, alias expansion, skin resolution, and all bundled themes pass.');
