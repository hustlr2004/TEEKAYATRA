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


def encrypt_phone(phone: str) -> str:
    if phone.startswith("gAAAAA"):
        return phone
    return Fernet(_key()).encrypt(phone.encode("utf-8")).decode("utf-8")


def decrypt_phone(ciphertext: str) -> str:
    return Fernet(_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def masked_phone(ciphertext: str) -> str:
    plain = decrypt_phone(ciphertext)
    return "****" + plain[-4:]
