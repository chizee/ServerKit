// Runtime skin applier (plan 60).
//
// A "skin" is a theme's validated token map applied on top of the stock
// stylesheet at runtime. We set each canonical token (plus its legacy aliases)
// as an inline custom property on <html> via setProperty — inline properties
// win over the stylesheet's :root / [data-theme] rules, and setProperty is
// inherently injection-safe (the browser drops anything malformed). Accent
// tokens are never touched here; ThemeContext.applyAccentToDOM owns those so a
// workspace/user accent keeps precedence over the skin.

import { sanitizeTokens, expandAliases, ALL_SKIN_PROPERTIES } from '../data/themeTokens.js';

/**
 * Pick the token map to apply for the current resolved mode, with the
 * light-mode fallback: a `base:"dark"` theme that ships no `light` tokens
 * degrades to the stock light theme when the user toggles to light (we return
 * null, which clears the skin so the stylesheet's [data-theme="light"] shows).
 *
 * @param {object|null} theme        a theme object with `tokens: { dark, light }`
 * @param {'dark'|'light'} resolvedTheme
 * @returns {object|null} raw token map for that mode, or null to clear
 */
export function resolveSkinTokens(theme, resolvedTheme) {
    if (!theme || !theme.tokens) return null;
    const mode = resolvedTheme === 'light' ? 'light' : 'dark';
    const map = theme.tokens[mode];
    if (map && typeof map === 'object' && Object.keys(map).length) return map;
    return null; // no tokens for this mode → fall back to stock
}

/**
 * Clear every property a skin could have set (canonical + aliases). Never
 * touches accent properties, which are managed separately.
 */
export function clearSkin(root = document.documentElement) {
    const style = root.style;
    for (const name of ALL_SKIN_PROPERTIES) style.removeProperty(name);
}

/**
 * Apply a raw token map to the document root: sanitise → expand aliases →
 * setProperty. Always clears the previous skin first so switching themes (or
 * toggling dark/light) never leaves stale overrides behind.
 *
 * @param {object|null} rawTokens  token map (unsanitised is fine), or null to clear
 * @param {HTMLElement} root       defaults to <html>
 */
export function applySkinTokens(rawTokens, root = document.documentElement) {
    clearSkin(root);
    if (!rawTokens) return;
    const clean = expandAliases(sanitizeTokens(rawTokens));
    const style = root.style;
    for (const [token, value] of Object.entries(clean)) {
        style.setProperty(token, value);
    }
}

/**
 * Convenience: resolve the right mode's tokens for a theme and apply them.
 * Returns the theme's declared `accent` (if any) so the caller can fold it into
 * accent precedence.
 */
export function applySkin(theme, resolvedTheme, root = document.documentElement) {
    const tokens = resolveSkinTokens(theme, resolvedTheme);
    applySkinTokens(tokens, root);
    return theme && typeof theme.accent === 'string' ? theme.accent : null;
}
