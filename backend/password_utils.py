"""
Password hashing utilities using bcrypt.

Provides bcrypt hashing with backward compatibility for SHA-256 hashes
(legacy users are auto-upgraded to bcrypt on successful login).
"""

import hashlib
import logging

import bcrypt

logger = logging.getLogger(__name__)

# bcrypt work factor: 12 rounds is secure and performant on modern hardware
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """
    Hash a password with bcrypt (auto-generates salt).

    Args:
        password: Plain-text password

    Returns:
        bcrypt hash string (starts with $2b$)
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify a password against its stored hash.

    Supports both bcrypt (new) and SHA-256 (legacy) hashes for
    backward compatibility during migration.

    Args:
        password: Plain-text password to verify
        stored_hash: Hash stored in the users file

    Returns:
        True if password matches
    """
    try:
        if stored_hash.startswith(("$2b$", "$2a$", "$2y$")):
            # Modern bcrypt hash
            return bcrypt.checkpw(
                password.encode("utf-8"),
                stored_hash.encode("utf-8"),
            )
        else:
            # Legacy SHA-256 hash (no salt) — backward compat only
            sha256 = hashlib.sha256(password.encode()).hexdigest()
            return sha256 == stored_hash
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def needs_upgrade(stored_hash: str) -> bool:
    """
    Return True if the stored hash should be upgraded to bcrypt.

    Args:
        stored_hash: Hash stored in the users file

    Returns:
        True if hash is not bcrypt format
    """
    return not stored_hash.startswith(("$2b$", "$2a$", "$2y$"))
