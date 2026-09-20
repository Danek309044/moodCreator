"""Preview-run counter + last-preview storage, per user."""

import json
import os
import time

from config import PREVIEWS_DIR


def _path(user_id: str) -> str:
    return os.path.join(PREVIEWS_DIR, f"{user_id}.jsonl")


def _latest_path(user_id: str) -> str:
    return os.path.join(PREVIEWS_DIR, f"{user_id}_latest.json")


# ---------------------------------------------------------------- counter

def record(user_id: str) -> None:
    try:
        with open(_path(user_id), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time()}) + "\n")
    except OSError:
        pass


def count(user_id: str) -> int:
    p = _path(user_id)
    if not os.path.exists(p):
        return 0
    n = 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
    except OSError:
        return 0
    return n


# -------------------------------------------------------------- last preview

def save_latest(user_id: str, proposal: dict) -> None:
    try:
        with open(_latest_path(user_id), "w", encoding="utf-8") as f:
            json.dump(proposal, f, ensure_ascii=False)
    except OSError:
        pass


def load_latest(user_id: str) -> dict | None:
    p = _latest_path(user_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_latest(user_id: str) -> None:
    try:
        os.remove(_latest_path(user_id))
    except OSError:
        pass


# ------------------------------------------------------------------ misc

def delete_all(user_id: str) -> None:
    try:
        os.remove(_path(user_id))
    except OSError:
        pass
    clear_latest(user_id)


def all_user_ids() -> list[str]:
    if not os.path.exists(PREVIEWS_DIR):
        return []
    ids = set()
    try:
        for fname in os.listdir(PREVIEWS_DIR):
            if fname.endswith(".jsonl"):
                ids.add(fname[:-6])
            elif fname.endswith("_latest.json"):
                ids.add(fname[:-12])
    except OSError:
        return []
    return sorted(ids)