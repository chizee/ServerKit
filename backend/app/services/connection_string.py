"""
Connection string codec.

A connection string is a single pasteable blob the user copies from the
panel and pastes into the agent's pairing wizard. It bundles the panel
URL + a single-use registration token + an optional expiry, replacing
the older flow where the user typed the URL and token into separate
fields.

Format: ``sk_conn_v1.<base64url(json_payload)>``

The version prefix is intentional — if we ever need to add fields the
agent must understand (a different signing scheme, a fleet ID, …) the
agent can refuse to decode unknown versions instead of silently
mis-parsing. Today's payload is deliberately tiny:

    {
      "url": "https://panel.example.com",
      "token": "sk_reg_xxx",
      "expires_at": "2026-05-08T17:00:00Z"  # or null for "never"
    }

Note: the panel never *reads* connection strings — the agent does.
``decode`` is exported only for tests and for symmetry, so the codec
has a single owner.
"""

import base64
import json
from datetime import datetime
from typing import Optional


VERSION_PREFIX = "sk_conn_v1."


def encode(url: str, token: str, expires_at: Optional[datetime]) -> str:
    """Pack the three fields into a single sk_conn_v1.<...> string.

    expires_at=None means the token has no expiry (panel-side feature
    knob — the registration token is single-use either way, so a missing
    expiry is safe).
    """
    if not url or not token:
        raise ValueError("url and token are required")

    payload = {
        "url": url.rstrip("/"),
        "token": token,
        "expires_at": expires_at.isoformat() + "Z" if expires_at else None,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return VERSION_PREFIX + encoded


def decode(s: str) -> dict:
    """Reverse of encode. Raises ValueError on any parse / version error.

    Returns a dict with keys ``url``, ``token``, ``expires_at`` (the
    latter as a datetime or None).
    """
    if not isinstance(s, str) or not s.startswith(VERSION_PREFIX):
        raise ValueError("not a v1 connection string")

    body = s[len(VERSION_PREFIX):]
    # urlsafe_b64decode requires correct padding; we strip it on encode
    # to keep the string short, so re-pad here.
    pad = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + pad)
    except Exception as exc:
        raise ValueError(f"invalid base64: {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid json: {exc}") from exc

    url = data.get("url")
    token = data.get("token")
    if not isinstance(url, str) or not isinstance(token, str):
        raise ValueError("missing url or token")

    expires_raw = data.get("expires_at")
    expires_at: Optional[datetime] = None
    if expires_raw is not None:
        if not isinstance(expires_raw, str):
            raise ValueError("expires_at must be ISO 8601 string or null")
        # Tolerate trailing Z (UTC marker) which datetime.fromisoformat
        # didn't accept until 3.11.
        cleaned = expires_raw[:-1] if expires_raw.endswith("Z") else expires_raw
        try:
            expires_at = datetime.fromisoformat(cleaned)
        except Exception as exc:
            raise ValueError(f"invalid expires_at: {exc}") from exc

    return {"url": url, "token": token, "expires_at": expires_at}
