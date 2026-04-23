from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from bidded.auth import AuthenticatedUser, authenticate_supabase_jwt


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _token(payload: dict[str, Any], *, secret: str = "jwt-secret") -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url(signature)}"


def test_authenticate_supabase_jwt_returns_authenticated_user() -> None:
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "email": "admin@example.com",
            "exp": int(time.time()) + 60,
        }
    )

    user = authenticate_supabase_jwt(
        f"Bearer {token}",
        settings=SimpleNamespace(supabase_jwt_secret="jwt-secret"),
    )

    assert user == AuthenticatedUser(
        user_id="11111111-1111-4111-8111-111111111111",
        email="admin@example.com",
    )


def test_authenticate_supabase_jwt_rejects_missing_bearer_token() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate_supabase_jwt(None, settings=SimpleNamespace())

    assert exc.value.status_code == 401


def test_authenticate_supabase_jwt_rejects_bad_signature() -> None:
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "exp": int(time.time()) + 60,
        },
        secret="different-secret",
    )

    with pytest.raises(HTTPException) as exc:
        authenticate_supabase_jwt(
            f"Bearer {token}",
            settings=SimpleNamespace(supabase_jwt_secret="jwt-secret"),
        )

    assert exc.value.status_code == 401


def test_authenticate_supabase_jwt_rejects_expired_token() -> None:
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "exp": int(time.time()) - 1,
        }
    )

    with pytest.raises(HTTPException) as exc:
        authenticate_supabase_jwt(
            f"Bearer {token}",
            settings=SimpleNamespace(supabase_jwt_secret="jwt-secret"),
        )

    assert exc.value.status_code == 401
