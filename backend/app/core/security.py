"""JWT issuance/verification and password hashing utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_settings = get_settings()
# NOTE: we intentionally use pbkdf2_sha256 as the active scheme. Recent bcrypt
# releases (>= 4.1) raise during passlib's backend auto-detection ("password
# cannot be longer than 72 bytes"), which breaks first-use hashing on some
# environments. pbkdf2_sha256 is a pure-Python, dependency-free scheme that
# guarantees consistent verification across supported Windows environments.
_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Create a signed JWT for *subject* (user_id)."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=_settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _settings.SECRET_KEY, algorithm=_settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises PyJWTError on failure."""
    return jwt.decode(token, _settings.SECRET_KEY, algorithms=[_settings.JWT_ALGORITHM])
