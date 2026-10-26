"""Password hashing (Argon2id) and JWT access tokens."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import AuthenticationError

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters

# Verified against when the user does not exist, so login timing does not reveal valid emails.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, secret: str, algorithm: str, expire_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, secret: str, algorithm: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[algorithm], options={"require": ["exp", "iat", "sub"]}
        )
        if payload.get("type") != "access":
            raise AuthenticationError("Invalid token")
        return uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired, please log in again") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Invalid token") from exc
