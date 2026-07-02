"""
Plugin Service - Download, install, and manage ServerKit plugins from URLs.

Plugins are zip files containing a plugin.json manifest, optional backend/
and frontend/ directories. They get extracted into the ServerKit plugins
directories and auto-registered at startup.
"""
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from app import db
from app.models.plugin import InstalledPlugin

logger = logging.getLogger(__name__)

# Resolve paths relative to the backend directory.
# __file__ = backend/app/services/plugin_service.py
# _APP_DIR = backend/app/
# _BACKEND_ROOT = backend/
# _PROJECT_ROOT = ServerKit/
#
# Both targets are env-var overridable. The defaults work for native dev
# (backend run from a checkout). They break in Docker because the backend
# image only contains /app — the host's frontend directory isn't mounted —
# so dockerized panels MUST set SERVERKIT_FRONTEND_PLUGINS_DIR (and bind
# mount the corresponding host folder) when installing plugins that ship
# a frontend.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_ROOT = os.path.dirname(_APP_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_ROOT)

BACKEND_PLUGINS_DIR = os.environ.get(
    'SERVERKIT_BACKEND_PLUGINS_DIR',
    os.path.join(_APP_DIR, 'plugins'),
)
FRONTEND_PLUGINS_DIR = os.environ.get(
    'SERVERKIT_FRONTEND_PLUGINS_DIR',
    os.path.join(_PROJECT_ROOT, 'frontend', 'src', 'plugins'),
)

# Folder of bundled-with-the-repo extensions that ship as plugins
# but are not installed by default. The discovery endpoint enumerates
# this folder so the Marketplace can show one-click installs without
# requiring users to know absolute paths.
BUILTIN_EXTENSIONS_DIR = os.environ.get(
    'SERVERKIT_BUILTIN_EXTENSIONS_DIR',
    os.path.join(_PROJECT_ROOT, 'builtin-extensions'),
)


def _ensure_backend_dir():
    """Create the backend plugin dir; raise a useful error if we can't."""
    try:
        os.makedirs(BACKEND_PLUGINS_DIR, exist_ok=True)
    except OSError as e:
        raise ValueError(
            f"Cannot create backend plugin directory at {BACKEND_PLUGINS_DIR}: {e}. "
            f"Set SERVERKIT_BACKEND_PLUGINS_DIR to a writable path."
        )
    init_path = os.path.join(BACKEND_PLUGINS_DIR, '__init__.py')
    if not os.path.exists(init_path):
        with open(init_path, 'w') as f:
            f.write('')


def _ensure_frontend_dir():
    """Create the frontend plugin dir on demand. Called only when a plugin
    actually ships frontend content — plugins without frontends never need
    this directory and shouldn't fail just because it doesn't exist (a
    common case in Docker)."""
    try:
        os.makedirs(FRONTEND_PLUGINS_DIR, exist_ok=True)
    except OSError as e:
        raise ValueError(
            f"This plugin ships a frontend, but the panel can't write to "
            f"the frontend plugin directory ({FRONTEND_PLUGINS_DIR}): {e}.\n\n"
            f"If the panel runs in Docker, this is expected — the container "
            f"sees only /app, not the host's frontend folder. Two fixes:\n"
            f"  • Bind-mount the host's frontend/src/plugins into the "
            f"container and set SERVERKIT_FRONTEND_PLUGINS_DIR to that path.\n"
            f"  • Or run the backend natively for plugin development.\n\n"
            f"You can also install the backend half only by stripping the "
            f"frontend/ folder from the plugin zip, but the UI half won't load."
        )


def _ensure_dirs():
    """Backwards-compatible eager init for backend dir only. Frontend dir is
    lazy now — see _ensure_frontend_dir."""
    _ensure_backend_dir()


def _resolve_github_url(url):
    """Convert a GitHub repo URL to the latest release zip download URL.

    Handles:
      - https://github.com/user/repo  -> latest release zip
      - https://github.com/user/repo/releases/tag/v1.0.0  -> that release zip
      - Direct zip URLs pass through unchanged
    """
    if url.endswith('.zip'):
        return url

    # Match github.com/owner/repo patterns
    gh_match = re.match(
        r'https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/releases/tag/([^/]+))?/?$',
        url,
    )
    if not gh_match:
        return url

    owner, repo, tag = gh_match.groups()

    if tag:
        # Specific release - get its assets
        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}'
    else:
        # Latest release
        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'

    try:
        resp = requests.get(api_url, timeout=15, headers={'Accept': 'application/vnd.github+json'})
        resp.raise_for_status()
        release = resp.json()

        # Look for a .zip asset (prefer plugin zip over source)
        for asset in release.get('assets', []):
            if asset['name'].endswith('.zip'):
                return asset['browser_download_url']

        # Fallback to source zipball
        return release.get('zipball_url', url)
    except Exception as e:
        logger.warning(f'Could not resolve GitHub release URL: {e}')
        # Fallback: try the zipball endpoint directly
        if tag:
            return f'https://api.github.com/repos/{owner}/{repo}/zipball/{tag}'
        return f'https://api.github.com/repos/{owner}/{repo}/zipball'


def _download_zip(url):
    """Download a zip file from URL and return bytes."""
    resolved = _resolve_github_url(url)
    logger.info(f'Downloading plugin from: {resolved}')
    resp = requests.get(resolved, timeout=120, stream=True, headers={
        'Accept': 'application/octet-stream',
        'User-Agent': 'ServerKit-Plugin-Installer/1.0',
    })
    resp.raise_for_status()

    buf = io.BytesIO()
    for chunk in resp.iter_content(chunk_size=8192):
        buf.write(chunk)
    buf.seek(0)
    return buf


def _find_manifest(zf):
    """Find plugin.json inside the zip, handling nested directories (GitHub zipball nesting)."""
    for name in zf.namelist():
        basename = os.path.basename(name)
        if basename == 'plugin.json':
            # Return the directory prefix so we can strip it
            prefix = name[: -len('plugin.json')]
            return name, prefix
    return None, None


def _validate_manifest(manifest):
    """Validate required fields in plugin manifest."""
    required = ['name', 'display_name', 'version']
    missing = [f for f in required if f not in manifest]
    if missing:
        raise ValueError(f"Manifest missing required fields: {', '.join(missing)}")

    # Sanitize the name for use as a directory
    name = manifest['name']
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise ValueError(f"Plugin name must be alphanumeric/dashes/underscores: {name}")

    return True


def _safe_extract_path(dest_root, rel_path):
    """Resolve `rel_path` under `dest_root` and assert it stays inside.

    Defense against Zip Slip: a malicious archive can carry entries like
    `../../etc/cron.d/foo` or absolute paths. Without this check, the
    extract loop happily writes outside the plugin directory and into
    anything the backend process can touch.

    Returns the validated absolute output path, or raises ValueError.
    """
    if not rel_path:
        raise ValueError('empty path in archive')
    normalized = rel_path.replace('\\', '/').lstrip('/')
    if normalized.startswith('/') or ':' in normalized.split('/')[0]:
        raise ValueError(f'absolute path in archive: {rel_path!r}')
    if '..' in normalized.split('/'):
        raise ValueError(f'path traversal in archive: {rel_path!r}')
    out = os.path.normpath(os.path.join(dest_root, normalized))
    root = os.path.normpath(dest_root) + os.sep
    if not (out + os.sep).startswith(root):
        raise ValueError(f'archive entry escapes destination: {rel_path!r}')
    return out


def _update_plugin_metadata(plugin, manifest):
    """Sync mutable manifest-derived fields onto an existing plugin row.

    Used on reinstall: the new manifest may have a fresh display_name,
    author, description, etc. Without this, those fields go stale and
    the UI keeps showing the original values.
    """
    plugin.name = manifest['name']
    plugin.display_name = manifest['display_name']
    plugin.description = manifest.get('description', '')
    plugin.author = manifest.get('author', '')
    plugin.homepage = manifest.get('homepage', '')
    plugin.repository = manifest.get('repository', '')
    plugin.license = manifest.get('license', '')
    plugin.category = manifest.get('category', 'utility')


def install_from_url(url, user_id=None, expected_sha256=None, force=False):
    """Download and install a plugin from a URL.

    Args:
        url: GitHub repo URL, release URL, or direct zip URL
        user_id: ID of the user performing the install
        expected_sha256: if given, the downloaded zip must match this digest
            before extraction — a mismatch is a hard failure (no partial install)
        force: allow reinstalling over an already-active plugin (used by updates)

    Returns:
        InstalledPlugin instance
    """
    try:
        buf = _download_zip(url)
    except Exception as e:
        raise ValueError(f'Failed to download plugin: {e}')

    if expected_sha256:
        import hashlib
        digest = hashlib.sha256(buf.getvalue()).hexdigest()
        if digest.lower() != str(expected_sha256).lower():
            raise ValueError(
                f'Checksum mismatch — refusing to install. '
                f'Expected sha256 {expected_sha256}, got {digest}.'
            )
        buf.seek(0)

    return _install_from_buffer(
        buf, source_url=url, source_type='url', user_id=user_id, force=force,
    )


def install_from_path(path, user_id=None):
    """Install a plugin from a local directory on the panel host.

    Useful during plugin development: point at the working tree, install,
    iterate. Internally we zip the folder in memory and reuse the same
    install pipeline as URL/upload installs so behavior is identical.

    Note: "local" here means local to the *panel backend*, not to the
    user's browser. If the backend runs in Docker, browser-host paths
    won't resolve — the user should either bind-mount their plugin
    source into the container or use install_from_zip via the upload
    endpoint instead.
    """
    if not path:
        raise ValueError('path is required')

    raw = path

    # Windows path on a non-Windows panel host is the most common
    # foot-gun (typical case: backend in Docker, dev on Windows). Detect
    # and reject with a helpful message before os.path.abspath turns it
    # into garbage like /app/C:\Users\...
    if os.name != 'nt' and len(path) >= 3 and path[1:3] == ':\\':
        raise ValueError(
            f"'{raw}' looks like a Windows path, but the panel backend is "
            f"running on {os.name!r} (likely a Linux container). The folder "
            f"install runs on the panel host's filesystem, not your browser's. "
            f"Either bind-mount your plugin source into the backend container, "
            f"or use 'Upload Zip' instead."
        )

    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        raise ValueError(
            f"Not a directory: {path}\n"
            f"This path is resolved on the panel backend ({os.name!r}), not "
            f"your browser. If the backend runs in Docker, the path must "
            f"exist inside the container — bind-mount the source folder or "
            f"use 'Upload Zip'."
        )
    if not os.path.exists(os.path.join(path, 'plugin.json')):
        raise ValueError(f'No plugin.json in {path}')

    # Zip the folder in memory, skipping dev junk that bloats the bundle.
    skip_dirs = {
        '.git', '.github', 'node_modules', '__pycache__',
        '.venv', 'venv', 'dist', 'build', '.pytest_cache',
        '.idea', '.vscode',
    }
    skip_files_endswith = ('.pyc', '.pyo')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(path):
            # mutate dirs in place so os.walk skips them
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if name.endswith(skip_files_endswith):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path).replace(os.sep, '/')
                zf.write(full, rel)
    buf.seek(0)

    return _install_from_buffer(
        buf, source_url=path, source_type='local', user_id=user_id,
    )


def install_from_zip(zip_bytes, user_id=None, source_name=None):
    """Install a plugin from raw zip bytes (e.g. a multipart upload)."""
    if not zip_bytes:
        raise ValueError('Empty upload')
    buf = io.BytesIO(zip_bytes)
    return _install_from_buffer(
        buf,
        source_url=source_name or 'uploaded.zip',
        source_type='upload',
        user_id=user_id,
    )


def _install_from_buffer(buf, source_url, source_type, user_id=None, force=False):
    """Shared install pipeline: takes a seekable BytesIO containing a zip,
    extracts it into the panel's plugin dirs, and registers / hot-loads
    the resulting blueprint. All public install_* helpers funnel here so
    behavior matches across URL / local / upload sources.

    `force=True` allows reinstalling over an active plugin (the update path);
    normal installs still refuse to clobber an active install.
    """
    _ensure_dirs()

    # Open zip
    try:
        zf = zipfile.ZipFile(buf)
    except zipfile.BadZipFile:
        raise ValueError('File is not a valid zip archive')

    # Find and read manifest
    manifest_path, prefix = _find_manifest(zf)
    if not manifest_path:
        raise ValueError('No plugin.json found in archive')

    manifest = json.loads(zf.read(manifest_path))
    _validate_manifest(manifest)

    slug = manifest['name']

    # Check if already installed
    existing = InstalledPlugin.query.filter_by(slug=slug).first()
    if existing and existing.status in ('active', 'installing') and not force:
        raise ValueError(f"Plugin '{slug}' is already installed (v{existing.version}). Uninstall first to reinstall.")

    # Create DB record early so we can track errors
    if existing:
        plugin = existing
        plugin.status = InstalledPlugin.STATUS_INSTALLING
        plugin.error_message = None
        plugin.version = manifest['version']
        plugin.source_url = source_url
        plugin.source_type = source_type
        plugin.manifest = manifest
        # Refresh display/description/author/etc from the new manifest so
        # the UI reflects the just-installed version, not the original.
        _update_plugin_metadata(plugin, manifest)
    else:
        plugin = InstalledPlugin(
            name=manifest['name'],
            display_name=manifest['display_name'],
            slug=slug,
            version=manifest['version'],
            description=manifest.get('description', ''),
            author=manifest.get('author', ''),
            homepage=manifest.get('homepage', ''),
            repository=manifest.get('repository', ''),
            license=manifest.get('license', ''),
            category=manifest.get('category', 'utility'),
            source_url=source_url,
            source_type=source_type,
            installed_by=user_id,
            status=InstalledPlugin.STATUS_INSTALLING,
        )
        plugin.manifest = manifest
        db.session.add(plugin)

    db.session.commit()

    try:
        # First pass — figure out what the archive contains. This lets us
        # bail early with a useful error if the plugin needs a frontend
        # dir we can't write to (the dockerized panel case).
        has_backend = False
        has_frontend = False
        for member in zf.namelist():
            rel = member[len(prefix):] if prefix else member
            if not rel or rel.endswith('/'):
                continue
            if rel.startswith('backend/'):
                has_backend = True
            elif rel.startswith('frontend/'):
                has_frontend = True

        if has_frontend:
            _ensure_frontend_dir()  # raises with a helpful message on failure

        backend_dest = os.path.join(BACKEND_PLUGINS_DIR, slug)
        frontend_dest = os.path.join(FRONTEND_PLUGINS_DIR, slug)

        # Clean old install
        if os.path.exists(backend_dest):
            shutil.rmtree(backend_dest)
        if has_frontend and os.path.exists(frontend_dest):
            shutil.rmtree(frontend_dest)

        for member in zf.namelist():
            # Strip the GitHub zipball prefix
            rel_path = member[len(prefix):] if prefix else member
            if not rel_path or rel_path.endswith('/'):
                continue

            if rel_path.startswith('backend/'):
                # Zip Slip defense: _safe_extract_path rejects absolute
                # paths, .. segments, and anything that resolves outside
                # backend_dest after normalization.
                out_path = _safe_extract_path(
                    backend_dest, rel_path[len('backend/'):]
                )
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with zf.open(member) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())

            elif rel_path.startswith('frontend/'):
                out_path = _safe_extract_path(
                    frontend_dest, rel_path[len('frontend/'):]
                )
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with zf.open(member) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())

            elif rel_path == 'requirements.txt':
                # Plugin Python deps are sandboxed by default: installing
                # them runs pip with the backend's privileges, which means
                # arbitrary code via setup.py hooks. Operators must opt in
                # by setting SERVERKIT_ALLOW_PLUGIN_PIP=1.
                req_content = zf.read(member).decode('utf-8')
                if req_content.strip() and os.environ.get(
                    'SERVERKIT_ALLOW_PLUGIN_PIP', ''
                ).lower() in ('1', 'true', 'yes'):
                    _install_requirements(req_content, slug)
                elif req_content.strip():
                    # Persist the requirements file so the admin can review
                    # and install it manually if they want.
                    req_out = _safe_extract_path(backend_dest, 'requirements.txt')
                    os.makedirs(os.path.dirname(req_out), exist_ok=True)
                    with open(req_out, 'w', encoding='utf-8') as f:
                        f.write(req_content)
                    logger.warning(
                        f"Plugin {slug} ships requirements.txt; skipping install "
                        f"(set SERVERKIT_ALLOW_PLUGIN_PIP=1 to enable). "
                        f"File saved to {req_out} for manual review."
                    )

        # Also write the manifest into the backend plugin dir for runtime access
        if has_backend:
            manifest_out = os.path.join(backend_dest, 'plugin.json')
            with open(manifest_out, 'w') as f:
                json.dump(manifest, f, indent=2)

        # Also write manifest to frontend dir
        if has_frontend:
            manifest_out = os.path.join(frontend_dest, 'plugin.json')
            with open(manifest_out, 'w') as f:
                json.dump(manifest, f, indent=2)

        # Determine blueprint info from manifest
        entry_point = manifest.get('entry_point', '')
        url_prefix = manifest.get('url_prefix', f'/api/v1/{slug}')

        plugin.has_backend = has_backend
        plugin.has_frontend = has_frontend
        plugin.backend_path = f'app/plugins/{slug}' if has_backend else None
        plugin.frontend_path = f'src/plugins/{slug}' if has_frontend else None
        plugin.entry_point = entry_point
        plugin.url_prefix = url_prefix
        plugin.frontend_entry = manifest.get('frontend_entry', '')
        plugin.status = InstalledPlugin.STATUS_ACTIVE
        db.session.commit()

        # Try to register the blueprint immediately (hot-load)
        if has_backend and entry_point:
            try:
                _register_plugin_blueprint(plugin)
            except Exception as e:
                logger.warning(f'Blueprint hot-load failed for {slug} (will load on restart): {e}')

        # Regenerate frontend plugin manifest
        if has_frontend:
            _regenerate_frontend_manifest()

        # Install template dependencies declared in manifest
        # (e.g. a "git-server" extension declaring "templates": ["gitea"]).
        # Best effort — record per-template result on the plugin row so the
        # UI can show what happened, but a template install failure does
        # not roll back the plugin install.
        template_results = _install_template_dependencies(plugin, manifest)

        # Run plugin's lifecycle.install hook if declared. Failure here is
        # also non-fatal — the plugin is installed; the hook is for
        # convenience setup (e.g. creating default rows).
        _run_lifecycle_hook(plugin, manifest, 'install')

        # If the plugin declares an "ai" block, register its tools/context with
        # the core assistant now so installing it teaches the assistant new
        # abilities without a restart. Best effort.
        _refresh_plugin_ai(plugin)

        logger.info(f'Plugin {slug} v{manifest["version"]} installed successfully')
        if template_results:
            plugin._template_install_results = template_results  # surfaced via to_dict if needed
        return plugin

    except Exception as e:
        plugin.status = InstalledPlugin.STATUS_ERROR
        plugin.error_message = str(e)
        db.session.commit()
        raise


def _install_requirements(req_content, plugin_name):
    """Install Python requirements for a plugin."""
    if not req_content.strip():
        return

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(req_content)
        req_path = f.name

    try:
        logger.info(f'Installing requirements for plugin {plugin_name}')
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '-r', req_path, '--quiet'],
            timeout=300,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f'Failed to install requirements for {plugin_name}: {e}')
        raise ValueError(f'Failed to install Python dependencies: {e}')
    finally:
        os.unlink(req_path)


def _attach_status_guard(bp, slug):
    """Attach a before_request that 503s if the plugin is disabled.

    Flask blueprints can't be unregistered from a running app, so once a
    plugin's routes are loaded they stay reachable until restart. This
    guard makes the in-DB status authoritative at request time, so
    disabling a plugin actually stops serving its routes.
    """
    def _check():
        from flask import jsonify
        p = InstalledPlugin.query.filter_by(slug=slug).first()
        if not p or p.status != InstalledPlugin.STATUS_ACTIVE:
            return jsonify({
                'error': f"Plugin '{slug}' is not active",
                'status': p.status if p else 'uninstalled',
            }), 503
        return None
    bp.before_request(_check)


def _register_plugin_blueprint(plugin):
    """Dynamically register a plugin's Flask blueprint into the running app."""
    from flask import current_app
    import importlib

    if not plugin.entry_point:
        return

    # entry_point format: "blueprint:ai_assistant_bp"
    parts = plugin.entry_point.split(':')
    if len(parts) != 2:
        raise ValueError(f'Invalid entry_point format: {plugin.entry_point}')

    module_name, bp_name = parts
    full_module = f'app.plugins.{plugin.slug}.{module_name}'

    try:
        mod = importlib.import_module(full_module)
        bp = getattr(mod, bp_name)
        _attach_status_guard(bp, plugin.slug)
        current_app.register_blueprint(bp, url_prefix=plugin.url_prefix)
        logger.info(f'Registered blueprint {bp_name} at {plugin.url_prefix}')
    except Exception as e:
        raise ValueError(f'Failed to register blueprint: {e}')


def _regenerate_frontend_manifest():
    """Generate a plugins-manifest.json for the frontend build system.

    This file tells the frontend which plugins are installed and where
    their components/styles live so Vite can include them.

    Best-effort: if the frontend dir doesn't exist (e.g. a pure backend
    plugin install where no frontend was ever extracted, or a Docker
    panel without the bind mount), we just log and move on rather than
    failing the install.
    """
    if not os.path.isdir(FRONTEND_PLUGINS_DIR):
        logger.info(
            f'Skipping frontend manifest regeneration: '
            f'{FRONTEND_PLUGINS_DIR} does not exist'
        )
        return
    manifest_path = os.path.join(FRONTEND_PLUGINS_DIR, 'plugins-manifest.json')

    plugins = InstalledPlugin.query.filter(
        InstalledPlugin.has_frontend == True,
        InstalledPlugin.status.in_(['active']),
    ).all()

    entries = []
    for p in plugins:
        entry = {
            'name': p.name,
            'slug': p.slug,
            'display_name': p.display_name,
            'version': p.version,
            'frontend_entry': p.frontend_entry,
            'path': p.slug,
        }
        # Check for styles
        style_dir = os.path.join(FRONTEND_PLUGINS_DIR, p.slug, 'styles')
        if os.path.isdir(style_dir):
            styles = [
                f for f in os.listdir(style_dir)
                if f.endswith('.scss') or f.endswith('.css') or f.endswith('.less')
            ]
            entry['styles'] = [f'plugins/{p.slug}/styles/{s}' for s in styles]
        entries.append(entry)

    with open(manifest_path, 'w') as f:
        json.dump({'plugins': entries}, f, indent=2)

    logger.info(f'Frontend plugin manifest regenerated with {len(entries)} plugin(s)')


def load_all_plugins(app):
    """Load all active plugin blueprints at app startup.

    Called from create_app() to register all installed plugin blueprints.
    """
    _ensure_dirs()

    with app.app_context():
        plugins = InstalledPlugin.query.filter_by(
            status=InstalledPlugin.STATUS_ACTIVE,
            has_backend=True,
        ).all()

        for plugin in plugins:
            if not plugin.entry_point:
                continue
            try:
                parts = plugin.entry_point.split(':')
                if len(parts) != 2:
                    continue

                module_name, bp_name = parts
                full_module = f'app.plugins.{plugin.slug}.{module_name}'

                import importlib
                mod = importlib.import_module(full_module)
                bp = getattr(mod, bp_name)
                _attach_status_guard(bp, plugin.slug)
                app.register_blueprint(bp, url_prefix=plugin.url_prefix)
                logger.info(f'Loaded plugin: {plugin.display_name} v{plugin.version} at {plugin.url_prefix}')
            except Exception as e:
                logger.error(f'Failed to load plugin {plugin.slug}: {e}')
                plugin.status = InstalledPlugin.STATUS_ERROR
                plugin.error_message = f'Failed to load: {e}'
                db.session.commit()


def uninstall_plugin(plugin_id):
    """Uninstall a plugin by removing its files and DB record."""
    plugin = InstalledPlugin.query.get(plugin_id)
    if not plugin:
        return False

    slug = plugin.slug
    manifest = plugin.manifest or {}

    # Run lifecycle.uninstall hook *before* we delete the files (the hook
    # may need to read its own files). Best effort — never block teardown.
    _run_lifecycle_hook(plugin, manifest, 'uninstall')

    # Drop any AI tools/context this plugin contributed to the assistant.
    _unregister_plugin_ai(slug)

    # Remove backend files
    backend_dest = os.path.join(BACKEND_PLUGINS_DIR, slug)
    if os.path.exists(backend_dest):
        shutil.rmtree(backend_dest)

    # Remove frontend files
    frontend_dest = os.path.join(FRONTEND_PLUGINS_DIR, slug)
    if os.path.exists(frontend_dest):
        shutil.rmtree(frontend_dest)

    db.session.delete(plugin)
    db.session.commit()

    # Regenerate frontend manifest
    _regenerate_frontend_manifest()

    logger.info(f'Plugin {slug} uninstalled')
    return True


def enable_plugin(plugin_id):
    """Enable a disabled plugin."""
    plugin = InstalledPlugin.query.get(plugin_id)
    if not plugin:
        return None
    plugin.status = InstalledPlugin.STATUS_ACTIVE
    plugin.error_message = None
    db.session.commit()
    _regenerate_frontend_manifest()
    _refresh_plugin_ai(plugin)
    return plugin


def disable_plugin(plugin_id):
    """Disable a plugin without removing files."""
    plugin = InstalledPlugin.query.get(plugin_id)
    if not plugin:
        return None
    plugin.status = InstalledPlugin.STATUS_DISABLED
    db.session.commit()
    _regenerate_frontend_manifest()
    _unregister_plugin_ai(plugin.slug)
    return plugin


def _refresh_plugin_ai(plugin):
    """Register a plugin's AI tools/context with the core assistant (if it has an
    ``ai`` manifest block). Idempotent; safe whether or not AI is initialized."""
    try:
        manifest = plugin.manifest or {}
        if isinstance(manifest.get('ai'), dict):
            from app.services.ai_tool_registry import ai_tool_registry
            ai_tool_registry.reload_plugin(plugin.slug)
    except Exception:
        logger.warning(f'AI tool refresh failed for plugin {plugin.slug}', exc_info=True)


def _unregister_plugin_ai(slug):
    """Drop a plugin's AI tools/context from the core assistant."""
    try:
        from app.services.ai_tool_registry import ai_tool_registry
        ai_tool_registry.unregister_plugin(slug)
    except Exception:
        logger.warning(f'AI tool unregister failed for plugin {slug}', exc_info=True)


def _run_lifecycle_hook(plugin, manifest, phase):
    """Execute a plugin's lifecycle hook.

    Manifest format:
        "lifecycle": { "install": "module:func", "uninstall": "module:func" }

    The module path is resolved under ``app.plugins.<slug>``. The hook
    receives the InstalledPlugin row as its single positional arg. Return
    value is ignored. Failure is logged and swallowed — lifecycle hooks
    are convenience, not correctness.
    """
    lifecycle = (manifest or {}).get('lifecycle') or {}
    target = lifecycle.get(phase)
    if not target or ':' not in target:
        return

    module_name, func_name = target.split(':', 1)
    full_module = f'app.plugins.{plugin.slug}.{module_name}'

    try:
        import importlib
        mod = importlib.import_module(full_module)
        func = getattr(mod, func_name, None)
        if not callable(func):
            logger.warning(
                f'Lifecycle {phase} hook {target} for {plugin.slug} is not callable'
            )
            return
        func(plugin)
        logger.info(f'Ran lifecycle.{phase} hook for {plugin.slug}')
    except Exception as e:
        logger.warning(f'Lifecycle {phase} hook for {plugin.slug} failed: {e}')


def _install_template_dependencies(plugin, manifest):
    """Install app templates declared in the manifest's `templates` key.

    Format:
        "templates": ["gitea", "umami"]            # template ids
        "templates": [{ "id": "gitea",
                        "app_name": "git-server",   # default: template id
                        "variables": {"PORT": "3000"} }]

    Returns a list of {template_id, success, message} dicts. Failures are
    logged but do not abort the plugin install — the user can install the
    template manually from /templates if it didn't auto-install.
    """
    deps = (manifest or {}).get('templates') or []
    if not deps:
        return []

    try:
        from app.services.template_service import TemplateService
    except Exception as e:
        logger.warning(f'TemplateService unavailable; skipping template deps: {e}')
        return []

    results = []
    for dep in deps:
        if isinstance(dep, str):
            template_id, app_name, variables = dep, dep, {}
        elif isinstance(dep, dict):
            template_id = dep.get('id') or dep.get('template_id')
            app_name = dep.get('app_name') or template_id
            variables = dep.get('variables') or {}
        else:
            continue

        if not template_id:
            continue

        try:
            res = TemplateService.install_template(
                template_id=template_id,
                app_name=app_name,
                user_variables=variables,
                user_id=plugin.installed_by,
            )
            ok = bool(res and res.get('success'))
            results.append({
                'template_id': template_id,
                'success': ok,
                'message': res.get('error') if not ok else 'installed',
            })
            if ok:
                logger.info(f'Plugin {plugin.slug} installed template {template_id}')
            else:
                logger.warning(
                    f'Plugin {plugin.slug} template dep {template_id} failed: '
                    f'{res.get("error")}'
                )
        except Exception as e:
            logger.warning(
                f'Plugin {plugin.slug} template dep {template_id} raised: {e}'
            )
            results.append({
                'template_id': template_id,
                'success': False,
                'message': str(e),
            })

    return results


def list_plugins(status=None):
    """List installed plugins."""
    query = InstalledPlugin.query
    if status:
        query = query.filter_by(status=status)
    return query.order_by(InstalledPlugin.display_name).all()


def get_plugin(plugin_id):
    """Get a single plugin by ID."""
    return InstalledPlugin.query.get(plugin_id)


def get_plugin_by_slug(slug):
    """Get a plugin by its slug."""
    return InstalledPlugin.query.filter_by(slug=slug).first()


def list_builtin_extensions():
    """Enumerate folders in BUILTIN_EXTENSIONS_DIR that look like plugins.

    Each entry includes the manifest, the absolute source path, and the
    install state (installed/active/disabled/error/not_installed). The
    Marketplace UI uses this to render one-click installs.
    """
    out = []
    if not os.path.isdir(BUILTIN_EXTENSIONS_DIR):
        return out

    for name in sorted(os.listdir(BUILTIN_EXTENSIONS_DIR)):
        folder = os.path.join(BUILTIN_EXTENSIONS_DIR, name)
        manifest_path = os.path.join(folder, 'plugin.json')
        if not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            logger.warning(f'Skipping builtin {name}: bad plugin.json ({e})')
            continue

        slug = manifest.get('name') or name
        existing = InstalledPlugin.query.filter_by(slug=slug).first()
        installed_state = existing.status if existing else 'not_installed'

        out.append({
            'folder': name,
            'path': folder,
            'slug': slug,
            'manifest': manifest,
            'installed': existing is not None,
            'install_id': existing.id if existing else None,
            'status': installed_state,
        })

    return out


def install_builtin_extension(slug, user_id=None):
    """Install a builtin extension by its slug (folder lookup)."""
    if not os.path.isdir(BUILTIN_EXTENSIONS_DIR):
        raise ValueError(f'Builtin extensions dir not found: {BUILTIN_EXTENSIONS_DIR}')

    for entry in list_builtin_extensions():
        if entry['slug'] == slug:
            return install_from_path(entry['path'], user_id=user_id)

    raise ValueError(f"No builtin extension with slug '{slug}'")


def _assert_panel_compatible(entry):
    """Raise if the panel version is outside an entry's min/max_panel_version."""
    from app.utils.version import version_satisfies, get_panel_version
    panel = get_panel_version()
    minv = entry.get('min_panel_version')
    maxv = entry.get('max_panel_version')
    if not version_satisfies(panel, minv, maxv):
        raise ValueError(
            f"{entry.get('display_name') or entry.get('slug')} "
            f"v{entry.get('version')} needs panel "
            f"{minv or '*'}–{maxv or '*'} (this panel is {panel})."
        )


def install_registry_extension(slug, user_id=None):
    """Install an extension listed in the remote registry (checksum-verified)."""
    from app.services import registry_service
    entry = registry_service.get_entry(slug)
    if not entry:
        raise ValueError(f"No registry extension with slug '{slug}'")
    _assert_panel_compatible(entry)
    source = (entry.get('source') or '').strip()
    if not source:
        raise ValueError(f"Registry entry '{slug}' has no source URL.")
    return install_from_url(
        source, user_id=user_id, expected_sha256=entry.get('sha256'),
    )


def check_for_updates():
    """Compare installed plugins to the registry; return update candidates.

    Update v1 is registry-driven: a plugin whose slug is in the registry with a
    higher version than installed is flagged. Panel-version compatibility is
    surfaced so the UI can gray out an update the panel can't run yet.
    """
    from app.services import registry_service
    from app.utils.version import compare_versions, version_satisfies, get_panel_version
    panel = get_panel_version()
    out = []
    for p in InstalledPlugin.query.all():
        entry = registry_service.get_entry(p.slug)
        if not entry:
            continue
        available = entry.get('version')
        out.append({
            'slug': p.slug,
            'plugin_id': p.id,
            'installed_version': p.version,
            'available_version': available,
            'update_available': compare_versions(available, p.version) > 0,
            'compatible': version_satisfies(
                panel, entry.get('min_panel_version'), entry.get('max_panel_version')
            ),
            'source': entry.get('source'),
        })
    return out


def update_plugin(plugin_id, user_id=None):
    """Update an installed plugin to the registry's version (reinstall in place)."""
    from app.services import registry_service
    plugin = InstalledPlugin.query.get(plugin_id)
    if not plugin:
        raise ValueError('Plugin not found')
    entry = registry_service.get_entry(plugin.slug)
    if not entry:
        raise ValueError(
            f"No registry entry for '{plugin.slug}' — cannot update from the registry."
        )
    _assert_panel_compatible(entry)
    source = (entry.get('source') or '').strip()
    if not source:
        raise ValueError('Registry entry has no source URL.')
    return install_from_url(
        source, user_id=user_id, expected_sha256=entry.get('sha256'), force=True,
    )
