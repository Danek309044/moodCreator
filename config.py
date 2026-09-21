"""Paths and constants. No local imports — this is the bottom of the
dependency graph. Anything that needs runtime values (API keys) should call
settings.get(...) instead of importing them here.
"""

import os


# --- OAuth ---
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:4444/callback"
SPOTIFY_SCOPES       = "user-read-private playlist-modify-private playlist-modify-public"

# --- Data layout ---
DATA_DIR      = "data"
TOKENS_DIR    = os.path.join(DATA_DIR, "tokens")
HISTORY_DIR   = os.path.join(DATA_DIR, "history")
PREVIEWS_DIR  = os.path.join(DATA_DIR, "previews")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# ...existing caches and log...

for _d in (DATA_DIR, TOKENS_DIR, HISTORY_DIR, PREVIEWS_DIR):
    os.makedirs(_d, exist_ok=True)

# --- Caches (top-level, not in data/, they're regenerable) ---
LASTFM_CACHE          = ".lastfm_cache.json"
SPOTIFY_SEARCH_CACHE  = ".spotify_search_cache.json"
SPOTIFY_CATALOG_CACHE = ".spotify_catalog_cache.json"

# --- CLI log (legacy, web app uses history.py instead) ---
RUNS_LOG = "runs.jsonl"

# Create the data directories on import — every caller needs them.
for _d in (DATA_DIR, TOKENS_DIR, HISTORY_DIR):
    os.makedirs(_d, exist_ok=True)