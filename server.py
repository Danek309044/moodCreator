"""FastAPI server: UI + API + Spotify OAuth callback, single port."""

import logger
log = logger.get_logger("server")
log.info("moodCreator starting up")

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import settings
import sessions
import history
import previews
import spotify_auth
from main import generate, commit
from validation import validate_mood


ROOT = Path(__file__).parent
STATIC = ROOT / "static"

app = FastAPI(title="moodCreator")

class NoCacheStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers):
        return False  # always re-serve

app.mount("/static", NoCacheStaticFiles(directory=str(STATIC)), name="static")


# --------------------------------------------------------------- helpers


def current_user(request: Request) -> str | None:
    sid = request.cookies.get("sid")
    return sessions.resolve(sid) if sid else None


def require_user(request: Request) -> str:
    uid = current_user(request)
    if not uid:
        raise _RedirectToLogin()
    return uid


class _RedirectToLogin(Exception):
    pass


@app.exception_handler(_RedirectToLogin)
async def _redirect_login(request, exc):
    return RedirectResponse("/login")


# --------------------------------------------------------------- pages

def _needs_setup() -> bool:
    return not settings.is_configured()


@app.get("/")
def index(request: Request):
    if _needs_setup():
        return RedirectResponse("/setup")
    if not current_user(request):
        return RedirectResponse("/login")
    return FileResponse(str(STATIC / "index.html"))


@app.get("/login")
def login_page(request: Request):
    if _needs_setup():
        return RedirectResponse("/setup")
    if current_user(request):
        return RedirectResponse("/")
    return FileResponse(str(STATIC / "login.html"))


@app.get("/history")
def history_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login")
    return FileResponse(str(STATIC / "history.html"))


@app.get("/settings")
def settings_page(request: Request):
    if not current_user(request):
        return RedirectResponse("/login")
    return FileResponse(str(STATIC / "settings.html"))


@app.get("/setup")
def setup_page(request: Request):
    # Setup is only accessible before keys are configured, or by the admin.
    if settings.is_configured():
        uid = current_user(request)
        if not uid or uid != settings.admin_user_id():
            return RedirectResponse("/")
    return FileResponse(str(STATIC / "setup.html"))


# --------------------------------------------------------------- state

@app.get("/api/state")
def state(request: Request):
    uid = current_user(request)
    s = settings.load()
    profile = spotify_auth.load_profile(uid) if uid else None
    return {
        "configured": settings.is_configured(),
        "authed": bool(uid),
        "user_id": uid,
        "profile": profile,
        "is_admin": bool(uid and uid == settings.admin_user_id()),
        "spotify_client_id_set": bool(s.get("spotify_client_id")),
        "redirect_uri": settings.get_redirect_uri(),
        "redirect_uri_explicit": settings.get_explicit_redirect_uri(),
    }


class SetupBody(BaseModel):
    spotify_client_id: str
    deepseek_api_key: str
    lastfm_api_key: str
    redirect_uri: str = ""


@app.post("/api/setup")
def do_setup(body: SetupBody, request: Request):
    if settings.is_configured():
        uid = current_user(request)
        if not uid or uid != settings.admin_user_id():
            return JSONResponse({"error": "not authorized"}, status_code=403)

    current = settings.load()
    current.update({
        "spotify_client_id": body.spotify_client_id.strip(),
        "deepseek_api_key":  body.deepseek_api_key.strip(),
        "lastfm_api_key":    body.lastfm_api_key.strip(),
    })
    if body.redirect_uri.strip():
        current["redirect_uri"] = body.redirect_uri.strip()
    elif "redirect_uri" in current and not body.redirect_uri.strip():
        # Allow clearing the override.
        current.pop("redirect_uri", None)
    settings.save(current)
    return {"ok": True}


@app.get("/api/stats")
def api_stats(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return history.stats_for_user(uid)


@app.get("/api/admin/stats")
def api_admin_stats(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    if uid != settings.admin_user_id():
        return JSONResponse({"error": "not authorized"}, status_code=403)
    return history.stats_for_all()

# --------------------------------------------------------------- oauth

@app.get("/auth/start")
def auth_start(request: Request):
    explicit = settings.get_explicit_redirect_uri()
    if explicit:
        uri = explicit
    else:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or "127.0.0.1:4444"
        )
        uri = f"{scheme}://{host}/callback"
    return RedirectResponse(spotify_auth.begin_auth(uri))

@app.get("/callback")
def auth_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    err = request.query_params.get("error")
    if err:
        return HTMLResponse(
            f"<h2>Spotify error: {err}</h2><p><a href='/login'>Back</a></p>",
            status_code=400,
        )
    try:
        user_id, profile = spotify_auth.finish_auth(code, state)
    except Exception as e:
        return HTMLResponse(
            f"<h2>Auth failed</h2><pre>{e}</pre>"
            f"<p><a href='/login'>Back</a></p>",
            status_code=400,
        )

    # First-ever user becomes the admin.
    if not settings.admin_user_id():
        settings.set_admin(user_id)

    sid = sessions.create(user_id)
    resp = RedirectResponse("/")
    resp.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=30*24*3600)
    return resp


@app.get("/auth/logout")
def auth_logout(request: Request):
    sid = request.cookies.get("sid")
    if sid:
        sessions.destroy(sid)
    resp = RedirectResponse("/login")
    resp.delete_cookie("sid")
    return resp


# --------------------------------------------------------------- validation

class ValidateBody(BaseModel):
    mood: str


@app.post("/api/validate")
def validate(body: ValidateBody):
    ok, reason = validate_mood(body.mood)
    return {"ok": ok, "reason": reason}


# --------------------------------------------------------------- streaming

def _sse(worker):
    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(evt):
            loop.call_soon_threadsafe(queue.put_nowait, evt)

        def run_worker():
            try:
                worker(emit)
            except Exception as e:
                emit({"event": "error", "message": str(e)})
            finally:
                emit({"event": "done"})

        threading.Thread(target=run_worker, daemon=True).start()

        while True:
            evt = await queue.get()
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            if evt["event"] == "done":
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


class PreviewBody(BaseModel):
    mood: str
    count: int
    avoid: list[dict] | None = None
    deep_cuts: bool = False
    public: bool = False


@app.post("/api/preview")
def preview(body: PreviewBody, request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)

    ok, reason = validate_mood(body.mood)
    if not ok:
        def err_worker(emit):
            emit({"event": "error", "message": reason})
        return _sse(err_worker)

    def worker(emit):
        proposal = generate(
            body.mood, body.count,
            avoid=body.avoid or [],
            deep_cuts=body.deep_cuts,
            public=body.public,
            on_event=emit,
        )
        previews.record(uid)
        previews.save_latest(uid, proposal)
        emit({"event": "final", "result": proposal})

    return _sse(worker)


@app.get("/api/preview/latest")
def preview_latest(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return {"proposal": previews.load_latest(uid)}


class PreviewDeleteBody(BaseModel):
    pass  # empty body; kept for symmetry with other POST endpoints


@app.post("/api/preview/clear")
def preview_clear(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    previews.clear_latest(uid)
    return {"ok": True}

class CreateBody(BaseModel):
    proposal: dict
    mood: str


@app.post("/api/create")
def create(body: CreateBody, request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)

    def worker(emit):
        commit(body.proposal, body.mood, user_id=uid, on_event=emit)

    return _sse(worker)


# --------------------------------------------------------------- history

@app.get("/api/history")
def api_history(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return {"entries": history.list_for_user(uid, limit=50)}


class DeleteEntryBody(BaseModel):
    ts: str


@app.post("/api/history/delete")
def api_history_delete(body: DeleteEntryBody, request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    history.delete_entry(uid, body.ts)
    return {"ok": True}


@app.post("/api/history/clear")
def api_history_clear(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    history.delete_all(uid)
    previews.clear_latest(uid)
    return {"ok": True}


class RecreateBody(BaseModel):
    ts: str


@app.post("/api/history/recreate")
def api_history_recreate(body: RecreateBody, request: Request):
    """Re-create a past playlist by replaying its stored proposal."""
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)

    entries = history.list_for_user(uid, limit=10_000)
    entry = next((e for e in entries if e.get("ts") == body.ts), None)
    if not entry or not entry.get("tracks"):
        return JSONResponse({"error": "entry not found or has no tracks"},
                            status_code=404)

    proposal = {
        "playlist_name": entry.get("playlist_name", "Recreated Playlist"),
        "genre": entry.get("genre", ""),
        "tracks": entry["tracks"],
        "count_requested": len(entry["tracks"]),
        "parsed": entry.get("parsed", {}),
        "deep_cuts": entry.get("deep_cuts", False),
        "public": entry.get("public", False),
    }

    def worker(emit):
        commit(proposal, entry.get("mood", ""), user_id=uid, on_event=emit)
        # Remove the original entry now that a fresh playlist was created.
        history.delete_entry(uid, body.ts)

    return _sse(worker)

# --------------------------------------------------------------- account

@app.post("/api/account/delete")
def api_account_delete(request: Request):
    uid = current_user(request)
    if not uid:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    spotify_auth.clear_tokens(uid)
    sessions.destroy_all_for_user(uid)
    history.delete_all(uid)
    previews.delete_all(uid)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sid")
    return resp


@app.post("/api/account/logout")
def api_account_logout(request: Request):
    sid = request.cookies.get("sid")
    if sid:
        sessions.destroy(sid)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sid")
    return resp