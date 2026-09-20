"""Last.fm wrapper — read-only, cached, rate-limited.

Caching policy: definitive hits and misses are cached. Transient errors
are NOT cached.
"""

import json
import os
import time

import pylast

from settings import get as get_setting
from config import LASTFM_CACHE


_RATE_LIMIT = 5.0
_MIN_INTERVAL = 1.0 / _RATE_LIMIT

_key_verified = False

_TAG_BLOCKLIST = {
    "seen live", "favorites", "favourites", "favorite", "favourite",
    "spotify", "want to see live", "under 2000 listeners", "all",
    "owned by me", "albums i own", "i own this", "vinyl", "cd",
    "usa", "uk", "american", "british", "english", "canadian",
    "male vocalists", "female vocalists", "male", "female",
}


def _first_artist(obj):
    if obj is None:
        return None
    if hasattr(obj, "get_name"):
        return obj
    try:
        for a in obj:
            return a
    except TypeError:
        return None
    return None


def _is_transient(value) -> bool:
    if isinstance(value, dict):
        return "error" in value
    return False


class LastFM:
    def __init__(self):
        global _key_verified
        api_key = get_setting("lastfm_api_key")
        if not api_key:
            raise RuntimeError("Last.fm API key not configured.")

        self.network = pylast.LastFMNetwork(api_key=api_key)
        self._last_call = 0.0
        self._mem_cache: dict = {}
        self._disk_cache: dict = self._load_disk_cache()

        if not _key_verified:
            try:
                self.network.get_artist("Radiohead").get_listener_count()
                _key_verified = True
            except pylast.WSError as e:
                raise RuntimeError(f"Last.fm API key rejected: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Last.fm unreachable: {e}") from e

    def _load_disk_cache(self) -> dict:
        if os.path.exists(LASTFM_CACHE):
            try:
                with open(LASTFM_CACHE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_disk_cache(self) -> None:
        try:
            with open(LASTFM_CACHE, "w") as f:
                json.dump(self._disk_cache, f, indent=2)
        except OSError:
            pass

    def _cached(self, key: str, producer):
        if key in self._mem_cache:
            return self._mem_cache[key]
        if key in self._disk_cache:
            self._mem_cache[key] = self._disk_cache[key]
            return self._disk_cache[key]
        value = producer()
        if not _is_transient(value):
            self._mem_cache[key] = value
            self._disk_cache[key] = value
            self._save_disk_cache()
        return value

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        self._last_call = time.time()

    # --------------------------------------------------------------- tools

    def search_artist(self, name: str) -> dict:
        # Version the cache key so old "not found" entries from before this
        # fix don't poison lookups.
        key = f"search_artist:v2:{name.lower().strip()}"

        def produce():
            # 1. Try search_for_artist. Strict index — needs exact spelling.
            try:
                self._throttle()
                result = self.network.search_for_artist(name)
                artist = _first_artist(result)
                if artist is not None:
                    try:
                        listeners = int(artist.get_listener_count())
                    except (AttributeError, pylast.WSError):
                        listeners = 0
                    if listeners > 0:
                        return {
                            "found": True,
                            "name": artist.get_name(),
                            "listeners": listeners,
                            "via": "search",
                        }
            except (pylast.WSError, AttributeError):
                pass

            # 2. Fallback: get_artist uses Last.fm's getInfo which does
            #    server-side fuzzy matching and returns the CANONICAL name.
            #    This is what turns "Casanova Bulhar" into "CA$HANOVA BULHAR".
            try:
                self._throttle()
                a = self.network.get_artist(name)
                canonical = a.get_name()
                # Validate: ask for one track. If it returns anything, the
                # artist exists under that name.
                try:
                    probe = a.get_top_tracks(limit=1)
                    has_tracks = len(probe) > 0
                except Exception:
                    has_tracks = False

                if has_tracks:
                    corrected = None
                    if canonical.lower() != name.lower():
                        corrected = canonical
                    return {
                        "found": True,
                        "name": canonical,
                        "listeners": 0,
                        "via": "get_artist",
                        "corrected_from": corrected,
                    }
            except Exception:
                pass

            return {"found": False}

        return self._cached(key, produce)

    def get_artist_top_tracks(self, artist: str, limit: int = 20) -> list[dict]:
        key = f"top_tracks:{artist.lower().strip()}:{limit}"

        def produce():
            try:
                self._throttle()
                a = self.network.get_artist(artist)
                return [
                    {"title": item.item.get_title(),
                     "artist": item.item.get_artist().get_name(),
                     "playcount": int(item.weight)}
                    for item in a.get_top_tracks(limit=limit)
                ]
            except (pylast.WSError, IndexError, AttributeError):
                return []

        return self._cached(key, produce)

    def get_similar_artists(self, artist: str, limit: int = 10) -> list[dict]:
        key = f"similar_artists:{artist.lower().strip()}:{limit}"

        def produce():
            try:
                self._throttle()
                a = self.network.get_artist(artist)
                return [
                    {"name": item.item.get_name(), "match": round(float(item.weight), 3)}
                    for item in a.get_similar(limit=limit)
                ]
            except (pylast.WSError, IndexError, AttributeError):
                return []

        return self._cached(key, produce)

    def get_similar_tracks(self, artist: str, track: str, limit: int = 10) -> list[dict]:
        key = f"similar_tracks:{artist.lower().strip()}:{track.lower().strip()}:{limit}"

        def produce():
            try:
                self._throttle()
                t = self.network.get_track(artist, track)
                return [
                    {"title": item.item.get_title(),
                     "artist": item.item.get_artist().get_name(),
                     "match": round(float(item.weight), 3)}
                    for item in t.get_similar(limit=limit)
                ]
            except (pylast.WSError, IndexError, AttributeError):
                return []

        return self._cached(key, produce)

    def get_artist_tags(self, artist: str, limit: int = 10) -> list[dict]:
        key = f"artist_tags:{artist.lower().strip()}:{limit}"

        def produce():
            try:
                self._throttle()
                a = self.network.get_artist(artist)
                return [
                    {"tag": item.item.get_name(), "weight": int(item.weight)}
                    for item in a.get_top_tags(limit=limit)
                ]
            except (pylast.WSError, IndexError, AttributeError):
                return []

        return self._cached(key, produce)

    def get_artist_top_tag(self, artist: str) -> str:
        key = f"artist_top_tag:{artist.lower().strip()}"

        def produce():
            tags = self.get_artist_tags(artist, limit=8)
            for t in tags:
                tag = t["tag"].strip()
                if tag.lower() in _TAG_BLOCKLIST:
                    continue
                return tag
            return ""

        return self._cached(key, produce)