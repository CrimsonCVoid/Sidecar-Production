"""FastAPI dependency injection: settings, Supabase client, and auth principals.

This module gained the auth layer in the 2026-04-21 security audit (C-6).
Prior to that, every route was unauthenticated — any caller on the network
could read/write labels, pipe DSMs, and trigger compute for any sample_id.

Two authentication paths are accepted:

1. ``X-Internal-API-Key`` header matching ``settings.internal_api_key`` —
   meant for server-to-server calls from the Next.js proxy. The proxy is
   trusted to have already resolved user → project → sample ownership.

2. ``Authorization: Bearer <jwt>`` — a Supabase-signed JWT (HS256, audience
   ``authenticated``). Verified against ``settings.supabase_jwt_secret``.
   The ``sub`` claim becomes the principal's user_id. Browser-direct calls
   land here.

For endpoints that operate on a specific ``sample_id``, the user-JWT path
additionally requires ownership via the projects table — see
``verify_sample_access`` below.

Dev escape hatch: if ``settings.dev_allow_unauth`` is true AND the request
is coming from localhost, auth is bypassed (principal becomes ``internal``).
This keeps the labeling-only frontend in ``./frontend`` working without
surgery during local dev. NEVER enable in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import Depends, Header, HTTPException, Request
from supabase import Client, create_client

from .config import Settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings + Supabase client
# ---------------------------------------------------------------------------


@lru_cache
def get_settings() -> Settings:
    """Return the application settings singleton.

    Uses ``@lru_cache`` so the Settings object (and the .env file read)
    happens exactly once per process.
    """
    return Settings()


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    """Create a Supabase client using the service-role key.

    The client is constructed on each call because the ``Depends()`` chain
    is evaluated per-request.  The underlying HTTP connection pool in httpx
    handles connection reuse automatically.

    NOTE: This client bypasses Row-Level Security. Every route that takes
    a user-supplied identifier must validate ownership BEFORE querying — see
    ``verify_sample_access`` for the sample-scoped check.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


# ---------------------------------------------------------------------------
# Principals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The authenticated caller of a request.

    ``kind`` is either ``"internal"`` (server-to-server via shared secret) or
    ``"user"`` (browser-direct via Supabase JWT). ``user_id`` is populated
    for user principals only; it's ``None`` for internal calls.
    """

    kind: Literal["internal", "user"]
    user_id: str | None


def _is_localhost_request(request: Request) -> bool:
    """True when the request originated from the loopback interface.

    Used only to gate the ``dev_allow_unauth`` escape hatch.  ``request.client``
    can be ``None`` (e.g. under TestClient), in which case we treat it as
    non-local.
    """
    host = getattr(request.client, "host", None) if request.client else None
    return host in {"127.0.0.1", "::1", "localhost"}


def _verify_supabase_jwt(token: str, settings: Settings) -> str:
    """Decode a Supabase HS256 JWT and return the ``sub`` claim.

    Raises ``HTTPException(401)`` for any signature, expiry, audience, or
    shape failure.  The exception message is intentionally opaque so we don't
    leak which validation step failed.
    """
    if not settings.supabase_jwt_secret:
        log.error("supabase_jwt_secret not configured — cannot verify JWTs")
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token") from None

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(status_code=401, detail="Invalid token") from None
    return sub


def require_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-API-Key"),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Resolve the request's principal (internal shared secret or Supabase JWT).

    Precedence:
      1. ``X-Internal-API-Key`` matching the configured secret → internal principal
      2. ``dev_allow_unauth`` is set AND the request came from loopback → internal
         (runs before JWT so a browser's stale session token can't trip a 503
          when supabase_jwt_secret is unset on a dev box)
      3. ``Authorization: Bearer <jwt>`` with a valid Supabase JWT → user principal
      4. Otherwise → 401

    Explicitly: an *invalid* internal key header is still checked, but it
    doesn't short-circuit; we fall through to JWT so misconfigured callers
    aren't rejected immediately on what might be a typo'd debug header. A
    *valid* key wins over a JWT if both are present.
    """
    # 1. Internal shared secret
    if (
        settings.internal_api_key
        and x_internal_api_key
        and _ct_eq(x_internal_api_key, settings.internal_api_key)
    ):
        return Principal(kind="internal", user_id=None)

    # 2. Dev escape hatch — loopback only. Runs BEFORE the JWT path so a
    #    browser that happens to attach a Supabase session token (from a
    #    logged-in dashboard tab) doesn't force JWT verification when the
    #    dev box hasn't configured supabase_jwt_secret. In prod with
    #    dev_allow_unauth=false, this branch is dead and JWT verification
    #    is mandatory.
    if settings.dev_allow_unauth and _is_localhost_request(request):
        log.warning(
            "DEV_ALLOW_UNAUTH bypassing auth for %s %s from %s",
            request.method,
            request.url.path,
            request.client.host if request.client else "?",
        )
        return Principal(kind="internal", user_id=None)

    # 3. Supabase JWT
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            user_id = _verify_supabase_jwt(token, settings)
            return Principal(kind="user", user_id=user_id)

    raise HTTPException(status_code=401, detail="Authentication required")


def _ct_eq(a: str, b: str) -> bool:
    """Constant-time string compare so a mismatched secret can't be timed."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


# ---------------------------------------------------------------------------
# Sample-scoped authorization
# ---------------------------------------------------------------------------


def verify_sample_access(
    principal: Principal,
    sample_id: str,
    supabase: Client,
) -> None:
    """Ensure the principal is allowed to act on ``sample_id``.

    Trust model:
      - Internal principals (Next.js proxy) are pre-validated by the Next.js
        API route's ``getOrgContext`` / ``auth.getUser`` checks. We trust the
        proxy and return immediately.
      - User principals must own the project whose id matches sample_id, or
        be a member of that project's organization. If no project row exists
        for the sample_id, we deny — orphan samples (e.g. from the labeling
        ``/api/solar/ingest`` flow that haven't been linked to a project)
        can only be accessed via the internal/proxy path.

    Raises:
      ``HTTPException(403)`` on denial. Intentionally returns the same status
      for "no project" and "not a member" so the endpoint doesn't serve as
      a sample-existence oracle.
    """
    if principal.kind == "internal":
        return

    if not principal.user_id:
        # Belt and suspenders — a user principal without a user_id is malformed
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        result = (
            supabase.table("projects")
            .select("user_id, organization_id")
            .eq("id", sample_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        log.exception("projects lookup failed in verify_sample_access")
        raise HTTPException(status_code=403, detail="Forbidden") from None

    row = result.data if result else None
    if not row:
        raise HTTPException(status_code=403, detail="Forbidden")

    if row.get("user_id") == principal.user_id:
        return

    org_id = row.get("organization_id")
    if org_id:
        try:
            membership = (
                supabase.table("organization_members")
                .select("user_id")
                .eq("org_id", org_id)
                .eq("user_id", principal.user_id)
                .maybe_single()
                .execute()
            )
        except Exception:
            log.exception("organization_members lookup failed")
            raise HTTPException(status_code=403, detail="Forbidden") from None
        if membership and membership.data:
            return

    raise HTTPException(status_code=403, detail="Forbidden")
