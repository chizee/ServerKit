// Bundled seed themes shipped with the panel (plan 60).
//
// These are the always-present gallery entries — the "default" stock look plus
// a handful of first-party skins — so the Theme Gallery has content on day one
// without any network fetch. Registry-installed themes are merged on top of
// these at runtime (see ThemeContext). The JSON files are the reference
// implementations linked from docs/THEMING.md and seed the serverkit-themes
// registry repo.
//
// The backend keeps its own copy (backend/app/data/themes/) for the pre-auth
// GET /public/active default and the offline registry fallback; the two are
// kept in sync (frontend/scripts/sync-bundled-themes.mjs).

const modules = import.meta.glob('./themes/*.json', { eager: true });

// The stock look is always first; the rest sort alphabetically by name.
export const BUNDLED_THEMES = Object.values(modules)
    .map((m) => m.default ?? m)
    .sort((a, b) => {
        if (a.slug === 'default') return -1;
        if (b.slug === 'default') return 1;
        return (a.name || a.slug).localeCompare(b.name || b.slug);
    });

export const BUNDLED_THEME_MAP = Object.fromEntries(
    BUNDLED_THEMES.map((t) => [t.slug, t]),
);

// The slug that means "no skin" — clears any applied skin and shows the stock
// stylesheet tokens. Always present, never uninstallable.
export const DEFAULT_THEME_SLUG = 'default';
