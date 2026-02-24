"""
K8S NetLab - User Authentication

Lightweight user authentication and session management.
"""

import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from backend.password_utils import hash_password, needs_upgrade, verify_password

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
            USERS_FILE.write_text(json.dumps({}, indent=2))

        if not SESSIONS_FILE.exists():
            SESSIONS_FILE.write_text(json.dumps({}, indent=2))

    def _load_users(self) -> Dict:
        """Load users from file."""
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            return {}

    def _save_users(self, users: Dict):
        """Save users to file."""
        try:
            with open(USERS_FILE, 'w') as f:
                json.dump(users, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save users: {e}")

    def _load_sessions(self) -> Dict:
        """Load sessions from file."""
        try:
            with open(SESSIONS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")
            return {}

    def _save_sessions(self, sessions: Dict):
        """Save sessions to file."""
        try:
            with open(SESSIONS_FILE, 'w') as f:
                json.dump(sessions, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def register_user(self, username: str, password: str) -> bool:
        """
        Register a new user with bcrypt password hash.

        Args:
            username: Username (unique)
            password: Plain password

        Returns:
            True if successful, False if username exists
        """
        users = self._load_users()

        if username in users:
            logger.warning(f"Username '{username}' already exists")
            return False

        users[username] = {
            "password_hash": hash_password(password),
            "created_at": datetime.now().isoformat(),
        }

        self._save_users(users)
        logger.info(f"User '{username}' registered successfully (bcrypt)")
        return True

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
            users[username]["password_hash"] = hash_password(password)
            self._save_users(users)
            logger.info(f"Password for '{username}' upgraded to bcrypt")

        return True

    def create_session(self, username: str) -> str:
        """
        Create a new session for user.

        Args:
            username: Username

        Returns:
            Session token
        """
        # Generate secure random token
        token = secrets.token_urlsafe(32)

        sessions = self._load_sessions()

        # Session expires in 24 hours
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()

        sessions[token] = {
            "username": username,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at,
        }

        self._save_sessions(sessions)
        logger.info(f"Session created for user '{username}'")

        return token

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
            # Session expired, remove it
            del sessions[token]
            self._save_sessions(sessions)
            logger.info(f"Session expired and removed: {token[:10]}...")
            return None

        return session["username"]

    def delete_session(self, token: str):
        """
        Delete a session (logout).

        Args:
            token: Session token
        """
        sessions = self._load_sessions()

        if token in sessions:
            username = sessions[token]["username"]
            del sessions[token]
            self._save_sessions(sessions)
            logger.info(f"Session deleted for user '{username}'")

    def cleanup_expired_sessions(self):
        """Remove all expired sessions."""
        sessions = self._load_sessions()
        now = datetime.now()

        expired_tokens = []
        for token, session in sessions.items():
            expires_at = datetime.fromisoformat(session["expires_at"])
            if now > expires_at:
                expired_tokens.append(token)

        for token in expired_tokens:
            del sessions[token]

        if expired_tokens:
            self._save_sessions(sessions)
            logger.info(f"Cleaned up {len(expired_tokens)} expired sessions")


# Global auth manager instance
auth_manager = AuthManager()
