"""DKIM keygen + mail DNS record deployment (serverkit-mail extension).

Owns the DNS side of standing up a deliverable domain:

* :meth:`generate_dkim` — mint an RSA-2048 DKIM keypair (via ``cryptography``),
  store the PEM private key + base64 DER public key on the :class:`MailDomain`
  row, and expose the public half as a DKIM TXT value.
* :meth:`build_records` — the **pure, testable** record builder: given a domain
  row + optional server IP, return the exact list of records
  (MX/SPF/DKIM/DMARC/A) the domain needs. No side effects.
* :meth:`deploy_dns` — push those records through the core
  :class:`DNSProviderService` (``source='mail'`` for the ownership ledger),
  recording per-record results on the row. When no connected provider manages
  the zone, degrade to manual instructions.
* :meth:`dns_instructions` — the record list for the UI, provider or not.
* :meth:`request_cert` — best-effort Let's Encrypt cert for the mail hostname.

Best-effort throughout; the provider/SSL layers are imported lazily so a missing
dependency never breaks import, and nothing here raises to the caller.
"""
import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_SELECTOR = 'serverkit'
DMARC_POLICY = 'quarantine'


class DkimDnsService:
    """Stateless DKIM + mail-DNS orchestration."""

    # ---------- DKIM key generation ----------

    @classmethod
    def generate_dkim(cls, domain_row):
        """Generate an RSA-2048 DKIM keypair and store it on *domain_row*.

        Returns ``{success, selector, dkim_value}`` (or an error dict). The
        private key is stored as PEM, the public key as base64 DER, and the
        DKIM TXT value ``v=DKIM1; k=rsa; p=<b64>`` is returned for display.
        """
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError as e:
            return {'success': False, 'error': f'cryptography is required for DKIM: {e}'}
        try:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            private_pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode('ascii')
            public_der = key.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            public_b64 = base64.b64encode(public_der).decode('ascii')
        except Exception as e:  # noqa: BLE001
            return {'success': False, 'error': f'DKIM key generation failed: {e}'}

        selector = domain_row.dkim_selector or DEFAULT_SELECTOR
        try:
            from app import db
            domain_row.dkim_selector = selector
            domain_row.dkim_private_key = private_pem
            domain_row.dkim_public_key = public_b64
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass
            return {'success': False, 'error': f'Could not store DKIM key: {e}'}

        return {
            'success': True,
            'selector': selector,
            'dkim_value': cls._dkim_txt_value(public_b64),
        }

    @staticmethod
    def _dkim_txt_value(public_b64):
        return f'v=DKIM1; k=rsa; p={public_b64}'

    # ---------- pure record builder (testable) ----------

    @classmethod
    def build_records(cls, domain_row, server_ip=None):
        """Return the list of DNS records *domain_row* needs. Pure, no I/O.

        Each record is ``{type, name, value}`` (plus ``priority`` for MX). The
        DKIM record is included only once a key has been generated.
        """
        name = (domain_row.name or '').strip().lower().rstrip('.')
        selector = domain_row.dkim_selector or DEFAULT_SELECTOR
        mail_host = f'mail.{name}'
        records = [
            {'type': 'MX', 'name': name, 'value': f'10 {mail_host}', 'priority': 10},
            {'type': 'TXT', 'name': name, 'value': 'v=spf1 mx a ~all'},
            {'type': 'TXT', 'name': f'_dmarc.{name}',
             'value': f'v=DMARC1; p={DMARC_POLICY}; rua=mailto:postmaster@{name}'},
        ]
        if domain_row.dkim_public_key:
            records.append({
                'type': 'TXT',
                'name': f'{selector}._domainkey.{name}',
                'value': cls._dkim_txt_value(domain_row.dkim_public_key),
            })
        if server_ip:
            records.append({'type': 'A', 'name': mail_host, 'value': server_ip})
        return records

    # ---------- DNS deployment ----------

    @classmethod
    def deploy_dns(cls, domain_id, server_ip=None):
        """Deploy the domain's mail records through a connected DNS provider.

        Records the per-record result on ``MailDomain.dns_last_result`` and sets
        ``dns_deployed``. When no connected provider manages the zone, returns
        ``{success: True, deployed: False, manual: True, records: [...]}`` so the
        caller can show manual instructions. Never raises.
        """
        try:
            from app import db
            from .models import MailDomain
        except Exception as e:  # noqa: BLE001
            return {'success': False, 'error': f'Model import failed: {e}'}

        domain_row = MailDomain.query.get(domain_id)
        if not domain_row:
            return {'success': False, 'error': 'Domain not found'}

        records = cls.build_records(domain_row, server_ip=server_ip)

        try:
            from app.services.dns_provider_service import DNSProviderService
        except Exception as e:  # noqa: BLE001
            return {'success': True, 'deployed': False, 'manual': True,
                    'records': records, 'note': f'DNS provider layer unavailable: {e}'}

        try:
            config, zone = DNSProviderService.find_zone_for_domain(domain_row.name)
        except Exception as e:  # noqa: BLE001
            return {'success': True, 'deployed': False, 'manual': True,
                    'records': records, 'note': f'Provider lookup failed: {e}'}

        if not config or not zone:
            return {'success': True, 'deployed': False, 'manual': True,
                    'records': records,
                    'note': f'No connected DNS provider manages {domain_row.name}.'}

        results = {}
        all_ok = True
        for rec in records:
            key = f"{rec['type'].lower()}:{rec['name']}"
            try:
                res = DNSProviderService.set_record(
                    config.id, zone['id'], rec['type'], rec['name'], rec['value'],
                    priority=rec.get('priority'), source='mail')
            except Exception as e:  # noqa: BLE001
                res = {'success': False, 'error': str(e)}
            results[key] = {'success': bool(res.get('success')),
                            'error': res.get('error'),
                            'record': rec}
            all_ok = all_ok and bool(res.get('success'))

        payload = {'provider': config.name, 'zone': zone.get('name'),
                   'results': results, 'all_ok': all_ok}
        try:
            domain_row.dns_last_result = json.dumps(payload)
            domain_row.dns_deployed = all_ok
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning('Could not persist DNS deploy result: %s', e)

        cls._notify_deployed(domain_row.name, all_ok)
        return {'success': all_ok, 'deployed': all_ok, 'manual': False,
                'provider': config.name, 'zone': zone.get('name'),
                'results': results, 'records': records}

    @staticmethod
    def _notify_deployed(domain, all_ok):
        try:
            from app.plugins_sdk import notify
            notify.send('mail.dns_deployed', to='admins',
                        data={'domain': domain, 'all_ok': all_ok}, category='system')
        except Exception as e:  # noqa: BLE001
            logger.debug('mail.dns_deployed notify failed: %s', e)

    @classmethod
    def dns_instructions(cls, domain_row, server_ip=None):
        """Return the records the operator must publish (for the UI), plus the
        current deployment status. Provider-independent."""
        deployed = bool(getattr(domain_row, 'dns_deployed', False))
        last_result = None
        if getattr(domain_row, 'dns_last_result', None):
            try:
                last_result = json.loads(domain_row.dns_last_result)
            except (ValueError, TypeError):
                last_result = None
        return {
            'domain': domain_row.name,
            'records': cls.build_records(domain_row, server_ip=server_ip),
            'dns_deployed': deployed,
            'dns_last_result': last_result,
            'dkim_configured': bool(getattr(domain_row, 'dkim_private_key', None)),
        }

    # ---------- TLS certificate ----------

    @classmethod
    def request_cert(cls, hostname):
        """Best-effort Let's Encrypt cert for ``mail.<hostname>``. Linux-only."""
        if os.name == 'nt':
            return {'success': False, 'skipped': True,
                    'error': 'Certificate issuance is not supported on this OS.'}
        hostname = (hostname or '').strip().lower().rstrip('.')
        if not hostname:
            return {'success': False, 'error': 'A hostname is required'}
        try:
            from app.services.ssl_service import SSLService
        except Exception as e:  # noqa: BLE001
            return {'success': False, 'error': f'SSL service unavailable: {e}'}
        email = f'postmaster@{hostname.split(".", 1)[-1]}' if '.' in hostname else f'postmaster@{hostname}'
        try:
            result = SSLService.obtain_certificate([hostname], email, use_nginx=True)
        except Exception as e:  # noqa: BLE001
            return {'success': False, 'error': f'Certificate request failed: {e}'}
        return result
