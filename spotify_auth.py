"""Spotify Authorization Code with PKCE — one token per user."""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

import requests

from settings import get as get_setting, get_redirect_uri
from config import TOKENS_DIR, SPOTIFY_SCOPES


AUTH_URL  = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
ME_URL    = "https://api.spotify.com/v1/me"


def _client_id() -> str:
    cid = get_setting("spotify_client_id")
    if not cid:
        raise RuntimeError("Spotify Client ID not configured.")
    return cid


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _token_path(user_id: str) -> str:
    return os.path.join(TOKENS_DIR, f"{user_id}.json")


def save_tokens(user_id: str, tokens: dict, profile: dict | None = None) -> None:
    tokens["expires_at"] = time.time() + tokens["expires_in"] - 60
    if profile is not None:
        tokens["_profile"] = profile
    else:
        existing = load_tokens(user_id)
        if existing and existing.get("_profile"):
            tokens["_profile"] = existing["_profile"]
    with open(_token_path(user_id), "w") as f:
        json.dump(tokens, f)
    try:
        os.chmod(_token_path(user_id), 0o600)
    except OSError:
        pass


def load_tokens(user_id: str) -> dict | None:
    p = _token_path(user_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_tokens(user_id: str) -> None:
    try:
        os.remove(_token_path(user_id))
    except OSError:
        pass


def is_authed(user_id: str) -> bool:
    t = load_tokens(user_id)
    return bool(t and (t.get("refresh_token") or t.get("access_token")))


def load_profile(user_id: str) -> dict | None:
    tokens = load_tokens(user_id)
    return tokens.get("_profile") if tokens else None


def _refresh(user_id: str, refresh_token: str) -> dict:
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     _client_id(),
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    data.setdefault("refresh_token", refresh_token)
    save_tokens(user_id, data)
    return data


def get_access_token(user_id: str) -> str:
    tokens = load_tokens(user_id)
    if tokens and tokens.get("expires_at", 0) > time.time():
        return tokens["access_token"]
    if tokens and tokens.get("refresh_token"):
        new = _refresh(user_id, tokens["refresh_token"])
        return new["access_token"]
    raise RuntimeError(
        f"No valid Spotify token for user {user_id}. Please log in again."
    )


# ------------------------------------------------------------ web PKCE

# state -> {"verifier": str, "redirect_uri": str}
_pending_states: dict[str, dict] = {}


def begin_auth(redirect_uri: str | None = None) -> str:
    uri = redirect_uri or get_redirect_uri()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    _pending_states[state] = {"verifier": verifier, "redirect_uri": uri}

    params = {
        "client_id":             _client_id(),
        "response_type":         "code",
        "redirect_uri":          uri,
        "scope":                 SPOTIFY_SCOPES,
        "code_challenge_method": "S256",
        "code_challenge":        challenge,
        "state":                 state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def finish_auth(code: str, state: str) -> tuple[str, dict]:
    entry = _pending_states.pop(state, None)
    if not entry:
        raise RuntimeError("State mismatch — possible CSRF or expired session.")

    verifier = entry["verifier"]
    redirect_uri = entry["redirect_uri"]

    r = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  redirect_uri,
        "client_id":     _client_id(),
        "code_verifier": verifier,
    }, timeout=30)
    r.raise_for_status()
    tokens = r.json()

    access = tokens["access_token"]
    me = requests.get(ME_URL, headers={
        "Authorization": f"Bearer {access}",
    }, timeout=30)
    me.raise_for_status()
    profile = me.json()
    user_id = profile["id"]

    profile_data = {
        "display_name": profile.get("display_name") or user_id,
        "image": (profile.get("images") or [{}])[0].get("url"),
    }
    save_tokens(user_id, tokens, profile_data)
    return user_id, profile