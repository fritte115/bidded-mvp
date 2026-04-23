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
    """Validate a Supabase HS256 access token and return the caller identity."""
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
        return _authenticated_user_from_claims(
            user_id=payload.get("sub"),
            email=payload.get("email"),
        )

    return _authenticate_via_supabase(token, settings=resolved_settings)


def _authenticate_via_supabase(
    token: str,
    *,
    settings: Any,
) -> AuthenticatedUser:
    supabase_url = getattr(settings, "supabase_url", None)
    service_role_key = getattr(settings, "supabase_service_role_key", None)
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "SUPABASE_JWT_SECRET or both SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY are required for authenticated "
                "API requests."
            ),
        )

    from supabase import create_client  # noqa: PLC0415
    from supabase_auth.errors import (  # noqa: PLC0415
        AuthApiError,
        AuthRetryableError,
        AuthUnknownError,
    )

    try:
        auth_client = create_client(str(supabase_url), str(service_role_key)).auth
        response = auth_client.get_user(jwt=token)
    except AuthApiError as exc:
        if _is_invalid_supabase_token_error(exc):
            raise _invalid_token() from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase Auth could not verify the bearer token.",
        ) from exc
    except (AuthRetryableError, AuthUnknownError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth verification is temporarily unavailable.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth verification failed.",
        ) from exc

    user = getattr(response, "user", None)
    return _authenticated_user_from_claims(
        user_id=getattr(user, "id", None),
        email=getattr(user, "email", None),
    )


def _authenticated_user_from_claims(
    *,
    user_id: Any,
    email: Any,
) -> AuthenticatedUser:
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is missing a subject.",
        )

    return AuthenticatedUser(
        user_id=user_id,
        email=email if isinstance(email, str) else None,
    )


def _is_invalid_supabase_token_error(error: Any) -> bool:
    code = getattr(error, "code", None)
    if code in {
        "bad_jwt",
        "invalid_jwt",
        "no_authorization",
        "session_not_found",
        "user_not_found",
    }:
        return True

    message = str(getattr(error, "message", error)).lower()
    return any(
        fragment in message
        for fragment in (
            "jwt",
            "authorization",
            "session not found",
            "user not found",
            "token",
        )
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
