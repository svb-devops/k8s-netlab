"""
K8S NetLab - User Authentication

Lightweight user authentication and session management.
"""

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

    def register_user(self, username: str, password: str) -> bool:
        """
        Register a new user with bcrypt password hash.

        Args:
            username: Username (unique)
            password: Plain password

        Returns:
            True if successful, False if username exists
        """
        registered = False

        def _add(users: Dict) -> Dict:
            nonlocal registered
            if username in users:
                return users
            users[username] = {
                "password_hash": hash_password(password),
                "created_at": datetime.now().isoformat(),
            }
            registered = True
            return users

        safe_update_json(USERS_FILE, _add)

        if registered:
            logger.info(f"User '{username}' registered successfully (bcrypt)")
        else:
            logger.warning(f"Username '{username}' already exists")
        return registered

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
