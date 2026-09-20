"""Runtime settings backed by data/settings.json."""

import json
import os

from config import SETTINGS_FILE, SPOTIFY_REDIRECT_URI


_cache: dict | None = None
_cache_mtime: float = 0


def load() -> dict:
    global _cache, _cache_mtime
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        return {}
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    try:
        with open(SETTINGS_FILE) as f:
            _cache = json.load(f)
            _cache_mtime = mtime
            return _cache
    except (json.JSONDecodeError, OSError):
        return {}


def save(data: dict) -> None:
    global _cache, _cache_mtime
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    _cache = None
    _cache_mtime = 0


def get(key: str, default=""):
    return load().get(key) or default


def is_configured() -> bool:
    s = load()
    return all([
        s.get("spotify_client_id"),
        s.get("deepseek_api_key"),
        s.get("lastfm_api_key"),
    ])


def admin_user_id() -> str:
    return load().get("admin_user_id", "")


def set_admin(user_id: str) -> None:
    s = load()
    if not s.get("admin_user_id"):
        s["admin_user_id"] = user_id
        save(s)


# --------------------------------------------------------- redirect URI

def get_redirect_uri() -> str:
    """Explicit setting > env var > default."""
    s = load()
    return (
        s.get("redirect_uri")
        or os.environ.get("SPOTIFY_REDIRECT_URI")
        or SPOTIFY_REDIRECT_URI
    )


def get_explicit_redirect_uri() -> str | None:
    """Only what's explicitly configured (settings or env), or None."""
    s = load()
    return s.get("redirect_uri") or os.environ.get("SPOTIFY_REDIRECT_URI") or None