"""Tests for app.services.connection_string codec."""

from datetime import datetime

import pytest

from app.services import connection_string as cs


def test_encode_decode_round_trip():
    expires = datetime(2026, 5, 8, 17, 0, 0)
    s = cs.encode(url='https://panel.example.com', token='sk_reg_abc', expires_at=expires)
    assert s.startswith('sk_conn_v1.')

    decoded = cs.decode(s)
    assert decoded['url'] == 'https://panel.example.com'
    assert decoded['token'] == 'sk_reg_abc'
    assert decoded['expires_at'] == expires


def test_encode_strips_trailing_slash_from_url():
    s = cs.encode(url='https://panel.example.com/', token='t', expires_at=None)
    assert cs.decode(s)['url'] == 'https://panel.example.com'


def test_encode_with_no_expiry():
    s = cs.encode(url='https://panel.example.com', token='t', expires_at=None)
    decoded = cs.decode(s)
    assert decoded['expires_at'] is None


def test_decode_rejects_missing_version_prefix():
    # Plain base64 without our prefix should be rejected — protects
    # agents from silently accepting a future format they don't understand.
    with pytest.raises(ValueError, match='v1'):
        cs.decode('not_a_connection_string')


def test_decode_rejects_unknown_version():
    with pytest.raises(ValueError, match='v1'):
        cs.decode('sk_conn_v2.abc')


def test_decode_rejects_bad_base64():
    with pytest.raises(ValueError, match='base64'):
        cs.decode('sk_conn_v1.!!!not_base64!!!')


def test_decode_rejects_missing_fields():
    import base64
    import json

    raw = json.dumps({'url': 'https://x'}).encode()  # no token
    body = base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    with pytest.raises(ValueError, match='missing url or token'):
        cs.decode('sk_conn_v1.' + body)


def test_encode_rejects_empty_inputs():
    with pytest.raises(ValueError):
        cs.encode(url='', token='t', expires_at=None)
    with pytest.raises(ValueError):
        cs.encode(url='https://x', token='', expires_at=None)


def test_decode_handles_iso_with_z_suffix():
    # encode() emits ISO with a trailing Z. fromisoformat() didn't accept
    # that until 3.11, so the codec strips it explicitly — guard against
    # regressions if anyone touches that branch.
    expires = datetime(2026, 5, 8, 17, 0, 0)
    s = cs.encode(url='https://x', token='t', expires_at=expires)
    assert cs.decode(s)['expires_at'] == expires
