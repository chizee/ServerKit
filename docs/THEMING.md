# Theming ServerKit

A ServerKit theme is **data, not code**: a small JSON file that maps color
tokens to values. There's no JavaScript, no build step, no permissions, and no
sandbox — the whole panel is already painted through CSS custom properties, so a
theme just supplies new values for them at runtime. Reviewing a theme is reading
a diff of colors.

- **Use a theme:** Settings → Appearance → **Theme**. Pick a card; it applies
  instantly and stays your personal choice. The dark/light toggle keeps working
  on top of it.
- **Make a theme:** Settings → Appearance → **Create theme** (Theme Studio) —
  edit colors over the live panel, then Export a `theme.json`, save it to this
  panel, or submit it to the registry.
- **Share a theme:** open a PR to the
  [`serverkit-themes`](https://github.com/jhd3197/serverkit-themes) registry.
  Merged = published.

---

## `theme.json` (schema_version 1)

```jsonc
{
  "schema_version": 1,
  "slug": "nord-deep",                  // required, kebab-case, unique, matches the folder
  "name": "Nord Deep",                  // required, display name
  "author": "your-handle",              // GitHub handle
  "version": "1.0.0",
  "description": "Cool arctic blues.",
  "base": "dark",                       // "dark" | "light" — which mode this is a skin OF
  "tokens": {
    "dark":  { "--bg-body": "#2e3440", "--surface": "#3b4252", "…": "…" },
    "light": { "…": "…" }               // optional — omit and the stock light theme is used
  },
  "accent": "#88c0d0",                  // optional — the panel derives the accent ramp from this
  "preview": ["#2e3440", "#3b4252", "#88c0d0", "#eceff4"]  // 4 gallery swatches
}
```

A **dark-only** theme omits `tokens.light` (the stock light theme is used when a
user toggles to light). A **light-only** theme (`base: "light"`) omits
`tokens.dark`. Provide both for a theme that should look intentional in either
mode.

---

## The token whitelist

A theme may set only these canonical tokens. You write ~37 names; the panel
fans each out to the legacy `--bg-*/--text-*/--border-*` aliases automatically,
so the whole UI tracks your theme. Accent tokens are **not** in this list — they
are derived from the single top-level `accent` field.

### Surfaces (colors)
| Token | Paints |
|---|---|
| `--bg-body` | App background (behind everything) |
| `--bg-sidebar` | Sidebar background |
| `--surface` | Card / panel surface (→ `--bg-card`) |
| `--surface-2` | Elevated / secondary surface (→ `--bg-elevated`, `--bg-secondary`) |
| `--surface-3` | Tertiary surface (→ `--bg-tertiary`) |
| `--surface-hover` | Hover surface (→ `--bg-hover`) |

### Borders (colors)
| Token | Paints |
|---|---|
| `--border` | Default border (→ `--border-default`) |
| `--border-soft` | Subtle divider (→ `--border-subtle`) |
| `--border-strong` | Active / strong border (→ `--border-active`, `--border-hover`) |

### Text (colors)
| Token | Paints |
|---|---|
| `--text` | Primary text (→ `--text-primary`) |
| `--text-dim` | Secondary text (→ `--text-secondary`) |
| `--text-faint` | Tertiary text (→ `--text-tertiary`) |
| `--text-ghost` | Faintest text / placeholders |

### Semantic (colors)
`--green`, `--green-bg`, `--amber`, `--amber-bg`, `--red`, `--red-bg`,
`--cyan`, `--cyan-bg`, `--violet`, `--violet-bg`.
The `*-bg` tokens are the translucent wash behind the matching accent (use an
`rgba()` at low alpha, e.g. `rgba(61,220,151,0.12)`).

### Chrome
| Token | Type | Paints |
|---|---|---|
| `--radius`, `--radius-sm`, `--radius-lg` | length | Corner radii |
| `--sans`, `--mono` | font stack | UI + monospace fonts (bundled families only) |
| `--shadow-sm`, `--shadow-md`, `--shadow-lg` | shadow | Elevation shadows |
| `--scrollbar-track`, `--scrollbar-thumb`, `--scrollbar-thumb-hover` | color | Scrollbars |
| `--bg-code`, `--text-code` | color | Code / terminal blocks |
| `--grid-color` | color | The faint background grid |

---

## Value rules (enforced client-side, server-side, and in registry CI)

- **Colors:** hex (`#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`), `rgb()/rgba()`,
  `hsl()/hsla()`, or a bare CSS named color.
- **Lengths:** a number with an optional `px/rem/em/%/vh/vw` unit (or `0`).
- **Fonts:** a font-family stack using only the families the panel already ships
  (IBM Plex Sans / Mono and the system fallbacks). **No `url()` — no remote
  fonts.** Most themes should omit `--sans`/`--mono` entirely.
- **Shadows:** standard `box-shadow` syntax, or `none`.
- **Never allowed anywhere:** `url(`, `@`, `;`, `}`, `{`, `<`, `>`,
  `expression(`, or `/*`. Values over 200 characters are rejected. Unknown
  tokens are dropped.

There is **no `custom_css` and no JavaScript** in a v1 theme. The moment
arbitrary CSS enters, a theme becomes code (exfiltration via
`background: url(...)`, UI spoofing) and the trust story collapses to the
extension one. Themes stay data on purpose.

Because every value is validated and applied per-token via
`CSSStyleDeclaration.setProperty`, a theme can't break out of its declaration or
smuggle a network request even if a validation rule is missed.

---

## Theme Studio (the authoring loop)

Settings → Appearance → **Create theme**:

1. **Start from** any installed theme to inherit its palette.
2. Edit colors with grouped pickers — every change applies to the **live panel**
   instantly, in the mode (dark/light) you're editing.
3. Set the **accent** once; the panel derives the hover/bright/dim/wash ramp.
4. **Export theme.json** (a valid, ready-to-share file), **Save to this panel**
   (admins — adds it to the gallery), or **Submit to registry** (opens a
   prefilled new-file PR against `serverkit-themes`).

No tooling to install — the whole authoring loop lives in the panel.

---

## Submit to the registry

The registry is the [`serverkit-themes`](https://github.com/jhd3197/serverkit-themes)
repo. Themes live **in** the repo — submission is a PR, publication is a merge:

1. Fork it. Add `themes/<slug>/theme.json` (or export one from Theme Studio).
2. Run `node scripts/build-index.mjs` and commit the updated `index.json`.
3. Open a PR. CI validates against the schema + token whitelist + value rules.
4. A maintainer merges — panels pick it up on their next registry refresh.

Operators can point a panel at a different registry with
`SERVERKIT_THEMES_REGISTRY_URL` (unset = the public registry; set-but-empty =
bundled seeds only). The panel is offline-tolerant: a failed fetch falls back to
the last good cache, then to the themes bundled with the panel — the gallery
never blanks.

---

## Notes & limits (v1)

- **Charts, xterm terminal, and the code/diff viewers** read their own color
  configs; they track the semantic tokens where feasible but are otherwise
  documented as unthemed for v1.
- **Hardcoded colors:** any page style not reading a token will ignore a skin.
  The panel's styles route through tokens; if you spot a straggler, it's a bug
  worth reporting.
- **The token names never change** — themes ride the existing names, so a theme
  authored today keeps working. A newer theme on an older panel degrades
  gracefully (unknown tokens are simply dropped).
