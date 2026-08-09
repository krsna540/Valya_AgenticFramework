from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt has a hard 72-byte input limit; schemas.user.UserCreate caps password
# length at 72 chars so this never silently truncates real user input.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed_password.encode("utf-8")
    )


def _signing_key() -> tuple[str, str]:
    """Return (key, algorithm) for signing a new token.

    RS256 when a private key is configured — the production path, and the
    only one every other service (app/stream.py, a future agent worker
    that only verifies) needs to trust without also being able to mint.
    Falls back to the HS256 shared secret only when no key pair is
    configured, so a fresh checkout with an empty .env still boots — see
    the docstring on Settings.jwt_algorithm.
    """
    if settings.jwt_private_key.strip():
        return settings.jwt_private_key, "RS256"
    return settings.jwt_secret, "HS256"


def create_access_token(subject: str, expires_minutes: int | None = None, extra_claims: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    key, algorithm = _signing_key()
    return jwt.encode(payload, key, algorithm=algorithm)


def decode_access_token(token: str) -> str | None:
    claims = decode_access_token_claims(token)
    return claims.get("sub") if claims else None


def decode_access_token_claims(token: str) -> dict[str, Any] | None:
    """Verify and return the full claim set, offline — no call to any auth
    service (PLATFORM_ARCHITECTURE.md §3.1/§14: "any service verifies it
    offline against a cached public key"). Tries RS256 against the
    configured public key first, then falls back to the HS256 dev secret,
    so tokens minted under either scheme during a key rotation still
    verify.
    """
    if settings.jwt_public_key.strip():
        try:
            return jwt.decode(token, settings.jwt_public_key, algorithms=["RS256"])
        except JWTError:
            pass
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        return None
