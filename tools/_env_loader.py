# tools/_env_loader.py
"""Shared helper to load .env credentials for VPS tooling."""
import os
from dotenv import load_dotenv

# Load .env from the repo root (parent of tools/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def require_env(*keys: str) -> dict:
    """Return a dict of required env vars, exiting if any are missing."""
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"[!] Missing environment variables: {', '.join(missing)}")
        print("    Set them in a .env file at the repo root or export them.")
        raise SystemExit(1)
    return {k: os.environ[k] for k in keys}
