from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _key() -> bytes:
    configured = os.getenv("PHONE_ENCRYPTION_KEY")
    if configured:
        return configured.encode("utf-8")
    digest = hashlib.sha256(b"teeka-yatra-dev-phone-key").digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_text(value: str) -> str:
    if value.startswith("gAAAAA"):
        return value
    return Fernet(_key()).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    if not ciphertext.startswith("gAAAAA"):
        return ciphertext
    return Fernet(_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def encrypt_phone(phone: str) -> str:
    return encrypt_text(phone)


def decrypt_phone(ciphertext: str) -> str:
    return decrypt_text(ciphertext)


def masked_phone(ciphertext: str) -> str:
    plain = decrypt_phone(ciphertext)
    return "****" + plain[-4:]
