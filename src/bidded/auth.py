from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from bidded.config import load_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str | None = None


def authenticate_supabase_jwt(
    authorization: str | None,
    *,
    settings: Any | None = None,
) -> AuthenticatedUser:
    """Validate a Supabase access token and return the caller identity.

    Primary path: HS256 signature verification using SUPABASE_JWT_SECRET.

    Dev fallback (no JWT secret): validates the token against Supabase's
    /auth/v1/user endpoint using the service-role key. This is still secure —
    Supabase will reject any token it didn't issue. Add SUPABASE_JWT_SECRET to
    .env (Settings → API → JWT Secret in the Supabase dashboard) to use the
    faster local-verification path.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization bearer token.",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization bearer token.",
        )

    resolved_settings = settings or load_settings()
    jwt_secret = getattr(resolved_settings, "supabase_jwt_secret", None)

    if jwt_secret:
        payload = _decode_hs256_jwt(token, str(jwt_secret))
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token is missing a subject.",
            )
        email = payload.get("email")
        return AuthenticatedUser(
            user_id=user_id,
            email=email if isinstance(email, str) else None,
        )

    # Dev fallback: verify via Supabase /auth/v1/user
    supabase_url = getattr(resolved_settings, "supabase_url", None)
    service_key = getattr(resolved_settings, "supabase_service_role_key", None)

    if not supabase_url or not service_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Add SUPABASE_JWT_SECRET to .env (Supabase dashboard → Settings → API → JWT Secret). "
                "Also ensure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set."
            ),
        )

    try:
        import httpx  # noqa: PLC0415

        resp = httpx.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": service_key,
            },
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reach Supabase to validate token: {exc}",
        ) from exc

    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid or expired.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed (Supabase returned {resp.status_code}).",
        )

    data = resp.json()
    user_id = data.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase returned a user without an id.",
        )

    return AuthenticatedUser(
        user_id=user_id,
        email=data.get("email"),
    )


def _decode_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise _invalid_token()

    header_raw, payload_raw, signature_raw = parts
    try:
        header = json.loads(_b64url_decode(header_raw))
        payload = json.loads(_b64url_decode(payload_raw))
        signature = _b64url_decode(signature_raw)
    except (ValueError, json.JSONDecodeError):
        raise _invalid_token() from None

    if header.get("alg") != "HS256":
        raise _invalid_token()

    signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise _invalid_token()

    exp = payload.get("exp")
    if isinstance(exp, int | float) and exp < time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token has expired.",
        )

    if not isinstance(payload, dict):
        raise _invalid_token()
    return payload


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Authorization bearer token.",
    )
