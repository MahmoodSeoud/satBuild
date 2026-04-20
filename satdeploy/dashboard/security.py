"""Shared-secret + HMAC helpers for dashboard auth.

Threat model (per eng-review L1 + plan-design-review):

- The dashboard runs on a LAN or Tailscale network. Anyone who can reach
  the bind address can GET pages. LAN-binding is NOT the auth layer for
  write endpoints — L1 called that out as untenable.
- State-changing endpoints (``/api/rollback``) require an
  ``X-Satdeploy-Token`` header matching the server's startup secret. The
  secret is printed once on ``satdeploy dashboard`` launch; users share it
  out-of-band (Slack DM, password manager) with teammates who need
  rollback authority.
- Each rollback form also carries an HMAC token scoped to the iteration
  hash so that a leaked secret cannot roll back arbitrary iterations
  without also seeing the detail page (defence in depth). The HMAC is
  keyed on the secret, expires with a 5-minute time bucket.
- Type-to-confirm on the client is the UX anti-footgun; the server also
  verifies the confirmation string exactly so a scripted attacker still
  has to construct the right string.
"""

from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256

_TOKEN_WINDOW_SECONDS = 300  # 5 minutes — matches type-to-confirm prompt shelf-life


def generate_secret() -> str:
    """Return a URL-safe random string for the dashboard startup secret."""
    return secrets.token_urlsafe(24)


def _time_bucket(now: float | None = None) -> int:
    t = now if now is not None else time.time()
    return int(t // _TOKEN_WINDOW_SECONDS)


def sign_rollback(secret: str, iteration_hash: str, *, now: float | None = None) -> str:
    """Return an HMAC token scoped to ``iteration_hash`` and the current time bucket."""
    bucket = _time_bucket(now)
    msg = f"rollback:{iteration_hash}:{bucket}".encode()
    return hmac.new(secret.encode(), msg, sha256).hexdigest()


def verify_rollback(
    secret: str,
    iteration_hash: str,
    token: str,
    *,
    now: float | None = None,
) -> bool:
    """Constant-time verify the HMAC, accepting the current AND previous bucket.

    Two-bucket tolerance handles the common case where the page was
    rendered near a bucket boundary and the user submits a few seconds
    later. The maximum effective token lifetime is ``2 * _TOKEN_WINDOW_SECONDS``.
    """
    now = now if now is not None else time.time()
    for bucket_offset in (0, -1):
        bucket = _time_bucket(now) + bucket_offset
        msg = f"rollback:{iteration_hash}:{bucket}".encode()
        expected = hmac.new(secret.encode(), msg, sha256).hexdigest()
        if hmac.compare_digest(expected, token):
            return True
    return False


def expected_confirm_string(app: str, target: str, iteration_hash: str) -> str:
    """Return the exact string the user must type in the rollback confirm modal."""
    short = iteration_hash[:8]
    return f"rollback {app}@{target} {short}"
