#!/usr/bin/env node
// Sync the bundled seed themes from the frontend (the authoring source of
// truth) into the backend, so the pre-auth GET /themes/public/active default
// and the offline registry fallback have the same theme data without a second
// hand-maintained copy (plan 60). Mirrors the repo's other sync-* scripts.
//
// Run from anywhere:  node frontend/scripts/sync-bundled-themes.mjs
//
// Writes:
//   backend/app/data/themes/<slug>.json   (verbatim copies)
//   backend/app/data/themes_index.json    (generated {schema_version, themes:[…]})

import { readFileSync, writeFileSync, readdirSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..');
const srcDir = resolve(repoRoot, 'frontend', 'src', 'data', 'themes');
const outDir = resolve(repoRoot, 'backend', 'app', 'data', 'themes');
const indexPath = resolve(repoRoot, 'backend', 'app', 'data', 'themes_index.json');

// Fresh copy of the themes dir so a removed seed theme doesn't linger.
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const files = readdirSync(srcDir).filter((f) => f.endsWith('.json')).sort();
const summaries = [];

for (const file of files) {
    const raw = readFileSync(join(srcDir, file), 'utf8');
    const theme = JSON.parse(raw);
    writeFileSync(join(outDir, file), raw.endsWith('\n') ? raw : `${raw}\n`);
    // The index carries only the light gallery metadata (not the full token
    // maps) — install fetches the full theme.json when needed.
    summaries.push({
        slug: theme.slug,
        name: theme.name,
        author: theme.author || 'serverkit',
        version: theme.version || '1.0.0',
        description: theme.description || '',
        base: theme.base || 'dark',
        preview: theme.preview || [],
        bundled: true,
    });
}

// Stable order: default first, then alphabetical by name.
summaries.sort((a, b) => {
    if (a.slug === 'default') return -1;
    if (b.slug === 'default') return 1;
    return (a.name || a.slug).localeCompare(b.name || b.slug);
});

const index = { schema_version: 1, themes: summaries };
writeFileSync(indexPath, `${JSON.stringify(index, null, 2)}\n`);

console.log(`✓ synced ${files.length} bundled theme(s) → backend/app/data/themes/`);
console.log(`✓ wrote themes_index.json (${summaries.length} entries)`);
