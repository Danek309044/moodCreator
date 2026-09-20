"""Pipeline: generate (agent) + commit (Spotify). Plus a CLI wrapper."""

import json
import random
import re
import sys
from datetime import datetime, timezone

from deepseek import parse_mood, run_agent, resolve_artists, resolve_seed_artists
from lastfm import LastFM
from settings import get as get_setting
from config import RUNS_LOG


_HARD_PATTERN = re.compile(r"\bonly\s+(.+?)(?:$|\.|,)", re.IGNORECASE)
_SPLIT_PATTERN = re.compile(r"\s*(?:,|\band\b|&)\s*", re.IGNORECASE)


def extract_hard_artists(mood: str) -> list[str]:
    m = _HARD_PATTERN.search(mood)
    if not m:
        return []
    return [p.strip() for p in _SPLIT_PATTERN.split(m.group(1)) if len(p.strip()) > 1]


def print_dry_run(result: dict, count: int) -> None:
    print()
    print("─" * 60)
    print(f"  Playlist: {result['playlist_name']}")
    if result["genre"]:
        print(f"  Genre:    {result['genre']}")
    print(f"  Tracks:   {len(result['tracks'])} of {count} requested")
    print("─" * 60)
    print()
    for i, t in enumerate(result["tracks"], 1):
        tag = f" [{t['tag']}]" if t.get("tag") else ""
        print(f"  {i:>2}.{tag} {t['artist']} – {t['title']}")
    print()
    print("(dry run — Spotify was not contacted)")


# ------------------------------------------------------------------ generate

def generate(mood: str, count: int,
             avoid: list[dict] | None = None,
             deep_cuts: bool = False,
             on_event=None) -> dict:
    avoid = avoid or []

    def emit(kind, **data):
        if on_event:
            on_event({"event": kind, **data})

    if count > 10000:
        count = 10000

    if not get_setting("deepseek_api_key"):
        raise RuntimeError("DeepSeek API key not configured.")

    emit("checking_keys")
    lastfm = LastFM()

    hard = extract_hard_artists(mood)

    emit("parse_started")
    parsed = parse_mood(mood)
    emit("parsed", artists=parsed["artists"], genres=parsed["genres"],
         language=parsed.get("language", ""))

    raw_artists = parsed["artists"]
    if raw_artists:
        emit("resolve_started", raw=raw_artists,
             language=parsed.get("language", ""),
             genres=parsed["genres"])
        res = resolve_artists(
            raw_artists, mood,
            language=parsed.get("language", ""),
            genres=parsed["genres"],
        )
        resolved_map = res["resolved"]
        canonical = []
        for raw in raw_artists:
            target = resolved_map.get(raw)
            canonical.append(target if target else raw)
        parsed["artists"] = canonical
        emit("resolved", resolved=resolved_map,
             dropped=res["dropped"], canonical=canonical)

    # Fallback for single-word mood that looks like an artist.
    if not parsed["artists"] and not parsed["genres"]:
        stripped = mood.strip()
        if stripped and " " not in stripped:
            emit("parse_fallback", query=stripped)
            probe = lastfm.search_artist(stripped)
            if probe.get("found"):
                parsed["artists"] = [probe["name"]]
                emit("parsed", artists=parsed["artists"],
                     genres=parsed["genres"],
                     language=parsed.get("language", ""))

    # Genre-only: resolve anchor artists.
    parsed["seed_artists"] = []
    if parsed["genres"] and not parsed["artists"]:
        emit("seeds_started", genres=parsed["genres"],
             language=parsed.get("language", ""))
        seeds = resolve_seed_artists(parsed["genres"], parsed.get("language", ""))
        parsed["seed_artists"] = seeds
        emit("seeds", artists=seeds)

    proposal = run_agent(
        mood, count, lastfm,
        hard_artists=hard, parsed=parsed,
        avoid=avoid, deep_cuts=deep_cuts,
        verbose=False, on_event=on_event,
    )

    # Enrich each track with the top Last.fm tag of its artist.
    emit("tagging_start", total=len(proposal["tracks"]))
    tag_cache: dict[str, str] = {}
    for t in proposal["tracks"]:
        artist = t["artist"]
        if artist not in tag_cache:
            try:
                tag_cache[artist] = lastfm.get_artist_top_tag(artist)
            except Exception:
                tag_cache[artist] = ""
        t["tag"] = tag_cache.get(artist, "")

    return {
        "mood": mood,
        "count_requested": count,
        "deep_cuts": deep_cuts,
        "parsed": parsed,
        "playlist_name": proposal["playlist_name"],
        "genre": proposal.get("genre", ""),
        "tracks": proposal["tracks"],
    }


# ------------------------------------------------------------------ commit

def resolve_tracks(sp, candidates, genre, hard, emit=None):
    uris, found, missing = [], [], []
    total = len(candidates)
    for i, t in enumerate(candidates, 1):
        hit = sp.search_track_with_fallback(
            t["title"], t["artist"], genre=genre, allowed=hard or None,
        )
        if not hit:
            missing.append(t)
            if emit:
                emit("spotify_search", i=i, total=total,
                     title=t["title"], artist=t["artist"], hit=False)
            continue
        uris.append(hit["uri"])
        found.append({"title": hit["name"], "artist": hit["artists"][0]["name"],
                      "tag": t.get("tag", "")})
        if emit:
            emit("spotify_search", i=i, total=total,
                 title=hit["name"], artist=hit["artists"][0]["name"], hit=True)
    return uris, found, missing


def fill_missing(sp, missing, found, uris, hard,
                 max_albums_per_artist=3, emit=None):
    if not missing:
        return uris, found, 0
    if emit:
        emit("catalog_start", count=len(missing))
    filled = 0
    seen = set(uris)
    artist_cache: dict = {}
    catalog_cache: dict = {}

    for slot in missing:
        name = slot["artist"]
        if name not in artist_cache:
            artist_cache[name] = sp.search_artist(name)
        artist = artist_cache[name]
        if not artist:
            continue
        if name not in catalog_cache:
            catalog_cache[name] = sp.artist_catalog_tracks(
                artist["id"], max_albums=max_albums_per_artist,
            )
        pool = catalog_cache[name]
        fresh = [t for t in pool if t.get("uri") and t["uri"] not in seen]
        if not fresh:
            continue
        pick = random.choice(fresh)
        uris.append(pick["uri"])
        seen.add(pick["uri"])
        found.append({"title": pick["name"], "artist": artist["name"],
                      "tag": slot.get("tag", "")})
        filled += 1
        if emit:
            emit("catalog_pick", artist=artist["name"], title=pick["name"])
    return uris, found, filled


def commit(proposal: dict, mood: str,
           user_id: str,
           public: bool = False,
           catalog_enabled: bool = True,
           on_event=None) -> dict:
    def emit(kind, **data):
        if on_event:
            on_event({"event": kind, **data})

    from spotify_auth import get_access_token
    from spotify_client import Spotify
    import history

    hard = extract_hard_artists(mood)

    emit("spotify_auth")
    token = get_access_token(user_id)
    sp = Spotify(token)

    tracks = proposal["tracks"]
    genre = proposal.get("genre", "")

    emit("spotify_search_start", total=len(tracks))
    uris, found, missing = resolve_tracks(sp, tracks, genre, hard, emit=emit)

    catalog_filled = 0
    if catalog_enabled:
        uris, found, catalog_filled = fill_missing(
            sp, missing, found, uris, hard, emit=emit,
        )

    if not uris:
        raise RuntimeError("Nothing matched on Spotify.")

    # Compose description: "genre · deep cuts · generated from: mood"
    parts = []
    if genre:
        parts.append(genre)
    if proposal.get("deep_cuts"):
        parts.append("deep cuts")
    parts.append(f"generated from: {mood}")
    description = " · ".join(parts)

    emit("spotify_create")
    playlist = sp.create_playlist(
        proposal["playlist_name"],
        description=description,
        public=public,
    )
    sp.add_items(playlist["id"], uris)

    result = {
        **proposal,
        "public": public,
        "spotify_url": playlist["external_urls"]["spotify"],
        "spotify_playlist_id": playlist["id"],
        "tracks": found,
        "missing": missing,
        "catalog_filled": catalog_filled,
    }

    history.append(user_id, {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mood": mood,
        "count_requested": proposal.get("count_requested"),
        "deep_cuts": proposal.get("deep_cuts", False),
        "parsed": proposal.get("parsed", {}),
        "playlist_name": proposal["playlist_name"],
        "genre": genre,
        "public": public,
        "tracks": found,
        "spotify_url": result["spotify_url"],
        "spotify_playlist_id": result["spotify_playlist_id"],
    })

    emit("final", result=result)
    return result


# ------------------------------------------------------------------ composed

def run(mood: str, count: int,
        dry_run: bool = False,
        catalog_enabled: bool = True,
        deep_cuts: bool = False,
        on_event=None) -> dict:
    proposal = generate(mood, count, deep_cuts=deep_cuts, on_event=on_event)
    if dry_run:
        return {**proposal, "dry_run": True, "spotify_url": None}
    raise RuntimeError("CLI commit requires a user_id — use the web app.")


# --------------------------------------------------------------- CLI

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if len(args) < 2:
        print("Usage: python main.py '<mood>' <count> "
              "[--dry-run] [--deep-cuts] [--json]")
        sys.exit(1)

    mood = args[0]
    try:
        count = int(args[1])
    except ValueError:
        print("track_count must be an integer.")
        sys.exit(1)

    dry_run = "--dry-run" in flags
    deep_cuts = "--deep-cuts" in flags
    json_output = "--json" in flags

    result = run(mood, count, dry_run=dry_run, deep_cuts=deep_cuts)

    if json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if dry_run:
        print_dry_run(result, count)
        return
    print(f"→ Added {len(result['tracks'])} tracks.")
    print(f"→ {result['spotify_url']}")


if __name__ == "__main__":
    main()