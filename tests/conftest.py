"""
Pytest configuration: load .env before any backend module is imported.

config.py reads env vars at module level, so env must be set first.
"""
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE any backend module is imported
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
