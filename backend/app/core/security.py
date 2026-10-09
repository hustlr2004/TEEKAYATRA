from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..database import get_db
from ..models import Role, User
from .config import get_settings


LEGACY_HASH_SCHEME = "pbkdf2" + "_sha256"
PASSWORD_ITERATIONS = 200_000
ARGON2_PREFIX = "$argon2"
bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(ARGON2_PREFIX):
        try:
            return password_hasher.verify(stored_hash, password)
        except VerifyMismatchError:
            return False
    if not stored_hash or "$" not in stored_hash:
        return False
    algorithm, iterations, salt, digest = stored_hash.split("$", 3)
    if algorithm != LEGACY_HASH_SCHEME:
        return False
    try:
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac_compare(expected, digest)
    except (TypeError, ValueError):
        return False


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def create_access_token(user: User) -> str:
    settings = get_settings()
    payload: Dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role.value,
        "typ": "access",
        "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def user_id_from_token(token: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != "access":
            raise ValueError("wrong token type")
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Any = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user_id = user_id_from_token(credentials.credentials)
    if hasattr(db, "run_sync"):
        user = await db.run_sync(lambda sync_db: sync_db.get(User, user_id))
    else:
        user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


def require_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
