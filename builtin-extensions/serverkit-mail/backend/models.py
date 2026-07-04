"""Data models for the serverkit-mail extension.

These tables are the panel-side **source of truth** for what mail objects
*should* exist; :class:`StalwartService` reconciles them to the running Stalwart
engine best-effort and each row records its own ``sync_state`` / ``sync_error``
so a Stalwart API failure never corrupts panel state (the row simply reports
drift).

Tables are namespaced ``ext_serverkit_mail_*`` (dash → underscore) per the
extension convention, so ``purge_models`` on uninstall drops exactly these.

Registration: importing this module defines the tables on the shared metadata as
a side effect; the manifest's ``models: "models:register"`` then calls
:func:`register` (a no-op passthrough) and the platform runs ``db.create_all()``.

Security: mailbox passwords are **never** persisted here — they live only on the
Stalwart engine. There is no password column on :class:`Mailbox`.
"""
from datetime import datetime

from app import db


class MailDomain(db.Model):
    __tablename__ = 'ext_serverkit_mail_domains'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=False)
    catch_all_target = db.Column(db.String(255), nullable=True)

    # DKIM
    dkim_selector = db.Column(db.String(63), default='serverkit')
    dkim_private_key = db.Column(db.Text, nullable=True)
    dkim_public_key = db.Column(db.Text, nullable=True)

    # DNS deployment ledger
    dns_deployed = db.Column(db.Boolean, default=False)
    dns_last_result = db.Column(db.Text, nullable=True)  # JSON string

    # Reconcile state against the Stalwart engine
    sync_state = db.Column(db.String(20), default='pending')  # pending|synced|error
    sync_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    mailboxes = db.relationship('Mailbox', backref='domain', lazy=True,
                                cascade='all, delete-orphan')
    forwarders = db.relationship('Forwarder', backref='domain', lazy=True,
                                 cascade='all, delete-orphan')

    def to_dict(self):
        import json
        dns_result = None
        if self.dns_last_result:
            try:
                dns_result = json.loads(self.dns_last_result)
            except (ValueError, TypeError):
                dns_result = None
        return {
            'id': self.id,
            'name': self.name,
            'is_active': bool(self.is_active),
            'catch_all_target': self.catch_all_target,
            'dkim_selector': self.dkim_selector,
            'dkim_public_key': self.dkim_public_key,
            'dkim_configured': bool(self.dkim_private_key),
            'dns_deployed': bool(self.dns_deployed),
            'dns_last_result': dns_result,
            'sync_state': self.sync_state,
            'sync_error': self.sync_error,
            'mailboxes_count': len(self.mailboxes) if self.mailboxes else 0,
            'forwarders_count': len(self.forwarders) if self.forwarders else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<MailDomain {self.name}>'


class Mailbox(db.Model):
    __tablename__ = 'ext_serverkit_mail_mailboxes'
    __table_args__ = (
        db.UniqueConstraint('domain_id', 'local_part', name='uq_mail_mailbox_local'),
    )

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer,
                          db.ForeignKey('ext_serverkit_mail_domains.id'),
                          nullable=False, index=True)
    local_part = db.Column(db.String(255), nullable=False)
    quota_mb = db.Column(db.Integer, default=0)  # 0 == unlimited
    is_active = db.Column(db.Boolean, default=True)
    display_name = db.Column(db.String(255), nullable=True)

    # NO password column — passwords live only on Stalwart, never persisted.
    sync_state = db.Column(db.String(20), default='pending')
    sync_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    autoresponder = db.relationship('Autoresponder', backref='mailbox', uselist=False,
                                    lazy=True, cascade='all, delete-orphan')

    @property
    def email(self):
        return f'{self.local_part}@{self.domain.name}' if self.domain else self.local_part

    def to_dict(self):
        return {
            'id': self.id,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'local_part': self.local_part,
            'email': self.email,
            'quota_mb': self.quota_mb,
            'is_active': bool(self.is_active),
            'display_name': self.display_name,
            'sync_state': self.sync_state,
            'sync_error': self.sync_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Mailbox {self.email}>'


class Forwarder(db.Model):
    __tablename__ = 'ext_serverkit_mail_forwarders'

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer,
                          db.ForeignKey('ext_serverkit_mail_domains.id'),
                          nullable=False, index=True)
    source_local_part = db.Column(db.String(255), nullable=False)
    destination = db.Column(db.Text, nullable=False)  # may be an external address
    keep_copy = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    sync_state = db.Column(db.String(20), default='pending')
    sync_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def source(self):
        return f'{self.source_local_part}@{self.domain.name}' if self.domain else self.source_local_part

    def to_dict(self):
        return {
            'id': self.id,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'source_local_part': self.source_local_part,
            'source': self.source,
            'destination': self.destination,
            'keep_copy': bool(self.keep_copy),
            'is_active': bool(self.is_active),
            'sync_state': self.sync_state,
            'sync_error': self.sync_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Forwarder {self.source} -> {self.destination}>'


class Autoresponder(db.Model):
    __tablename__ = 'ext_serverkit_mail_autoresponders'

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer,
                           db.ForeignKey('ext_serverkit_mail_mailboxes.id'),
                           nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=False)
    subject = db.Column(db.String(500), nullable=True)
    body = db.Column(db.Text, nullable=True)
    start_at = db.Column(db.DateTime, nullable=True)
    end_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'mailbox_id': self.mailbox_id,
            'enabled': bool(self.enabled),
            'subject': self.subject,
            'body': self.body,
            'start_at': self.start_at.isoformat() if self.start_at else None,
            'end_at': self.end_at.isoformat() if self.end_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Autoresponder mailbox={self.mailbox_id} enabled={self.enabled}>'


class PreflightResult(db.Model):
    __tablename__ = 'ext_serverkit_mail_preflight'

    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(255), nullable=True, index=True)
    server_ip = db.Column(db.String(64), nullable=True)

    ptr_ok = db.Column(db.Boolean, default=False)
    ptr_value = db.Column(db.String(255), nullable=True)
    port25_ok = db.Column(db.Boolean, default=False)
    rbl_ok = db.Column(db.Boolean, default=False)
    rbl_hits = db.Column(db.Text, nullable=True)  # JSON list
    ports_ok = db.Column(db.Boolean, default=False)

    passed = db.Column(db.Boolean, default=False)
    detail = db.Column(db.Text, nullable=True)  # JSON object

    checked_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        rbl_hits = []
        if self.rbl_hits:
            try:
                rbl_hits = json.loads(self.rbl_hits)
            except (ValueError, TypeError):
                rbl_hits = []
        detail = None
        if self.detail:
            try:
                detail = json.loads(self.detail)
            except (ValueError, TypeError):
                detail = None
        return {
            'id': self.id,
            'hostname': self.hostname,
            'server_ip': self.server_ip,
            'ptr_ok': bool(self.ptr_ok),
            'ptr_value': self.ptr_value,
            'port25_ok': bool(self.port25_ok),
            'rbl_ok': bool(self.rbl_ok),
            'rbl_hits': rbl_hits,
            'ports_ok': bool(self.ports_ok),
            'passed': bool(self.passed),
            'detail': detail,
            'checked_at': self.checked_at.isoformat() if self.checked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<PreflightResult {self.hostname} passed={self.passed}>'


def register(db):  # noqa: A002 — signature dictated by the platform (fn(db))
    """No-op passthrough required by the manifest ``models: "models:register"``.

    Importing this module already registered the tables on the metadata; the
    platform calls this then runs ``db.create_all()``. Returns ``None``.
    """
    return None
