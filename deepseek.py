"""DeepSeek agent with Last.fm tool calling.

The model NEVER invents track names. It orchestrates Last.fm lookups.

Multilingual: parse detects the language of the request (Czech, Russian,
Chinese, whatever) and the seed-artist resolver uses it verbatim. No hardcoded
language list — the model drives it.
"""

import json
import random

import requests
from openai import OpenAI

from settings import get as get_setting


MODEL = "deepseek-chat"
MAX_STEPS = 12


def _tool_budget(count: int) -> int:
    if count <= 10:
        return 10
    if count <= 30:
        return 16
    return 24


_client_cache: dict = {}


def _client() -> OpenAI:
    key = get_setting("deepseek_api_key")
    if not key:
        raise RuntimeError("DeepSeek API key not configured.")
    if key not in _client_cache:
        _client_cache[key] = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    return _client_cache[key]


def _post(payload: dict) -> dict:
    key = get_setting("deepseek_api_key")
    if not key:
        raise RuntimeError("DeepSeek API key not configured.")
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _norm(title: str, artist: str) -> tuple[str, str]:
    return (title.lower().strip(), artist.lower().strip())


def _is_useful(result) -> bool:
    if isinstance(result, list):
        return len(result) > 0
    if isinstance(result, dict):
        if result.get("error"):
            return False
        if result.get("found") is False:
            return False
    return True


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_artist",
            "description": "Resolve an artist NAME to a canonical Last.fm artist. Do NOT use this for genres.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_artist_top_tracks",
            "description": "Most-played tracks for a Last.fm artist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                },
                "required": ["artist"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar_artists",
            "description": "Similar artists. Best tool for exploring a genre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
                },
                "required": ["artist"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar_tracks",
            "description": "Tracks similar to a seed track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "track": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
                },
                "required": ["artist", "track"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_artist_tags",
            "description": "Community genre/mood tags for an artist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 15},
                },
                "required": ["artist"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_playlist",
            "description": "Call exactly once, at the end. Tracks must come from prior tool results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist_name": {"type": "string"},
                    "genre": {"type": "string"},
                    "tracks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "artist": {"type": "string"},
                            },
                            "required": ["title", "artist"],
                        },
                    },
                },
                "required": ["playlist_name", "tracks"],
            },
        },
    },
]


SYSTEM = """You are a music curator agent with Last.fm tools.

YOUR JOB: build a playlist of exactly N tracks matching the user's request.

CORE RULES:
1. NEVER invent a track name. Only use tracks returned by tool results.
2. Call each tool AT MOST ONCE with the same arguments.
3. FILLER WORDS ARE NOT ARTISTS: mood, vibe, style, sound, type, kind, feat,
   like, similar, some, stuff, playlist, song, track, old, new, chill, sad,
   hype, calm, and any adjective. This applies to filler words in ANY language.
4. NEVER call search_artist on a GENRE NAME, in any language. Genres
   (rap, jazz, house, drill, dnb, and their non-English equivalents) are not
   artists. If you need to explore a genre, use the anchor artists provided in
   the prompt as seeds, then call get_similar_artists or
   get_artist_top_tracks on them.
5. Submit EXACTLY the target number of tracks. If you cannot reach the target,
   submit FEWER — never pad.
6. Call submit_playlist ONCE and stop.
7. If the user says to avoid certain tracks, do NOT submit any of them.
8. VARY THE DISTRIBUTION. Do not force a strict 50/50 split.
9. SUBMIT EARLY WHEN STUCK. If tools return empty and you have usable tracks,
   submit immediately rather than searching further.

WORKFLOW:
- Named artists AND a genre:
    1. get_artist_top_tracks for each named artist.
    2. get_similar_artists on ONE named artist.
    3. get_artist_top_tracks for 1-3 of the closest matches.
    4. Blend without forcing a fixed ratio.
- Named artists only:
    - small: just the artists; medium/large: add 2-4 similar artists.
- Genre only (no artists named):
    1. The prompt gives you ANCHOR ARTISTS for the genre. Use them directly
       with get_artist_top_tracks.
    2. Optionally get_similar_artists on ONE anchor to expand.
    3. Do NOT call search_artist on the genre itself.
- Pure mood (no genre, no artists):
    - Interpret the mood, pick an anchor artist who fits, explore from there.

LANGUAGE AND SCRIPT:
- The user may write in any language. Artist names may use any script.
  Pass names through to Last.fm exactly as the user wrote them — Last.fm
  indexes native scripts for most artists.
- If the user's request implies a language or region (e.g. "сz rap",
  "русский рэп", "中文爵士", "deutscher rap"), the anchor artists you receive
  will already be from that region. Trust them.

BUDGET: wasted calls cost you tracks.
"""


# --------------------------------------------------------------- parse pass

_PARSE_FILLER = (
    # generic English fillers
    "mood, vibe, vibes, style, sound, type, kind, some, stuff, playlist, mix, "
    "song, songs, track, tracks, like, similar, featuring, feat, ft, only, with, "
    "and, or, the, a, an, my, me, i, want, need, give, make, music, please, "
    # descriptors
    "old, new, early, late, classic, modern, young, recent, "
    "chill, sad, happy, dark, energetic, calm, hype, soft, hard, mellow, "
    # generic nouns
    "artists, artist, band, bands, rapper, rappers, singer, singers"
)


def parse_mood(mood: str) -> dict:
    """
    Extract raw artist tokens, genres, and language.

    Artists are returned as the user wrote them — no canonicalization.
    Resolution happens in resolve_artists() with full context.
    """
    if not mood.strip():
        return {"artists": [], "genres": [], "language": ""}

    user = f"""Extract structured info from a music playlist request.

Request: "{mood}"

Return JSON with this exact shape:
{{
  "artists": ["artist mentions as the user wrote them"],
  "genres": ["genre names"],
  "language": "language implied by the request, in English — e.g. 'Czech', 'Russian', 'Chinese'. Empty if none."
}}

ARTISTS:
- Return the artist names EXACTLY as the user wrote them (nicknames, short
  forms, misspellings — leave them alone). Do NOT try to canonicalize.
  Example: "yzo a ptk" -> ["yzo", "ptk"]  (NOT ["Yzomandias", "PTK"])
- Strip filler words, connecting words ("a", "and", "y", "+"), and adjectives.
- If the user names three artists in a row, return three entries.
- If nothing looks like an artist, return [].

GENRES:
- Return style labels in English: rap, trap, jazz, house, drill, etc.
- "рэп" -> "rap".  "爵士" -> "jazz".  "ロック" -> "rock".

LANGUAGE:
- Detect any language/region modifier. Examples:
    cesky / český / ceska      -> "Czech"
    slovensky                  -> "Slovak"
    deutsch / nemecky          -> "German"
    русский / rus              -> "Russian"
    中文 / 汉语                 -> "Chinese"
    日本 / 日本語               -> "Japanese"
    한국어                      -> "Korean"
    العربية                    -> "Arabic"
    español / spanelsky        -> "Spanish"
- If the request is written in a non-English language, that language is
  implied even without an explicit modifier.

IGNORE these fillers in every language:
  {_PARSE_FILLER}

If nothing is confidently identifiable, return empty lists. Do NOT guess.
"""
    try:
        body = _post({
            "model": MODEL,
            "messages": [{"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 250,
        })
        data = json.loads(body["choices"][0]["message"]["content"])
        return {
            "artists":  [a for a in data.get("artists", []) if isinstance(a, str)],
            "genres":   [g for g in data.get("genres", []) if isinstance(g, str)],
            "language": (data.get("language") or "").strip(),
        }
    except Exception:
        return {"artists": [], "genres": [], "language": ""}

def resolve_artists(raw_artists: list[str], original_mood: str,
                    language: str = "", genres: list[str] | None = None) -> dict:
    """
    Given raw artist tokens and the full original mood, ask DeepSeek to
    resolve each one with context.

    Returns {"resolved": {"raw": "canonical"}, "dropped": ["token", ...]}.
    """
    if not raw_artists:
        return {"resolved": {}, "dropped": []}

    genres = genres or []
    context_bits = []
    if language:
        context_bits.append(f"language/region: {language}")
    if genres:
        context_bits.append(f"genre(s): {', '.join(genres)}")
    context = "; ".join(context_bits) if context_bits else "(none detected)"

    user = f"""A user asked for a music playlist with this request:

  "{original_mood}"

Detected context: {context}

They mentioned these artist names (exactly as written):
  {json.dumps(raw_artists, ensure_ascii=False)}

For EACH mentioned name, determine the real artist the user meant, GIVEN THE
CONTEXT. Return the exact spelling used on Last.fm's artist page — including
any special characters, dollar signs, diacritics, and capitalisation.

Return JSON with this exact shape:
{{
  "resolved": {{"raw name": "Canonical Last.fm name or empty string"}},
  "dropped": ["raw name", ...]
}}

Rules:
- Spelling matters. Last.fm's search index is strict. Examples:
    "casanova bulhar" in Czech rap -> "CA$HANOVA BULHAR"
    "yzo" in Czech rap             -> "Yzomandias"
    "ptk" in Czech rap             -> "PTK"
    "tom odell"                    -> "Tom Odell"
    "a$ap rocky"                   -> "A$AP Rocky"
    "don" (any rap)                -> "Don Toliver"
- For artists whose names include $, £, diacritics, or unusual case,
  output the exact stylization. Do NOT normalise to plain ASCII.
- If a name clearly isn't an artist (filler, adjective, genre, connecting
  word), put it in "dropped" with an empty string in "resolved".
- If you genuinely don't know who the user means, put the raw name in
  "dropped" rather than guessing.
"""
    try:
        body = _post({
            "model": MODEL,
            "messages": [{"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 300,
        })
        data = json.loads(body["choices"][0]["message"]["content"])
        resolved = {}
        for k, v in (data.get("resolved") or {}).items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                resolved[k] = v.strip()
        dropped = [d for d in (data.get("dropped") or []) if isinstance(d, str)]
        return {"resolved": resolved, "dropped": dropped}
    except Exception:
        return {"resolved": {}, "dropped": list(raw_artists)}


def resolve_seed_artists(genres: list[str], language: str = "") -> list[str]:
    """
    Focused call: given genres and an optional language, return 3-5 well-known
    seed artists. Kept separate from parse_mood so the LLM has no distractions.

    No language is hardcoded — whatever string parse_mood returned is used
    verbatim in the prompt.
    """
    if not genres:
        return []

    genre_str = ", ".join(genres)
    if language:
        ask = (
            f"Name 5 well-known artists who perform {genre_str} music "
            f"primarily in {language}. They must actually work in {language} — "
            f"not English-language artists who happen to make this genre."
        )
    else:
        ask = f"Name 5 well-known {genre_str} artists."

    user = f"""{ask}

Return JSON:
{{"artists": ["Artist One", "Artist Two", "Artist Three", "Artist Four", "Artist Five"]}}

Rules:
- Only real, established artists.
- Mix legendary and current.
- Use the artist's most common spelling (native script if they perform in a
  non-Latin script; Latin spelling otherwise).
- If you don't know any artists for this language + genre combination, return
  {{"artists": []}}. Do not fall back to English-language artists.
"""
    try:
        body = _post({
            "model": MODEL,
            "messages": [{"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": 200,
        })
        data = json.loads(body["choices"][0]["message"]["content"])
        return [a for a in data.get("artists", []) if isinstance(a, str)][:5]
    except Exception:
        return []


# ------------------------------------------------------------ agent driver

def _exec_tool(lastfm, name: str, args: dict, avoid_keys: set):
    if name == "search_artist":
        return lastfm.search_artist(**args)
    if name == "get_artist_top_tracks":
        result = lastfm.get_artist_top_tracks(**args)
        if avoid_keys:
            result = [t for t in result
                      if _norm(t["title"], t["artist"]) not in avoid_keys]
        return result
    if name == "get_similar_artists":
        return lastfm.get_similar_artists(**args)
    if name == "get_similar_tracks":
        result = lastfm.get_similar_tracks(**args)
        if avoid_keys:
            result = [t for t in result
                      if _norm(t["title"], t["artist"]) not in avoid_keys]
        return result
    if name == "get_artist_tags":
        return lastfm.get_artist_tags(**args)
    raise ValueError(f"Unknown tool: {name}")


def _build_user_prompt(mood, count, named_artists, named_genres,
                       seed_artists, hard_artists, avoid, deep_cuts, language):
    parts = [f"Build a playlist for: {mood}", f"Target track count: {count}"]

    if language:
        parts.append(f"Language / region: {language}")

    if deep_cuts:
        parts.append(
            "\nDEEP CUTS: ON. When picking tracks for a named artist, "
            "STRONGLY prefer positions 5-40 of their top tracks over the "
            "top 3 singles."
        )
    else:
        parts.append(
            "\nDEEP CUTS: OFF. Prefer each artist's most popular tracks."
        )

    if named_artists:
        parts.append(f"\nNamed artists (canonical): {', '.join(named_artists)}")
    if named_genres:
        parts.append(f"Named genres: {', '.join(named_genres)}")

    # Genre-only requests: anchors are essential.
    if named_genres and not named_artists and seed_artists:
        parts.append(
            f"\nANCHOR ARTISTS for these genres (use these — do NOT call "
            f"search_artist on the genre name itself): {', '.join(seed_artists)}"
        )
        parts.append(
            "Workflow: call get_artist_top_tracks on each anchor, then "
            "get_similar_artists on the strongest anchor to expand the scene."
        )

    if named_artists and named_genres:
        parts.append(
            "\nBLENDED request. Include a mix of the named artists and artists "
            f"from {' / '.join(named_genres)}. Don't drop either side entirely."
        )
    elif named_artists and count <= 10:
        parts.append("\nSmall artist-specific request. Stay focused.")

    if hard_artists:
        parts.append(
            f"\nHARD CONSTRAINT: only tracks by {', '.join(hard_artists)}. "
            f"Use limit=50 on get_artist_top_tracks."
        )
    if avoid:
        preview = "; ".join(f"{t['artist']} - {t['title']}" for t in avoid[:15])
        parts.append(
            f"\nAVOID {len(avoid)} previously-suggested track(s). "
            f"The first few:\n  {preview}"
        )
        if len(avoid) > 15:
            parts.append(f"  ... and {len(avoid) - 15} more")
        parts.append(
            "If filtered results don't leave enough for the target count, "
            "submit whatever you can find rather than looping."
        )
    return "\n".join(parts)


def run_agent(mood: str, count: int, lastfm,
              hard_artists: list[str] | None = None,
              parsed: dict | None = None,
              avoid: list[dict] | None = None,
              deep_cuts: bool = False,
              verbose: bool = True,
              on_event=None) -> dict:
    hard_artists = hard_artists or []
    parsed = parsed or {}
    avoid = avoid or []
    named_artists = parsed.get("artists", []) or []
    named_genres = parsed.get("genres", []) or []
    seed_artists = parsed.get("seed_artists", []) or []
    language = parsed.get("language", "")

    avoid_keys = {_norm(t["title"], t["artist"]) for t in avoid}

    budget = _tool_budget(count)
    calls_used = 0
    call_cache: dict = {}
    empty_streak = 0
    useful_results = 0
    last_chance_sent = False

    def emit(kind, **data):
        if on_event:
            on_event({"event": kind, **data})

    user = _build_user_prompt(mood, count, named_artists, named_genres,
                              seed_artists, hard_artists, avoid, deep_cuts,
                              language)

    if verbose:
        print(f"  [agent] tool budget: {budget} calls")
        if avoid_keys:
            print(f"  [agent] avoiding {len(avoid_keys)} track(s)")

    emit("agent_started", budget=budget,
         artists=named_artists, genres=named_genres,
         seed_artists=seed_artists, language=language,
         avoid_count=len(avoid_keys), deep_cuts=deep_cuts)

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]

    for step in range(MAX_STEPS):
        if step == MAX_STEPS - 2 and useful_results == 0 and not last_chance_sent:
            last_chance_sent = True
            emit("last_chance")
            messages.append({
                "role": "user",
                "content": (
                    "You are out of usable results and running out of steps. "
                    "Call submit_playlist NOW, even with an empty list."
                ),
            })

        response = _client().chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=1.0,
        )
        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            messages.append({
                "role": "user",
                "content": "Call submit_playlist now with what you have.",
            })
            continue

        submitted = None
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}

            if name == "submit_playlist":
                submitted = args
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"status": "received"}),
                })
                continue

            cache_key = (name, json.dumps(args, sort_keys=True))
            if cache_key in call_cache:
                emit("tool_cached", name=name, args=args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(call_cache[cache_key], ensure_ascii=False),
                })
                continue

            calls_used += 1
            if calls_used > budget:
                emit("budget_exceeded", used=calls_used, budget=budget)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"error": "Budget exceeded. Submit now."}),
                })
                continue

            try:
                result = _exec_tool(lastfm, name, args, avoid_keys)
            except Exception as e:
                result = {"error": str(e)}

            call_cache[cache_key] = result

            if _is_useful(result):
                useful_results += 1
                empty_streak = 0
            else:
                empty_streak += 1

            summary = _fmt_result(result)
            emit("tool", step=calls_used, budget=budget,
                 name=name, args=args, summary=summary)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        if submitted is not None:
            raw = submitted.get("tracks") or []

            seen = set()
            tracks = []
            avoided_hits = 0
            for t in raw:
                if not isinstance(t, dict) or "title" not in t or "artist" not in t:
                    continue
                k = _norm(t["title"], t["artist"])
                if k in seen:
                    continue
                if k in avoid_keys:
                    avoided_hits += 1
                    continue
                seen.add(k)
                tracks.append(t)

            if avoided_hits:
                emit("avoided_filtered", count=avoided_hits)

            if len(tracks) > count:
                tracks = tracks[:count]

            random.shuffle(tracks)

            emit("agent_submitted", count=len(tracks),
                 playlist_name=submitted.get("playlist_name", "Untitled"))
            return {
                "playlist_name": submitted.get("playlist_name", "Untitled"),
                "genre": submitted.get("genre", ""),
                "tracks": tracks,
            }

        if empty_streak >= 4:
            emit("empty_streak_nudge", streak=empty_streak)
            messages.append({
                "role": "user",
                "content": (
                    "Tools are returning empty or filtered-out results. "
                    "Call submit_playlist now with whatever you already have."
                ),
            })
            empty_streak = 0

    if useful_results == 0:
        raise RuntimeError(
            "No usable results from Last.fm. The mood may not match any "
            "artist, or your Last.fm API key may be invalid."
        )
    raise RuntimeError(
        f"Agent did not submit within {MAX_STEPS} steps "
        f"({useful_results} useful results, {calls_used} tool calls used)."
    )


def _fmt_result(r) -> str:
    if isinstance(r, list):
        return f"{len(r)} items"
    if isinstance(r, dict):
        if r.get("error"):
            return f"error: {str(r['error'])[:50]}"
        if "found" in r and not r["found"]:
            return "not found"
        return "ok"
    return "?"