"""Embedded agent client — lets THIS panel act as a worker of a master panel.

Instead of installing the standalone Go agent (serverkit-agent), a linked
panel runs this client: it registers with the master (one REST call), then
keeps an HTTP long-poll session to the master's agent gateway
(/api/v1/agent/connect|poll|result) — the same protocol and HMAC auth the
Go agent uses. Incoming commands are dispatched to this panel's OWN local
services (DockerService, filesystem), so the master can deploy apps here
exactly as if the Go agent were installed.

Transport note: the long-poll fallback intentionally has no streaming
(live logs / terminal); the master degrades those to "view recent only".
"""
import base64
import hashlib
import hmac
import logging
import os
import platform
import secrets
import socket
import threading
import time

import requests

from app import db
from app.models.linked_panel import LinkedPanelConfig

logger = logging.getLogger(__name__)

# Version reported to the master as User-Agent (ServerKit-Agent/<version>).
AGENT_VERSION = 'panel-embedded-1.0'

# Root prefixes the master is allowed to write files under. Template
# installs target <apps_root>/<app-name>/..., matching the local layout.
DEFAULT_ALLOWED_WRITE_ROOTS = ('/var/serverkit/apps', '/etc/serverkit')

POLL_TIMEOUT_S = 35          # slightly above the master's 25s long-poll
RECONNECT_DELAY_S = 10
CONNECT_TIMEOUT_S = 15

_client = None


class EmbeddedAgentClient:
    """Long-poll agent-protocol client bound to one LinkedPanelConfig row."""

    def __init__(self, app):
        self.app = app
        self.running = False
        self.session_token = None
        self.last_error = None
        self.connected_at = None
        self.last_heartbeat_at = None
        self._thread = None
        self._send_state = True  # ship system_info+capabilities on next poll

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='linked-panel-agent')
        self._thread.start()
        logger.info('Linked-panel embedded agent started')

    def stop(self):
        self.running = False
        token, self.session_token = self.session_token, None
        if token:
            try:
                cfg = self._load_config()
                if cfg:
                    requests.post(
                        f'{cfg.master_url}/api/v1/agent/disconnect',
                        headers={'X-Session-Token': token},
                        timeout=CONNECT_TIMEOUT_S,
                    )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main loop: connect → poll → (reconnect on failure)
    # ------------------------------------------------------------------
    def _run(self):
        while self.running:
            try:
                cfg = self._load_config()
                if not cfg or not cfg.enabled:
                    self.last_error = 'Link disabled or removed'
                    return
                self._connect(cfg)
                self._poll_loop(cfg)
            except Exception as exc:  # pragma: no cover - defensive
                self.last_error = str(exc)
                logger.warning('Linked-panel agent error: %s', exc)
            self.session_token = None
            self.connected_at = None
            if self.running:
                time.sleep(RECONNECT_DELAY_S)

    def _load_config(self):
        with self.app.app_context():
            cfg = LinkedPanelConfig.query.first()
            if not cfg:
                return None
            # Detach the values we need from the session-bound object.
            return _ConfigSnapshot(cfg)

    # ------------------------------------------------------------------
    # Protocol: HMAC auth connect (mirrors agent_poll.connect expectations)
    # ------------------------------------------------------------------
    def _connect(self, cfg):
        timestamp = int(time.time() * 1000)
        nonce = secrets.token_hex(16)
        message = f'{cfg.agent_id}:{timestamp}:{nonce}'
        signature = hmac.new(
            cfg.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        resp = requests.post(
            f'{cfg.master_url}/api/v1/agent/connect',
            json={
                'agent_id': cfg.agent_id,
                'api_key_prefix': cfg.api_key_prefix,
                'signature': signature,
                'timestamp': timestamp,
                'nonce': nonce,
            },
            headers={'User-Agent': f'ServerKit-Agent/{AGENT_VERSION}'},
            timeout=CONNECT_TIMEOUT_S,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f'connect failed ({resp.status_code}): {resp.text[:200]}')
        data = resp.json()
        if not data.get('success'):
            raise RuntimeError(f"connect rejected: {data.get('error')}")
        self.session_token = data['session_token']
        self.connected_at = time.time()
        self.last_error = None
        self._send_state = True
        logger.info('Linked-panel agent connected to %s', cfg.master_url)

    def _poll_loop(self, cfg):
        while self.running:
            body = {'metrics': collect_metrics()}
            if self._send_state:
                body['system_info'] = collect_system_info()
                body['capabilities'] = {
                    'capabilities': {
                        'docker': True,
                        'compose': True,
                        'files': True,
                        'metrics': True,
                    },
                    'platform': 'linux' if os.name == 'posix' else os.name,
                }
            resp = requests.post(
                f'{cfg.master_url}/api/v1/agent/poll',
                json=body,
                headers={'X-Session-Token': self.session_token},
                timeout=POLL_TIMEOUT_S,
            )
            if resp.status_code == 401:
                raise RuntimeError('session expired — reconnecting')
            resp.raise_for_status()
            self._send_state = False
            self.last_heartbeat_at = time.time()
            for command in (resp.json().get('commands') or []):
                # Long-running commands (compose build) must not block the
                # heartbeat loop — dispatch each on its own thread.
                threading.Thread(
                    target=self._dispatch,
                    args=(cfg, command),
                    daemon=True,
                    name=f'linked-panel-cmd-{command.get("id", "?")[:8]}',
                ).start()

    # ------------------------------------------------------------------
    # Command dispatch → this panel's own local services
    # ------------------------------------------------------------------
    def _dispatch(self, cfg, command):
        command_id = command.get('id')
        action = command.get('action')
        params = command.get('params') or {}
        started = time.time()
        try:
            handler = ACTION_HANDLERS.get(action)
            if not handler:
                raise RuntimeError(f'Unsupported action: {action}')
            data = handler(params)
            result = {
                'command_id': command_id,
                'success': True,
                'data': data,
                'error': None,
                'duration': time.time() - started,
            }
        except Exception as exc:
            logger.warning('Linked-panel command %s (%s) failed: %s',
                           command_id, action, exc)
            result = {
                'command_id': command_id,
                'success': False,
                'data': None,
                'error': str(exc),
                'duration': time.time() - started,
            }
        try:
            requests.post(
                f'{cfg.master_url}/api/v1/agent/result',
                json=result,
                headers={'X-Session-Token': self.session_token},
                timeout=CONNECT_TIMEOUT_S,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning('Linked-panel result post failed: %s', exc)


class _ConfigSnapshot:
    """Plain-data copy of a LinkedPanelConfig row (detached from the session)."""

    def __init__(self, cfg: LinkedPanelConfig):
        self.master_url = cfg.master_url.rstrip('/')
        self.agent_id = cfg.agent_id
        self.api_key_prefix = cfg.api_key_prefix
        self.api_secret = cfg.get_api_secret()
        self.enabled = cfg.enabled


# ---------------------------------------------------------------------------
# Command handlers (agent action → local execution)
# ---------------------------------------------------------------------------

def _allowed_write_roots():
    raw = os.environ.get('LINKED_PANEL_ALLOWED_WRITE_ROOTS', '')
    roots = tuple(r.strip() for r in raw.split(',') if r.strip())
    return roots or DEFAULT_ALLOWED_WRITE_ROOTS


def handle_file_write(params):
    path = params.get('path') or ''
    if not os.path.isabs(path):
        raise RuntimeError(f'file:write requires an absolute path, got {path!r}')
    real = os.path.realpath(path)
    if not any(real == os.path.realpath(root)
               or real.startswith(os.path.realpath(root) + os.sep)
               for root in _allowed_write_roots()):
        raise RuntimeError(f'file:write path outside allowed roots: {path}')
    content = base64.b64decode(params.get('content') or b'').decode('utf-8')
    mode = int(params.get('mode', 0o644))
    if params.get('create_dirs', True):
        os.makedirs(os.path.dirname(real), exist_ok=True)
    with open(real, 'w') as handle:
        handle.write(content)
    os.chmod(real, mode)
    return {'path': real, 'size': len(content)}


def handle_compose_up(params):
    from app.services.docker_service import DockerService
    project_path = params.get('project_path')
    if not project_path:
        raise RuntimeError('docker:compose:up requires project_path')
    result = DockerService.compose_up(
        project_path,
        detach=bool(params.get('detach', True)),
        build=bool(params.get('build', False)),
    )
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'docker compose up failed')
    return result


def handle_compose_ps(params):
    from app.services.docker_service import DockerService
    project_path = params.get('project_path')
    if not project_path:
        raise RuntimeError('docker:compose:ps requires project_path')
    return DockerService.compose_ps(project_path)


def handle_compose_logs(params):
    from app.services.docker_service import DockerService
    project_path = params.get('project_path')
    if not project_path:
        raise RuntimeError('docker:compose:logs requires project_path')
    result = DockerService.compose_logs(
        project_path,
        service=params.get('service') or None,
        tail=int(params.get('tail', 100)),
    )
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'docker compose logs failed')
    return result


def handle_system_info(_params):
    return collect_system_info()


def handle_system_metrics(_params):
    return collect_metrics()


ACTION_HANDLERS = {
    'file:write': handle_file_write,
    'docker:compose:up': handle_compose_up,
    'docker:compose:ps': handle_compose_ps,
    'docker:compose:logs': handle_compose_logs,
    'system:info': handle_system_info,
    'system:metrics': handle_system_metrics,
}


# ---------------------------------------------------------------------------
# Host telemetry
# ---------------------------------------------------------------------------

def collect_system_info():
    import psutil
    return {
        'hostname': socket.gethostname(),
        'os': 'linux' if os.name == 'posix' else os.name,
        'platform': platform.system().lower(),
        'platform_version': platform.release(),
        'architecture': platform.machine(),
        'cpu_cores': psutil.cpu_count(),
        'total_memory': psutil.virtual_memory().total,
        'total_disk': psutil.disk_usage('/').total,
    }


def collect_metrics():
    import psutil
    return {
        'cpu_percent': psutil.cpu_percent(interval=None),
        'memory_percent': psutil.virtual_memory().percent,
        'memory_used': psutil.virtual_memory().used,
        'disk_percent': psutil.disk_usage('/').percent,
        'disk_used': psutil.disk_usage('/').used,
    }


# ---------------------------------------------------------------------------
# Singleton management (mirrors the job-consumer pattern)
# ---------------------------------------------------------------------------

def get_client():
    return _client


def start_embedded_agent(app):
    """Start the embedded agent if this panel is linked. Skipped under testing."""
    global _client
    if _client is not None:
        return _client
    if app.config.get('ENV') == 'testing' or app.config.get('TESTING'):
        return None
    client = EmbeddedAgentClient(app)
    client.start()
    _client = client
    return client


def stop_embedded_agent():
    global _client
    if _client is not None:
        _client.stop()
        _client = None
