"""Domain-registrar portfolio service.

Connects to registrar APIs (GoDaddy today; Namecheap is a planned addition) to
answer the question "what domains do I own and when do they expire?" — the data
that powers the Connections → Registrars cards and the Domains-page portfolio.

Credentials live on RegistrarConnection rows, Fernet-encrypted. The public
methods return plain dicts so the API layer can jsonify them directly.
"""

import logging
from datetime import datetime, timezone

import requests

from app import db
from app.models.registrar_connection import RegistrarConnection
from app.utils.crypto import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)


class RegistrarService:
    # Only providers we can fully read are listed here; the connect form is
    # gated on this. Namecheap (XML API + IP allow-listing) is intentionally
    # left out until implemented, and shown as "coming soon" in the catalog.
    SUPPORTED = {
        'godaddy': {'name': 'GoDaddy', 'fields': ['api_key', 'api_secret']},
        'namecheap': {'name': 'Namecheap', 'fields': ['api_key', 'username', 'client_ip']},
    }

    GODADDY_BASE = 'https://api.godaddy.com/v1'
    NAMECHEAP_BASE = 'https://api.namecheap.com/xml.response'
    NAMECHEAP_NS = {'nc': 'http://api.namecheap.com/xml.response'}

    # --- Connections (CRUD) ---

    @staticmethod
    def list_connections():
        return RegistrarConnection.query.order_by(RegistrarConnection.created_at.desc()).all()

    @staticmethod
    def get_connection(cid):
        return RegistrarConnection.query.get(cid)

    @classmethod
    def add_connection(cls, data, user_id=None):
        provider = (data.get('provider') or '').lower().strip()
        if provider not in cls.SUPPORTED:
            raise ValueError(f'Unsupported registrar: {provider or "(none)"}')
        api_key = (data.get('api_key') or '').strip()
        if not api_key:
            raise ValueError('api_key is required')

        conn = RegistrarConnection(
            provider=provider,
            name=(data.get('name') or '').strip() or cls.SUPPORTED[provider]['name'],
            api_key_encrypted=encrypt_secret(api_key),
            user_id=user_id,
        )
        if provider == 'godaddy':
            api_secret = (data.get('api_secret') or '').strip()
            if not api_secret:
                raise ValueError('api_secret is required')
            conn.api_secret_encrypted = encrypt_secret(api_secret)
        elif provider == 'namecheap':
            username = (data.get('username') or '').strip()
            client_ip = (data.get('client_ip') or '').strip()
            if not username or not client_ip:
                raise ValueError('username and client_ip are required')
            conn.config = {'username': username, 'client_ip': client_ip}

        db.session.add(conn)
        db.session.commit()
        return conn

    @staticmethod
    def delete_connection(cid):
        conn = RegistrarConnection.query.get(cid)
        if not conn:
            return False
        db.session.delete(conn)
        db.session.commit()
        return True

    @staticmethod
    def _creds(conn):
        return decrypt_secret(conn.api_key_encrypted), decrypt_secret(conn.api_secret_encrypted)

    @staticmethod
    def _api_key(conn):
        return decrypt_secret(conn.api_key_encrypted) if conn.api_key_encrypted else ''

    # --- GoDaddy ---

    @classmethod
    def _godaddy_headers(cls, conn):
        key, secret = cls._creds(conn)
        return {'Authorization': f'sso-key {key}:{secret}', 'Accept': 'application/json'}

    @classmethod
    def _godaddy_list_domains(cls, conn):
        resp = requests.get(
            f'{cls.GODADDY_BASE}/domains',
            params={'limit': 1000, 'statuses': 'ACTIVE'},
            headers=cls._godaddy_headers(conn),
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json() if isinstance(resp.json(), list) else []
        return [
            cls._normalize_domain(conn, {
                'domain': d.get('domain'),
                'status': d.get('status'),
                'expires': d.get('expires'),
                'auto_renew': d.get('renewAuto'),
                'locked': d.get('locked'),
                'nameservers': d.get('nameServers'),
                'created': d.get('createdAt'),
            })
            for d in rows
        ]

    # --- Namecheap (XML API; the calling server IP must be allow-listed) ---

    @classmethod
    def _namecheap_params(cls, conn, command):
        cfg = conn.config
        return {
            'ApiUser': cfg.get('username', ''),
            'ApiKey': cls._api_key(conn),
            'UserName': cfg.get('username', ''),
            'ClientIp': cfg.get('client_ip', ''),
            'Command': command,
        }

    @staticmethod
    def _namecheap_date(value):
        # Namecheap returns "MM/DD/YYYY"; normalize to ISO "YYYY-MM-DD".
        try:
            m, d, y = (value or '').split('/')
            return f'{int(y):04d}-{int(m):02d}-{int(d):02d}'
        except Exception:
            return None

    @classmethod
    def _namecheap_test(cls, conn):
        import xml.etree.ElementTree as ET
        try:
            params = cls._namecheap_params(conn, 'namecheap.domains.getList')
            params['PageSize'] = 1
            resp = requests.get(cls.NAMECHEAP_BASE, params=params, timeout=15)
            root = ET.fromstring(resp.text)
            if root.get('Status') == 'OK':
                return {'success': True, 'message': 'Namecheap connection works'}
            err = root.find('.//nc:Error', cls.NAMECHEAP_NS)
            msg = (err.text if err is not None and err.text else
                   'Check the API key, username, and that this server IP is allow-listed in Namecheap.')
            return {'success': False, 'error': msg}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _namecheap_list_domains(cls, conn):
        import xml.etree.ElementTree as ET
        params = cls._namecheap_params(conn, 'namecheap.domains.getList')
        params['PageSize'] = 100
        resp = requests.get(cls.NAMECHEAP_BASE, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        if root.get('Status') != 'OK':
            err = root.find('.//nc:Error', cls.NAMECHEAP_NS)
            raise RuntimeError(err.text if err is not None and err.text else 'Namecheap API error')
        out = []
        for d in root.findall('.//nc:Domain', cls.NAMECHEAP_NS):
            out.append(cls._normalize_domain(conn, {
                'domain': d.get('Name'),
                'status': 'expired' if d.get('IsExpired') == 'true' else 'active',
                'expires': cls._namecheap_date(d.get('Expires')),
                'auto_renew': d.get('AutoRenew') == 'true',
                'locked': d.get('IsLocked') == 'true',
                'nameservers': None,
            }))
        return out

    # --- Public capability methods ---

    @classmethod
    def test_connection(cls, conn):
        try:
            if conn.provider == 'godaddy':
                resp = requests.get(
                    f'{cls.GODADDY_BASE}/domains', params={'limit': 1},
                    headers=cls._godaddy_headers(conn), timeout=15,
                )
                if resp.status_code == 200:
                    return {'success': True, 'message': 'GoDaddy connection works'}
                if resp.status_code in (401, 403):
                    return {'success': False, 'error': 'Access denied — check the API key/secret (must be a Production key, not OTE).'}
                return {'success': False, 'error': f'GoDaddy returned HTTP {resp.status_code}'}
            if conn.provider == 'namecheap':
                return cls._namecheap_test(conn)
            return {'success': False, 'error': f'Unsupported registrar: {conn.provider}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def list_domains(cls, conn):
        if conn.provider == 'godaddy':
            return cls._godaddy_list_domains(conn)
        if conn.provider == 'namecheap':
            return cls._namecheap_list_domains(conn)
        return []

    @classmethod
    def list_all_domains(cls):
        """Aggregate every domain across all connected registrars, soonest-to-expire first."""
        domains = []
        for conn in cls.list_connections():
            try:
                domains.extend(cls.list_domains(conn))
            except Exception as e:
                logger.warning(f'Registrar {conn.id} ({conn.provider}) domain list failed: {e}')
        domains.sort(key=lambda d: (d.get('days_until_expiry') is None, d.get('days_until_expiry') if d.get('days_until_expiry') is not None else 0))
        return domains

    @classmethod
    def sync_now(cls):
        """Refresh the portfolio and stamp last_synced_at on every connection."""
        domains = cls.list_all_domains()
        now = datetime.utcnow()
        conns = cls.list_connections()
        for conn in conns:
            conn.last_synced_at = now
            # Surface the per-account domain count as the card subtitle.
            count = sum(1 for d in domains if d.get('connection_id') == conn.id)
            conn.account_label = f'{count} domain' + ('' if count == 1 else 's')
        db.session.commit()
        return domains

    # --- Helpers ---

    @staticmethod
    def _normalize_domain(conn, d):
        expires_raw = d.get('expires')
        expires_at = None
        days = None
        if expires_raw:
            try:
                dt = datetime.fromisoformat(str(expires_raw).replace('Z', '+00:00'))
                expires_at = dt
                if dt.tzinfo:
                    days = (dt - datetime.now(timezone.utc)).days
                else:
                    days = (dt - datetime.utcnow()).days
            except Exception:
                pass
        return {
            'domain': d.get('domain'),
            'registrar': conn.provider,
            'registrar_name': conn.name or conn.provider,
            'connection_id': conn.id,
            'status': d.get('status'),
            'expires_at': expires_at.isoformat() if expires_at else None,
            'days_until_expiry': days,
            'auto_renew': d.get('auto_renew'),
            'locked': d.get('locked'),
            'nameservers': d.get('nameservers') or [],
        }
