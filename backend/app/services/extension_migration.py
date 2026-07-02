"""One-shot auto-install of converted builtin extensions (decision D3).

When a core page is converted into a builtin extension, an *upgraded* panel must
not lose the feature. On the first boot after such an upgrade we auto-install the
extension once, recording a per-slug marker so we never do it again — the user is
free to uninstall afterwards and it stays uninstalled.

Fresh installs are different: they never had the page as a core feature, so they
should discover the extension in the Marketplace rather than have it pre-installed
(flagships that ship installed-by-default per D4 are handled separately, not here).
We distinguish the two by whether any user exists yet — a brand-new panel has none
until the setup wizard creates the first admin.

The whole pass is best-effort: a failure to install (e.g. a Docker panel whose
frontend plugins dir isn't writable) is logged and retried on the next boot, and
never blocks startup. The builtin frontends are pre-bundled (D5) regardless, so
the marker only governs whether the contribution is switched on.
"""
import json
import logging

from app import db
from app.models.plugin import InstalledPlugin

logger = logging.getLogger(__name__)

# Builtin extensions that were previously shipped as core pages. Append a slug
# here when its page is converted; existing panels then auto-install it once.
CONVERTED_BUILTIN_SLUGS = [
    'serverkit-gpu',
    'serverkit-workflows',
]

_MARKER_KEY = 'extensions.auto_installed_slugs'


def _processed_slugs():
    from app.services.settings_service import SettingsService
    raw = SettingsService.get(_MARKER_KEY, '')
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (ValueError, TypeError):
        # Tolerate a legacy comma-joined value.
        return {s.strip() for s in str(raw).split(',') if s.strip()}


def _save_processed(slugs):
    from app.services.settings_service import SettingsService
    SettingsService.set(_MARKER_KEY, json.dumps(sorted(slugs)))


def _looks_like_existing_install():
    """True if this panel has prior data (an upgrade), False if brand-new.

    A fresh install has no users yet — the setup wizard creates the first admin.
    """
    from app.models.user import User
    try:
        return db.session.query(User.id).first() is not None
    except Exception:
        return False


def run_auto_install():
    """Install converted builtins once on an upgraded panel. Idempotent."""
    processed = _processed_slugs()
    existing = _looks_like_existing_install()

    try:
        from app.services.plugin_service import (
            install_builtin_extension,
            list_builtin_extensions,
        )
        available = {e['slug'] for e in list_builtin_extensions()}
    except Exception as e:
        logger.warning(f'Extension auto-install skipped (builtins unavailable): {e}')
        return

    changed = False
    for slug in CONVERTED_BUILTIN_SLUGS:
        if slug in processed:
            continue

        # Not yet shipped as a builtin folder — skip quietly, revisit next boot.
        if slug not in available:
            continue

        if existing:
            # Upgrade path: keep the feature alive unless it's already present.
            if not InstalledPlugin.query.filter_by(slug=slug).first():
                try:
                    install_builtin_extension(slug)
                    logger.info(f'Auto-installed converted builtin extension: {slug}')
                except Exception as e:
                    logger.warning(
                        f'Auto-install of {slug} failed (retry next boot): {e}'
                    )
                    continue  # leave unmarked so we retry
        # Fresh install (marketplace-only) OR successfully installed: record it.
        processed.add(slug)
        changed = True

    if changed:
        _save_processed(processed)
