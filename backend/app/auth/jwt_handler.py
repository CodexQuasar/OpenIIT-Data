# JWT token creation and verification
from datetime import datetime, timedelta
from typing import Optional, NamedTuple
import os
import hmac
import hashlib
import base64
import json

from config.settings import get_settings


class TokenData(NamedTuple):
    """Decoded token payload."""
    user_id: str
    session_id: str
    role: str
    tenant_id: Optional[str]
    exp: datetime


# Signing key loaded from settings (env-overridable)
_settings = get_settings()
JWT_SECRET = os.environ.get("JWT_SECRET", _settings.secret_key)
JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", str(_settings.token_ttl_hours)))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(
    user_id: str,
    session_id: str,
    role: str,
    tenant_id: Optional[str] = None,
    ttl_hours: int = TOKEN_TTL_HOURS,
) -> str:
    """Create a signed JWT access token."""
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "sid": session_id,
        "role": role,
        "tenant": tenant_id,
        "iat": now.timestamp(),
        "exp": (now + timedelta(hours=ttl_hours)).timestamp(),
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_token(token: str) -> Optional[TokenData]:
    """Verify and decode a JWT access token. Returns None if invalid/expired."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            return None

        # Decode payload
        payload = json.loads(_b64url_decode(payload_b64))

        # Check expiry
        exp = datetime.utcfromtimestamp(payload["exp"])
        if datetime.utcnow() > exp:
            return None

        return TokenData(
            user_id=payload["sub"],
            session_id=payload["sid"],
            role=payload.get("role", ""),
            tenant_id=payload.get("tenant"),
            exp=exp,
        )
    except Exception:
        return None
