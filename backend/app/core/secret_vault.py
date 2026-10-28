"""Small application-level vault for persisted runtime model credentials.

The database stores only versioned Fernet ciphertext. The encryption key is
derived from MODEL_CONFIG_ENCRYPTION_KEY (or SECRET_KEY for local migration).
Legacy plaintext values remain readable and are rewritten encrypted on the
next save or by ``scripts.encrypt_model_config``.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

PREFIX = "enc:v1:"


def _cipher() -> Fernet:
    settings = get_settings()
    material = settings.MODEL_CONFIG_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    token = _cipher().encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("模型密钥无法解密，请检查 MODEL_CONFIG_ENCRYPTION_KEY") from exc
