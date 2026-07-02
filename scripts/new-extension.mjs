#!/usr/bin/env node
/**
 * Scaffold a new ServerKit extension (task #40).
 *
 *   node scripts/new-extension.mjs <slug> [--backend] [--builtin]
 *
 *   <slug>       kebab-case extension name, e.g. serverkit-uptime-badge
 *   --backend    also scaffold a backend/ blueprint + lifecycle skeleton
 *   --builtin    scaffold under builtin-extensions/<slug>/ (in-repo, pre-bundled)
 *                instead of a standalone ./<slug>/ folder for a third-party repo
 *
 * After scaffolding, install it into a dev panel with:
 *   - builtin:      one-click from the Marketplace (Built-in), or
 *                   POST /api/v1/plugins/builtin/<slug>/install
 *   - standalone:   POST /api/v1/plugins/install-local  { "path": "<abs path>" }
 *
 * See docs/EXTENSIONS.md for the full authoring guide.
 */
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const args = process.argv.slice(2);
const slug = args.find((a) => !a.startsWith('--'));
const withBackend = args.includes('--backend');
const asBuiltin = args.includes('--builtin');

if (!slug || !/^[a-zA-Z0-9_-]+$/.test(slug)) {
    console.error('Usage: node scripts/new-extension.mjs <slug> [--backend] [--builtin]');
    console.error('  <slug> must be alphanumeric/dashes/underscores.');
    process.exit(1);
}

const componentName = slug
    .split(/[-_]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join('') + 'Page';

const baseDir = asBuiltin
    ? path.join(ROOT, 'builtin-extensions', slug)
    : path.join(ROOT, slug);

const manifest = {
    name: slug,
    display_name: slug.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    version: '0.1.0',
    description: 'A ServerKit extension.',
    author: '',
    license: 'MIT',
    category: 'utility',
    permissions: [],
    min_panel_version: null,
    contributions: {
        nav: [{
            id: slug,
            label: slug.replace(/[-_]/g, ' '),
            route: `/${slug}`,
            category: 'system',
            icon: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
        }],
        routes: [{ path: slug, component: componentName }],
        page_titles: { [`/${slug}`]: slug },
        command_palette: [{ label: slug, path: `/${slug}`, category: 'Pages', keywords: slug }],
    },
};

if (withBackend) {
    manifest.entry_point = 'blueprint:ext_bp';
    manifest.url_prefix = `/api/v1/${slug}`;
    manifest.lifecycle = { install: 'lifecycle:on_install', uninstall: 'lifecycle:on_uninstall' };
}

const frontendIndex = `// ${manifest.display_name} — extension UI entry.
// Exports named components referenced by contributions.routes[].component.
export function ${componentName}() {
    return (
        <div className="sk-tabgroup__inner">
            <h1>${manifest.display_name}</h1>
            <p>Replace this with your extension UI.</p>
        </div>
    );
}
`;

const backendBlueprint = `"""${manifest.display_name} backend blueprint."""
from flask import Blueprint, jsonify
from app.plugins_sdk import jwt_required, current_user, logger

ext_bp = Blueprint('${slug.replace(/-/g, '_')}', __name__)
log = logger(__name__)


@ext_bp.route('/ping', methods=['GET'])
@jwt_required()
def ping():
    return jsonify({'ok': True, 'plugin': '${slug}'})
`;

const backendLifecycle = `"""Lifecycle hooks for ${manifest.display_name}."""
from app.plugins_sdk import logger

log = logger(__name__)


def on_install(plugin):
    log.info('Installing ${slug}')


def on_uninstall(plugin, purge=False):
    log.info('Uninstalling ${slug} (purge=%s)', purge)
`;

async function writeFile(rel, content) {
    const full = path.join(baseDir, rel);
    await fs.mkdir(path.dirname(full), { recursive: true });
    await fs.writeFile(full, content);
    console.log(`  created ${path.relative(ROOT, full)}`);
}

async function main() {
    try {
        await fs.access(baseDir);
        console.error(`Refusing to overwrite existing directory: ${baseDir}`);
        process.exit(1);
    } catch { /* doesn't exist — good */ }

    console.log(`Scaffolding ${asBuiltin ? 'builtin ' : ''}extension "${slug}"…`);
    await writeFile('plugin.json', JSON.stringify(manifest, null, 2) + '\n');
    await writeFile('frontend/index.jsx', frontendIndex);
    if (withBackend) {
        await writeFile('backend/blueprint.py', backendBlueprint);
        await writeFile('backend/lifecycle.py', backendLifecycle);
    }

    console.log('\nDone.');
    if (asBuiltin) {
        console.log('Pre-bundle the frontend:  node scripts/sync-builtin-frontends.mjs');
        console.log('Then install it from the Marketplace (Built-in).');
    } else {
        console.log(`Install into a dev panel:  POST /api/v1/plugins/install-local { "path": "${baseDir}" }`);
    }
    console.log('Guide: docs/EXTENSIONS.md');
}

main().catch((e) => { console.error(e); process.exit(1); });
