"""
Thin wrapper around the Spotify Web API — throttled and cached.

Endpoints:
  GET  /me                         -> current user
  GET  /search                     -> find a track or artist by name
  GET  /artists/{id}               -> artist profile
  GET  /artists/{id}/albums        -> artist discography
  GET  /albums/{id}/tracks         -> tracks per album
  POST /me/playlists               -> create a playlist for the current user
  POST /playlists/{id}/items       -> add tracks to a playlist

Optimizations:
  - Proactive throttle: min 0.5s between requests
  - Bail-out on long Retry-After (>300s)
  - Genre reliability learning (skips genre filters that keep failing)
  - Disk cache for search results (30-day TTL)
  - Disk cache for artist catalogs (7-day TTL)

Playlist limits:
  - Max tracks per playlist: 10,000
  - Max tracks per add_items request: 100
  - Max search results per request: 50
"""

import logger
log = logger.get_logger("spotify")

import json
import os
import re
import time

import requests

from config import SPOTIFY_SEARCH_CACHE, SPOTIFY_CATALOG_CACHE


API_BASE = "https://api.spotify.com/v1"

_SEARCH_TTL  = 30 * 24 * 3600
_CATALOG_TTL = 7  * 24 * 3600

_GENRE_FAILURE_THRESHOLD = 5


def _word_pattern(name: str) -> re.Pattern:
    key = name.lower()
    if key not in _word_pattern._cache:
        _word_pattern._cache[key] = re.compile(r"\b" + re.escape(key) + r"\b")
    return _word_pattern._cache[key]


_word_pattern._cache: dict[str, re.Pattern] = {}


def _artist_names_contain(requested: str, result_names: list[str]) -> bool:
    pat = _word_pattern(requested)
    return any(pat.search(n.lower()) for n in result_names)


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


class Spotify:
    def __init__(self, token: str, min_interval: float = 0.5):
        self.token = token
        self.session = requests.Session()
        self._min_interval = min_interval
        self._last_call = 0.0
        self._genre_stats: dict[str, dict] = {}
        self._search_cache  = _load_json(SPOTIFY_SEARCH_CACHE)
        self._catalog_cache = _load_json(SPOTIFY_CATALOG_CACHE)

    # ------------------------------------------------------------------ HTTP

    def _req(self, method: str, path: str, **kwargs):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

        url = API_BASE + path
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"

        delay = 1.0
        for _ in range(6):
            r = self.session.request(method, url, headers=headers, **kwargs)

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", delay))
                if retry_after > 300:
                    raise RuntimeError(
                        f"Rate limited for {retry_after}s — too long to wait. "
                        f"Aborting to avoid escalating the cooldown. "
                        f"Try again in {retry_after // 3600}h."
                    )
                wait = max(retry_after, delay)
                log.warning("rate limited, sleeping %ss (Retry-After: %s)",
                            wait, retry_after)
                time.sleep(wait)
                delay *= 2
                continue

            if r.status_code >= 500:
                time.sleep(delay)
                delay *= 2
                continue

            if not r.ok:
                try:
                    body = r.json()
                    msg = body.get("error", {}).get("message", r.text)
                    reason = body.get("error", {}).get("reason", "")
                except Exception:
                    msg, reason = r.text, ""
                raise RuntimeError(f"Spotify {r.status_code}: {msg} {reason}")

            return r.json() if r.text else None

        raise RuntimeError("Gave up after repeated retries.")

    # ------------------------------------------------------------- search

    def search_track(self, title: str, artist: str, genre: str = "",
                     allowed: list[str] | None = None, limit: int = 10,
                     use_genre: bool = True):
        cache_key = f"{artist.lower().strip()}|{title.lower().strip()}|{genre.lower().strip()}"
        if cache_key in self._search_cache:
            entry = self._search_cache[cache_key]
            if time.time() - entry.get("ts", 0) < _SEARCH_TTL:
                return entry.get("track") if entry.get("track") else None

        q_parts = [f'track:"{title}"', f'artist:"{artist}"']
        if genre and use_genre:
            q_parts.append(f'genre:"{genre}"')
        q = " ".join(q_parts)

        data = self._req("GET", "/search",
                         params={"q": q, "type": "track", "limit": limit})
        items = data.get("tracks", {}).get("items", [])

        hit = None
        if allowed:
            for item in items:
                names = [a["name"] for a in item["artists"]]
                if any(_artist_names_contain(a, names) for a in allowed):
                    hit = item
                    break
        else:
            for item in items:
                names = [a["name"] for a in item["artists"]]
                if _artist_names_contain(artist, names):
                    hit = item
                    break

        self._search_cache[cache_key] = {"track": hit, "ts": time.time()}
        _save_json(SPOTIFY_SEARCH_CACHE, self._search_cache)
        return hit

    def search_track_with_fallback(self, title: str, artist: str,
                                   genre: str = "",
                                   allowed: list[str] | None = None):
        use_genre = True
        if genre:
            stats = self._genre_stats.setdefault(genre, {"ok": 0, "fail": 0})
            if stats["fail"] >= _GENRE_FAILURE_THRESHOLD:
                use_genre = False

        hit = self.search_track(title, artist, genre=genre,
                                allowed=allowed, use_genre=use_genre)

        if hit is None and genre and use_genre:
            self._genre_stats[genre]["fail"] += 1
            hit = self.search_track(title, artist, genre="",
                                    allowed=allowed, use_genre=False)
        elif hit and genre and use_genre:
            self._genre_stats.setdefault(genre, {"ok": 0, "fail": 0})["ok"] += 1

        return hit

    def search_artist(self, name: str, limit: int = 5):
        data = self._req("GET", "/search",
                         params={"q": name, "type": "artist", "limit": limit})
        items = data.get("artists", {}).get("items", [])
        for item in items:
            if _artist_names_contain(name, [item["name"]]):
                return item
        return None

    # ------------------------------------------------------------- catalog

    def artist_info(self, artist_id: str) -> dict:
        return self._req("GET", f"/artists/{artist_id}")

    def artist_albums(self, artist_id: str, limit: int = 3,
                      include_groups: str = "album,single") -> list[dict]:
        data = self._req(
            "GET",
            f"/artists/{artist_id}/albums",
            params={
                "include_groups": include_groups,
                "limit": min(limit, 10),
                "market": "from_token",
            },
        )
        return data.get("items", [])

    def album_tracks(self, album_id: str, limit: int = 50) -> list[dict]:
        data = self._req(
            "GET",
            f"/albums/{album_id}/tracks",
            params={"limit": min(limit, 50), "market": "from_token"},
        )
        return data.get("items", [])

    def artist_catalog_tracks(self, artist_id: str,
                              max_albums: int = 3) -> list[dict]:
        cache_key = f"{artist_id}:{max_albums}"
        if cache_key in self._catalog_cache:
            entry = self._catalog_cache[cache_key]
            if time.time() - entry.get("ts", 0) < _CATALOG_TTL:
                return entry.get("tracks", [])

        albums = self.artist_albums(artist_id, limit=max_albums)
        seen_uris = set()
        tracks = []

        for album in albums:
            try:
                album_tracks = self.album_tracks(album["id"])
            except RuntimeError:
                continue
            for t in album_tracks:
                uri = t.get("uri")
                if not uri or uri in seen_uris:
                    continue
                if "artists" not in t:
                    t["artists"] = album.get("artists", [])
                seen_uris.add(uri)
                tracks.append(t)

        self._catalog_cache[cache_key] = {"tracks": tracks, "ts": time.time()}
        _save_json(SPOTIFY_CATALOG_CACHE, self._catalog_cache)
        return tracks

    # ------------------------------------------------------------- playlist

    def create_playlist(self, name: str, description: str = "",
                        public: bool = False) -> dict:
        return self._req(
            "POST",
            "/me/playlists",
            json={"name": name, "description": description, "public": public},
        )

    def add_items(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            self._req(
                "POST",
                f"/playlists/{playlist_id}/items",
                json={"uris": uris[i:i + 100]},
            )