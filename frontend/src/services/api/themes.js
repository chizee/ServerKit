// Themes platform API methods (plan 60).
// A theme is data (a validated token map), so these are plain JSON calls — no
// zip upload, no checksum dance.

// All selectable themes (bundled seeds + installed) + the panel default slug.
export async function getInstalledThemes() {
    return this.request('/themes/installed');
}

// UNAUTHENTICATED pre-auth default — the login/setup screens call this before
// anyone signs in to paint themselves with the panel default.
export async function getPublicActiveTheme() {
    return this.request('/themes/public/active');
}

// Import a theme from a parsed theme.json object (admin).
export async function importTheme(theme, { source } = {}) {
    const q = source === 'studio' ? '?source=studio' : '';
    return this.request(`/themes/import${q}`, {
        method: 'POST',
        body: JSON.stringify(theme),
    });
}

// Import a theme from an uploaded .json file (admin).
export async function importThemeFile(file) {
    const form = new FormData();
    form.append('file', file);
    return this.request('/themes/import', { method: 'POST', body: form });
}

// Uninstall an installed theme by slug (admin). Bundled seeds can't be removed.
export async function deleteTheme(slug) {
    return this.request(`/themes/${encodeURIComponent(slug)}`, { method: 'DELETE' });
}

// The panel-wide default theme slug.
export async function getDefaultTheme() {
    return this.request('/themes/default');
}

// Set the panel-wide default theme (admin).
export async function setDefaultTheme(slug) {
    return this.request('/themes/default', {
        method: 'POST',
        body: JSON.stringify({ slug }),
    });
}

// Browse the remote theme registry (with live install state). Offline-tolerant.
export async function getThemeRegistry() {
    return this.request('/themes/registry');
}

// Install a theme from the registry by slug (admin).
export async function installRegistryTheme(slug) {
    return this.request(`/themes/registry/${encodeURIComponent(slug)}/install`, {
        method: 'POST',
    });
}
