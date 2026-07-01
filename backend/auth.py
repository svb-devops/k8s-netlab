"""
K8S NetLab - User Authentication

Lightweight user authentication and session management.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, cast

from backend.password_utils import hash_password, needs_upgrade, verify_password
from backend.storage_utils import safe_read_json, safe_update_json, safe_write_json

logger = logging.getLogger(__name__)

# Data paths
DATA_DIR = Path(__file__).parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"


class AuthManager:
    """Manages user authentication and sessions."""

    def __init__(self):
        """Initialize auth manager."""
        self._ensure_data_files()

    def _ensure_data_files(self):
        """Ensure data files exist."""
        DATA_DIR.mkdir(exist_ok=True)

        if not USERS_FILE.exists():
            safe_write_json(USERS_FILE, {})

        if not SESSIONS_FILE.exists():
            safe_write_json(SESSIONS_FILE, {})

    def _load_users(self) -> Dict:
        """Load users from file."""
        return safe_read_json(USERS_FILE, default={})

    def _load_sessions(self) -> Dict:
        """Load sessions from file."""
        return safe_read_json(SESSIONS_FILE, default={})

    def register_user(self, username: str, password: str, email: Optional[str] = None) -> bool:
        """
        Register a new user with bcrypt password hash.

        Args:
            username: Username (unique)
            password: Plain password
            email: Optional email (must be unique if provided; already normalized by caller)

        Returns:
            True if successful, False if username or email already exists
        """
        from backend import config

        registered = False
        # Email verification is only enforced when an email provider is configured
        # (RESEND_API_KEY set). Otherwise new users are treated as pre-verified —
        # this preserves current behavior when the feature is not yet configured.
        email_verified = not bool(config.RESEND_API_KEY)

        def _add(users: Dict) -> Dict:
            nonlocal registered
            if username in users:
                return users
            # Duplicate email check (case-insensitive, already lowercased by caller)
            if email:
                for u in users.values():
                    if u.get("email") and u["email"] == email:
                        return users
            record: Dict = {
                "password_hash": hash_password(password),
                "created_at": datetime.now().isoformat(),
                "email_verified": email_verified,
            }
            if email:
                record["email"] = email
            users[username] = record
            registered = True
            return users

        safe_update_json(USERS_FILE, _add)

        if registered:
            logger.info(f"User '{username}' registered successfully (bcrypt)")
        else:
            logger.warning(f"Registration failed for '{username}' (username or email conflict)")
        return registered

    def is_email_taken(self, email: str) -> bool:
        """Return True if any existing user already has this email (case-insensitive)."""
        users = self._load_users()
        return any(u.get("email") == email for u in users.values())

    def get_user_email(self, username: str) -> Optional[str]:
        """Return the registered email for username, or None if not set/found."""
        users = self._load_users()
        user = users.get(username)
        return user.get("email") if user else None

    def is_email_verified(self, username: str) -> bool:
        """
        Return True if the user's email is verified (or verification isn't required).

        Users created before this feature (or while RESEND_API_KEY was unset) have
        no `email_verified` field — default True so existing accounts stay usable.
        """
        users = self._load_users()
        user = users.get(username)
        if not user:
            return True
        return bool(user.get("email_verified", True))

    def generate_verification_code(self, username: str) -> Optional[str]:
        """
        Generate and store a 6-digit verification code for username (15 min TTL).

        The code is stored as a sha256 hash, never in plaintext. Returns the
        plaintext code (for the caller to email), or None if user not found.
        """
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
        found = False

        def _update(users: Dict) -> Dict:
            nonlocal found
            if username in users:
                found = True
                users[username]["verification_code_hash"] = code_hash
                users[username]["verification_code_expires_at"] = expires_at
                users[username]["verification_attempts"] = 0
            return users

        safe_update_json(USERS_FILE, _update)
        return code if found else None

    def verify_email(self, username: str, code: str) -> Dict:
        """
        Verify a registration code for username.

        Returns {"success": bool, "reason": Optional[str], "attempts_remaining": int}.
        reason (when success is False) is one of:
        "not_found", "too_many_attempts", "expired", "invalid_code".
        Max 5 attempts per code before it must be resent.
        """
        result: Dict = {"success": False, "reason": "not_found", "attempts_remaining": 0}

        def _update(users: Dict) -> Dict:
            user = users.get(username)
            if not user:
                return users
            if user.get("email_verified", True):
                result["success"] = True
                result["reason"] = None
                return users

            attempts = user.get("verification_attempts", 0)
            if attempts >= 5:
                result["reason"] = "too_many_attempts"
                return users

            expires_at = user.get("verification_code_expires_at")
            code_hash = user.get("verification_code_hash")
            if not expires_at or not code_hash or datetime.fromisoformat(expires_at) < datetime.now():
                result["reason"] = "expired"
                result["attempts_remaining"] = max(0, 5 - attempts)
                return users

            if not secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest(), code_hash):
                attempts += 1
                user["verification_attempts"] = attempts
                result["reason"] = "invalid_code"
                result["attempts_remaining"] = max(0, 5 - attempts)
                return users

            user["email_verified"] = True
            user.pop("verification_code_hash", None)
            user.pop("verification_code_expires_at", None)
            user["verification_attempts"] = 0
            result["success"] = True
            result["reason"] = None
            return users

        safe_update_json(USERS_FILE, _update)
        if result["success"]:
            logger.info(f"Email verified for user '{username}'")
        return result

    def verify_credentials(self, username: str, password: str) -> bool:
        """
        Verify user credentials. Supports bcrypt (new) and SHA-256 (legacy).

        On successful login with a legacy SHA-256 hash the password is
        automatically re-hashed with bcrypt so the user is silently migrated.

        Args:
            username: Username
            password: Plain password

        Returns:
            True if credentials are valid
        """
        users = self._load_users()

        if username not in users:
            return False

        stored_hash = users[username]["password_hash"]

        if not verify_password(password, stored_hash):
            return False

        # Auto-upgrade legacy SHA-256 hashes to bcrypt on successful login
        if needs_upgrade(stored_hash):
            def _upgrade(u: Dict) -> Dict:
                if username in u:
                    u[username]["password_hash"] = hash_password(password)
                return u
            safe_update_json(USERS_FILE, _upgrade)
            logger.info(f"Password for '{username}' upgraded to bcrypt")

        return True

    def create_session(self, username: str, login_ip: Optional[str] = None) -> str:
        """
        Create a new session for user.

        Args:
            username: Username
            login_ip: Client IP address at login time (optional)

        Returns:
            Session token
        """
        token = secrets.token_urlsafe(32)
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()

        def _add(sessions: Dict) -> Dict:
            # Evict previous sessions for this user (one active session per user)
            for old_token in [k for k, v in sessions.items() if v.get("username") == username]:
                del sessions[old_token]
            sessions[token] = {
                "username": username,
                "created_at": created_at,
                "expires_at": expires_at,
                "login_ip": login_ip,
            }
            return sessions

        safe_update_json(SESSIONS_FILE, _add)
        logger.info(f"Session created for user '{username}' from {login_ip or 'unknown'}")
        return token

    def get_active_sessions(self) -> list:
        """
        Return all non-expired sessions with their metadata.

        Returns:
            List of session dicts (without the raw token).
        """
        sessions = self._load_sessions()
        now = datetime.now()
        return [
            data
            for data in sessions.values()
            if datetime.fromisoformat(data["expires_at"]) > now
        ]

    def is_admin(self, username: str) -> bool:
        """Return True if username is in the ADMIN_USERNAMES config set."""
        from backend import config
        return username in config.ADMIN_USERNAMES

    def get_users_summary(self) -> Dict:
        """
        Return user metadata without password hashes.

        Returns:
            Dict mapping username → {created_at, is_admin}
        """
        from backend import config
        users = self._load_users()
        return {
            username: {
                "created_at": info.get("created_at"),
                "is_admin": username in config.ADMIN_USERNAMES,
            }
            for username, info in users.items()
        }

    def _invalidate_user_sessions(self, username: str) -> None:
        """Delete all sessions for a user (called after any password change)."""
        def _cleanup(sessions: Dict) -> Dict:
            to_delete = [k for k, v in sessions.items() if v.get("username") == username]
            for k in to_delete:
                del sessions[k]
            return sessions
        safe_update_json(SESSIONS_FILE, _cleanup)
        logger.info(f"All sessions invalidated for '{username}' (password changed)")

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """
        Change password after verifying the old one.

        Returns:
            True on success, False if old_password is incorrect.
        """
        if not self.verify_credentials(username, old_password):
            return False

        def _update(users: Dict) -> Dict:
            if username in users:
                users[username]["password_hash"] = hash_password(new_password)
            return users

        safe_update_json(USERS_FILE, _update)
        self._invalidate_user_sessions(username)
        logger.info(f"Password changed for '{username}'")
        return True

    def reset_password(self, username: str, new_password: str) -> bool:
        """
        Reset password without verifying the old one (admin action).

        Returns:
            True on success, False if user not found.
        """
        users = self._load_users()
        if username not in users:
            return False

        def _update(u: Dict) -> Dict:
            if username in u:
                u[username]["password_hash"] = hash_password(new_password)
            return u

        safe_update_json(USERS_FILE, _update)
        self._invalidate_user_sessions(username)
        logger.info(f"Password reset for '{username}' by admin")
        return True

    def update_session_activity(
        self, token: str, current_experiment: Optional[str] = None
    ) -> None:
        """
        Update session with latest activity data (best-effort, silent if token missing).

        Args:
            token: Session token
            current_experiment: Two-digit experiment ID the user switched to, e.g. "05"
        """
        def _update(sessions: Dict) -> Dict:
            if token in sessions:
                sessions[token]["last_activity"] = datetime.now().isoformat()
                if current_experiment is not None:
                    sessions[token]["current_experiment"] = current_experiment
            return sessions

        safe_update_json(SESSIONS_FILE, _update)

    def verify_session(self, token: str) -> Optional[str]:
        """
        Verify session token and return username.

        Args:
            token: Session token

        Returns:
            Username if valid, None if invalid/expired
        """
        sessions = self._load_sessions()

        if token not in sessions:
            return None

        session = sessions[token]

        # Check expiration
        expires_at = datetime.fromisoformat(session["expires_at"])
        if datetime.now() > expires_at:
            def _expire(s: Dict) -> Dict:
                s.pop(token, None)
                return s
            safe_update_json(SESSIONS_FILE, _expire)
            logger.info(f"Session expired and removed: {token[:10]}...")
            return None

        return cast(str, session["username"])

    def delete_session(self, token: str):
        """
        Delete a session (logout).

        Args:
            token: Session token
        """
        deleted_user = None

        def _delete(sessions: Dict) -> Dict:
            nonlocal deleted_user
            if token in sessions:
                deleted_user = sessions[token]["username"]
                del sessions[token]
            return sessions

        safe_update_json(SESSIONS_FILE, _delete)
        if deleted_user:
            logger.info(f"Session deleted for user '{deleted_user}'")

    def cleanup_expired_sessions(self):
        """Remove all expired sessions."""
        now = datetime.now()
        removed = 0

        def _cleanup(sessions: Dict) -> Dict:
            nonlocal removed
            expired = [
                tok for tok, s in sessions.items()
                if datetime.fromisoformat(s["expires_at"]) < now
            ]
            for tok in expired:
                del sessions[tok]
            removed = len(expired)
            return sessions

        safe_update_json(SESSIONS_FILE, _cleanup)
        if removed:
            logger.info(f"Cleaned up {removed} expired sessions")


# Global auth manager instance
auth_manager = AuthManager()
