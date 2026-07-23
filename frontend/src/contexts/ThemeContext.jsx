import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { BUNDLED_THEMES, BUNDLED_THEME_MAP, DEFAULT_THEME_SLUG } from '../data/bundledThemes';
import { applySkin } from '../utils/applySkin';

const ThemeContext = createContext(null);

const DEFAULT_ACCENT = '#6d7cff';

const DEFAULT_WHITE_LABEL = {
    enabled: false,
    mode: 'image_text',    // 'image_text' | 'image_full' | 'text_only'
    brandName: '',
    logoData: '',          // base64 data URL
};

// Get the resolved theme based on current setting and OS preference
function getResolvedTheme(theme) {
    if (theme === 'system') {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return theme;
}

// Convert hex to { r, g, b }
function hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!result) return { r: 109, g: 124, b: 255 };
    return {
        r: parseInt(result[1], 16),
        g: parseInt(result[2], 16),
        b: parseInt(result[3], 16),
    };
}

const toHex = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
const rgbToHex = (r, g, b) => `#${toHex(r)}${toHex(g)}${toHex(b)}`;

// Derive the full accent ramp from a single hex. The redesign needs brighter
// (toward white) and dimmer (toward black) stops plus translucent washes so
// the new design-system primitives track a custom/workspace accent.
function deriveAccentVariants(hex) {
    const { r, g, b } = hexToRgb(hex);
    const darken = (v) => v * 0.88;        // hover
    const dim = (v) => v * 0.70;           // --accent-dim
    const bright = (v) => v + (255 - v) * 0.30; // --accent-bright, toward white
    return {
        primary: hex,
        hover: rgbToHex(darken(r), darken(g), darken(b)),
        bright: rgbToHex(bright(r), bright(g), bright(b)),
        dim: rgbToHex(dim(r), dim(g), dim(b)),
        bg: `rgba(${r}, ${g}, ${b}, 0.13)`,
        bgSoft: `rgba(${r}, ${g}, ${b}, 0.07)`,
        glow: `rgba(${r}, ${g}, ${b}, 0.35)`,
        shadow: `rgba(${r}, ${g}, ${b}, 0.3)`,
    };
}

// Apply accent CSS custom properties to the document
function applyAccentToDOM(hex) {
    const v = deriveAccentVariants(hex);
    const style = document.documentElement.style;
    style.setProperty('--accent-primary', v.primary);
    style.setProperty('--accent', v.primary);
    style.setProperty('--accent-hover', v.hover);
    style.setProperty('--accent-bright', v.bright);
    style.setProperty('--accent-dim', v.dim);
    style.setProperty('--accent-bg', v.bg);
    style.setProperty('--accent-bg-soft', v.bgSoft);
    style.setProperty('--accent-glow', v.glow);
    style.setProperty('--accent-shadow', v.shadow);
}

// Accent precedence (highest wins): an active workspace's brand color, then the
// user's explicit custom accent, then the active skin's declared accent, then
// the stock default. This keeps workspace/white-label independent of skins and
// lets a theme ship a cohesive accent without stomping a user's choice.
function computeEffectiveAccent({ workspaceAccent, hasCustomAccent, accentColor, skinAccent }) {
    if (workspaceAccent) return workspaceAccent;
    if (hasCustomAccent && accentColor) return accentColor;
    if (skinAccent) return skinAccent;
    return DEFAULT_ACCENT;
}

export function ThemeProvider({ children }) {
    const [theme, setThemeState] = useState(() => {
        return localStorage.getItem('theme') || 'dark';
    });

    const [resolvedTheme, setResolvedTheme] = useState(() => {
        const stored = localStorage.getItem('theme') || 'dark';
        return getResolvedTheme(stored);
    });

    const [accentColor, setAccentColorState] = useState(() => {
        return localStorage.getItem('accent_color') || DEFAULT_ACCENT;
    });

    // Whether the user has explicitly chosen an accent (vs. inheriting the
    // skin/default). Drives accent precedence.
    const [hasCustomAccent, setHasCustomAccent] = useState(() => {
        return localStorage.getItem('accent_color') != null;
    });

    // Selected skin slug (per-user, like dark/light). 'default' = stock look.
    const [skin, setSkinState] = useState(() => {
        return localStorage.getItem('skin') || DEFAULT_THEME_SLUG;
    });

    // Registry/imported themes merged on top of the bundled seeds at runtime
    // (populated in Phase 2 by fetching installed themes from the API).
    const [installedThemes, setInstalledThemes] = useState({});

    const [whiteLabel, setWhiteLabelState] = useState(() => {
        try {
            const stored = localStorage.getItem('white_label');
            return stored ? { ...DEFAULT_WHITE_LABEL, ...JSON.parse(stored) } : DEFAULT_WHITE_LABEL;
        } catch {
            return DEFAULT_WHITE_LABEL;
        }
    });

    // Active-workspace branding (#33): when a workspace is selected, its accent
    // color (written to localStorage by the WorkspaceSwitcher) takes precedence
    // over the user's personal accent. It only changes on reload — the switcher
    // reloads on switch — so a one-time read is deterministic and sufficient.
    const workspaceAccent = localStorage.getItem('workspace_accent') || null;

    // All selectable themes (bundled seeds + installed), keyed by slug.
    const themesMap = useMemo(
        () => ({ ...BUNDLED_THEME_MAP, ...installedThemes }),
        [installedThemes],
    );
    const availableThemes = useMemo(() => {
        const merged = { ...BUNDLED_THEME_MAP, ...installedThemes };
        const extras = Object.values(installedThemes).filter((t) => !(t.slug in BUNDLED_THEME_MAP));
        return [...BUNDLED_THEMES, ...extras].map((t) => merged[t.slug] || t);
    }, [installedThemes]);

    // Update the DOM attribute and resolved theme
    const applyTheme = useCallback((newTheme) => {
        document.documentElement.setAttribute('data-theme', newTheme);
        setResolvedTheme(getResolvedTheme(newTheme));
    }, []);

    // Public setter that updates state, localStorage, and DOM
    const setTheme = useCallback((newTheme) => {
        setThemeState(newTheme);
        localStorage.setItem('theme', newTheme);
        applyTheme(newTheme);
    }, [applyTheme]);

    // Public setter for accent color. Persists the user's explicit choice.
    const setAccentColor = useCallback((hex) => {
        setAccentColorState(hex);
        setHasCustomAccent(true);
        localStorage.setItem('accent_color', hex);
    }, []);

    // Clear the explicit accent so the active skin's accent (or the default)
    // takes over again.
    const resetAccentColor = useCallback(() => {
        setHasCustomAccent(false);
        setAccentColorState(DEFAULT_ACCENT);
        localStorage.removeItem('accent_color');
    }, []);

    // Public setter for the selected skin (per-user).
    const setSkin = useCallback((slug) => {
        const next = slug || DEFAULT_THEME_SLUG;
        setSkinState(next);
        localStorage.setItem('skin', next);
    }, []);

    // Live preview: temporarily apply a theme (or null for stock) without
    // persisting it — used by the gallery on hover. clearPreview restores the
    // currently-selected skin.
    const previewSkin = useCallback((themeObj) => {
        const skinAccent = applySkin(themeObj, resolvedTheme);
        applyAccentToDOM(
            computeEffectiveAccent({ workspaceAccent, hasCustomAccent, accentColor, skinAccent }),
        );
    }, [resolvedTheme, workspaceAccent, hasCustomAccent, accentColor]);

    const clearPreview = useCallback(() => {
        const skinTheme = skin !== DEFAULT_THEME_SLUG ? themesMap[skin] : null;
        const skinAccent = applySkin(skinTheme, resolvedTheme);
        applyAccentToDOM(
            computeEffectiveAccent({ workspaceAccent, hasCustomAccent, accentColor, skinAccent }),
        );
    }, [skin, themesMap, resolvedTheme, workspaceAccent, hasCustomAccent, accentColor]);

    // Merge installed (registry/imported) themes into the selectable set.
    const registerInstalledThemes = useCallback((list) => {
        if (!Array.isArray(list)) return;
        setInstalledThemes((prev) => {
            const next = { ...prev };
            for (const t of list) {
                if (t && t.slug) next[t.slug] = t;
            }
            return next;
        });
    }, []);

    // Public setter for white label config (accepts partial updates)
    const setWhiteLabel = useCallback((partial) => {
        setWhiteLabelState(prev => {
            const next = { ...prev, ...partial };
            localStorage.setItem('white_label', JSON.stringify(next));
            return next;
        });
    }, []);

    // Listen for OS theme changes when using 'system' theme
    useEffect(() => {
        if (theme !== 'system') return;

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        const handleChange = (e) => {
            setResolvedTheme(e.matches ? 'dark' : 'light');
        };

        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);
    }, [theme]);

    // Apply the theme mode attribute on mount / change.
    useEffect(() => {
        applyTheme(theme);
    }, [theme, applyTheme]);

    // Apply the active skin's tokens and the effective accent whenever anything
    // that feeds them changes. The 'default' slug means "no skin" — applySkin
    // is handed null so it clears any overrides and the stock stylesheet shows.
    useEffect(() => {
        const skinTheme = skin !== DEFAULT_THEME_SLUG ? themesMap[skin] : null;
        const skinAccent = applySkin(skinTheme, resolvedTheme);
        applyAccentToDOM(
            computeEffectiveAccent({ workspaceAccent, hasCustomAccent, accentColor, skinAccent }),
        );
    }, [skin, resolvedTheme, accentColor, hasCustomAccent, workspaceAccent, themesMap]);

    const activeTheme = skin !== DEFAULT_THEME_SLUG ? (themesMap[skin] || null) : null;

    const value = {
        theme,           // Current setting: 'dark' | 'light' | 'system'
        resolvedTheme,   // Actual appearance: 'dark' | 'light'
        setTheme,        // Function to change theme
        accentColor,     // Current accent hex color (user's explicit choice)
        setAccentColor,  // Function to change accent color
        hasCustomAccent, // Whether the accent is an explicit user override
        resetAccentColor,// Clear the explicit accent (fall back to skin/default)
        skin,            // Selected skin slug ('default' = stock)
        setSkin,         // Function to change the selected skin
        activeTheme,     // The active skin's theme object (null for stock)
        availableThemes, // Selectable themes (bundled + installed)
        previewSkin,     // Temporarily apply a theme (hover preview)
        clearPreview,    // Restore the selected skin after a preview
        registerInstalledThemes, // Merge registry/imported themes into the set
        whiteLabel,      // White label config object
        setWhiteLabel,   // Function to update white label config
    };

    return (
        <ThemeContext.Provider value={value}>
            {children}
        </ThemeContext.Provider>
    );
}

export function useTheme() {
    const context = useContext(ThemeContext);
    if (!context) {
        throw new Error('useTheme must be used within a ThemeProvider');
    }
    return context;
}

export default ThemeContext;
