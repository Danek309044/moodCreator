"""Session cookie -> user_id mapping, persisted to data/sessions.json."""

import json
import os
import secrets
import time

from config import SESSIONS_FILE


_SESSION_TTL = 30 * 24 * 3600  # 30 days
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE) as f:
                    _cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                _cache = {}
        else:
            _cache = {}
    return _cache


def _save() -> None:
    if _cache is None:
        return
    try:
        with open(SESSIONS_FILE, "w") as f:
            json.dump(_cache, f, indent=2)
    except OSError:
        pass


def create(user_id: str) -> str:
    store = _load()
    sid = secrets.token_urlsafe(32)
    store[sid] = {"user_id": user_id, "created": time.time()}
    _save()
    return sid


def resolve(session_id: str) -> str | None:
    if not session_id:
        return None
    entry = _load().get(session_id)
    if not entry:
        return None
    if time.time() - entry.get("created", 0) > _SESSION_TTL:
        destroy(session_id)
        return None
    return entry["user_id"]


def destroy(session_id: str) -> None:
    store = _load()
    if session_id in store:
        del store[session_id]
        _save()


def destroy_all_for_user(user_id: str) -> None:
    store = _load()
    to_remove = [sid for sid, e in store.items() if e.get("user_id") == user_id]
    for sid in to_remove:
        del store[sid]
    _save()