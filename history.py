"""Per-user playlist history, stored as data/history/{user_id}.jsonl."""

import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

from config import HISTORY_DIR
import previews as _previews


def _path(user_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{user_id}.jsonl")


def append(user_id: str, entry: dict) -> None:
    try:
        with open(_path(user_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def list_for_user(user_id: str, limit: int = 50) -> list[dict]:
    p = _path(user_id)
    if not os.path.exists(p):
        return []
    entries = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    entries.reverse()
    return entries[:limit]


def delete_all(user_id: str) -> None:
    try:
        os.remove(_path(user_id))
    except OSError:
        pass


def delete_entry(user_id: str, ts: str) -> None:
    p = _path(user_id)
    if not os.path.exists(p):
        return
    kept = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("ts") != ts:
                    kept.append(e)
    except OSError:
        return
    try:
        with open(p, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- user ids

def all_user_ids() -> list[str]:
    """Every user_id that has a history file or a previews file."""
    ids: set[str] = set()

    if os.path.exists(HISTORY_DIR):
        try:
            for fname in os.listdir(HISTORY_DIR):
                if fname.endswith(".jsonl"):
                    ids.add(fname[:-6])
        except OSError:
            pass

    for uid in _previews.all_user_ids():
        ids.add(uid)

    return sorted(ids)


# ------------------------------------------------------------------ stats

def _user_stats(user_id: str) -> dict:
    entries = list_for_user(user_id, limit=100_000)
    playlists = len(entries)
    tracks = sum(len(e.get("tracks") or []) for e in entries)
    return {
        "previews": _previews.count(user_id),
        "playlists": playlists,
        "tracks": tracks,
    }


def stats_for_user(user_id: str) -> dict:
    return _user_stats(user_id)


def stats_for_all() -> dict:
    ids = all_user_ids()

    agg = {"previews": 0, "playlists": 0, "tracks": 0}
    per_user: dict[str, dict] = {}

    for uid in ids:
        s = _user_stats(uid)
        per_user[uid] = s
        agg["previews"] += s["previews"]
        agg["playlists"] += s["playlists"]
        agg["tracks"] += s["tracks"]

    n = len(ids)
    avg = {
        "previews": round(agg["previews"] / n, 1) if n else 0,
        "playlists": round(agg["playlists"] / n, 1) if n else 0,
        "tracks": round(agg["tracks"] / n, 1) if n else 0,
    }

    return {
        "aggregate": agg,
        "average_per_user": avg,
        "per_user": per_user,
        "user_count": n,
    }