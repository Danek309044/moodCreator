# moodCreator

Turn a text description into a Spotify playlist.

Type a mood, an artist, a genre, or any mix. The app uses DeepSeek and
Last.fm to find real tracks that match, shows you a preview, and creates
the playlist on your Spotify account when you're happy with it.

Examples that work:

- `chill rap with drake`
- `british indie rock`
- `chill jazz for a rainy day`
- `90s hip hop`

---

## Features

- **Free-form input.** No genre dropdowns, no fixed mood list. Write what
  you want in plain language, in any language.
- **Context-aware artist resolution.** Nicknames and short forms get
  resolved against the mood. `travis` in a rap request becomes
  `Travis Scott`, `don` becomes `Don Toliver`. Same word in a different
  context stays as-is.
- **Real tracks, not hallucinations.** The LLM orchestrates Last.fm
  lookups. It never invents track names.
- **Preview before commit.** Edit the playlist name, remove tracks you
  don't want, regenerate if you don't like it, and only create the
  playlist when you're satisfied.
- **Private or public.** Toggle per playlist.
- **Deep cuts mode.** Prefer lesser-known tracks over an artist's hits.
- **History.** Every playlist you create is saved. One-click recreate if
  you deleted the original.
- **Cross-device.** Sessions, tokens, and history are per-user. Log in
  from your phone and your PC and see the same state.
- **Self-hosted.** No accounts, no telemetry, no cloud service. Everything
  runs on your machine.

---

## How it works

Three external services are involved:

1. **DeepSeek** — parses your mood, resolves artist names, orchestrates
   tool calls.
2. **Last.fm** — provides the actual track data. The agent queries it
   with structured tools and picks from what comes back.
3. **Spotify** — receives the final playlist.

None of these are optional. You need your own API key for each.

The pipeline in short:

    mood → parse → resolve artists → agent explores Last.fm
         → preview → create on Spotify

The LLM never generates a track name. Every track comes from a Last.fm
tool call.

---

## Requirements

- **Python 3.10 or newer** (for the native install)
- **Docker** (for the container install — see below)
- A **Spotify Developer app** — [create one here](https://developer.spotify.com/dashboard)
- A **DeepSeek API key** — [platform.deepseek.com](https://platform.deepseek.com)
- A **Last.fm API key** — [last.fm/api/account/create](https://www.last.fm/api/account/create)

All three are free to sign up. The Spotify app is free and doesn't
require Premium. DeepSeek charges per token but their chat model is
cheap enough that personal use costs cents per month.

---

## Setup

### 1. Create a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app. Any name and description.
3. Add this redirect URI exactly:

       http://127.0.0.1:4444/callback

4. Under **Users and Access**, add the email of every Spotify account
   you want to allow. Dev-mode apps are capped at 25 users. For personal
   use that's more than enough.
5. Copy the **Client ID**. You'll paste it into the setup page.

If you plan to run this behind a reverse proxy (homelab, VPS), also
register `https://your-domain.com/callback` and set the redirect URI
explicitly in the app's setup page.

### 2. Install

**Option A — Docker (recommended)**

No Python needed. Just Docker.

    docker compose up -d

Open http://127.0.0.1:4444/.

**Option B — Native (Windows)**

    start.bat

First run creates a virtual environment, installs dependencies, and
starts the server. `stop.bat` shuts it down cleanly.

**Option C — Native (Linux / macOS)**

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python -m uvicorn server:app --host 0.0.0.0 --port 4444

### 3. First-run configuration

Open http://127.0.0.1:4444/ in your browser.

- If this is your first time, you'll be redirected to `/setup`.
- Paste your Spotify Client ID, DeepSeek API key, and Last.fm API key.
- Optionally set a redirect URI if you're using a reverse proxy.
- Save. You'll be redirected to `/login`.
- Click **Continue with Spotify**. The first user to log in becomes the
  admin.

Done.

---

## Usage

1. Type a mood, artist, genre, or any combination into the input.
2. Pick a track count (5 to 100).
3. Toggle **Deep Cuts** if you want lesser-known tracks.
4. Toggle **Public Playlist** if you want it visible on your profile.
5. Press Enter or click **Generate Playlist**.
6. Watch the stream log as the agent explores Last.fm.
7. Review the preview. Remove tracks you don't like.
8. Click **Create Playlist**.

The playlist appears in your Spotify account. The URL is shown on the
result screen.

### Keyboard shortcuts

- `Enter` in the mood field — generate
- `Escape` — cancel a running generation
- `Enter` on the playlist name — confirm rename

---

## Deployment

### Docker

The container image is built automatically on GitHub and pushed to
GitHub Container Registry on every push to `main`.

**Run the prebuilt image:**

    docker run -d \
      --name moodcreator \
      -p 4444:4444 \
      -v ${PWD}/data:/app/data \
      --restart unless-stopped \
      ghcr.io/danek309044/moodcreator:latest

On Linux/macOS, use `$(pwd)/data` instead of `${PWD}/data`.

**Or with Compose:**

Create `docker-compose.yml`:

    services:
      moodcreator:
        image: ghcr.io/danek309044/moodcreator:latest
        container_name: moodcreator
        ports:
          - "4444:4444"
        volumes:
          - ./data:/app/data
        restart: unless-stopped
        environment:
          - TZ=Europe/Prague

Then:

    docker compose up -d

**Or build from source:**

    git clone https://github.com/Danek309044/moodCreator.git
    cd moodCreator
    docker compose up -d --build

All runtime state lives in `./data` on the host and is mounted into the
container, so tokens, history, and previews survive container rebuilds.

### Behind a reverse proxy

Spotify only accepts HTTPS for non-loopback redirect URIs, so for
network access you need a proxy that terminates TLS. Caddy example:

    mood.yourdomain.com {
        reverse_proxy 10.10.1.100:4444 {
            header_up X-Forwarded-Proto {scheme}
            header_up X-Forwarded-Host {host}
        }
    }

Then in `/setup`, set the Redirect URI explicitly to
`https://mood.yourdomain.com/callback` and register that URL in the
Spotify dashboard.

Cloudflare Tunnel works as an alternative:

    cloudflared tunnel --url http://127.0.0.1:4444

Copy the trycloudflare.com URL, register `.../callback` in Spotify, and
paste it into the setup form.

---

## Configuration

Runtime state lives under `data/`:

    data/settings.json                       API keys and configuration
    data/tokens/{user_id}.json               per-user Spotify tokens
    data/history/{user_id}.jsonl             playlist history
    data/previews/{user_id}_latest.json      last preview, cross-device
    data/sessions.json                       session cookie → user mapping
    data/app.log                             application log

**Do not commit `data/`.** It contains plaintext API keys.

### Factory reset

    python reset.py

Or delete `data/` — it's recreated on next start.

---

## Troubleshooting

### Public playlist created as private

Spotify has an account-level default that forces new playlists private,
regardless of what the API requests. The API returns success either way,
so this can be confusing.

The setting is only available in the **mobile Spotify app** (as of the
current version). It isn't exposed on the web player or the desktop app.

- **Mobile app:** Settings → Privacy and Sharing → Playlist visibility
  (or the localised equivalent — "Soukromí a sdílení" in Czech,
  "Privatsphäre und Freigabe" in German, etc.)

Enable **"Make new playlists public."** After that, the API's `public`
flag works as expected. You may need to log out and back in to the
moodCreator app for the change to take effect.

### "Rate limited for XXXXXs"

Spotify has temporarily blocked the app. The cooldown decays on its own
(hours, not days). Wait it out. Don't spam Create. If it happens
repeatedly, reduce playlist count and space out your runs.

### "Last.fm API key rejected"

The key is wrong or you hit a Last.fm rate limit. Verify the key on
last.fm, wait a minute, retry.

### "No tracks returned for a mood"

The agent couldn't find any real tracks matching the request. This is
usually one of:

- The artist or genre is too niche for Last.fm's database.
- The input is gibberish or unrecognised.
- The mood is too vague (e.g. just "music").

Try a more specific request, use canonical artist names, or add a genre
hint.

### Avatar stays as a letter

The profile cache is written at login. Log out and log back in to
refresh.

### Cache poisoning

If a mood suddenly returns "not found" for something that worked before,
delete `data/lastfm_cache.json` and restart.

### Reading the log

Everything important goes to `data/app.log`. If something fails and the
UI shows a vague error, the log usually has the real reason.

---

## About this project

This codebase was built collaboratively with an AI assistant. Almost
every line came out of a conversation — debugging, iterating, occasionally
starting over. The human side directed, tested, and decided what to
ship. The LLM side wrote the code.

What that means in practice:

- The architecture is pragmatic, not textbook.
- Some functions do more than they strictly should.
- Comment style varies depending on when it was written.
- Tests are manual, not automated.
- Some design decisions are the result of "this works, let's move on."

It works, it's maintained, and it's free to use however you want. Just
don't expect enterprise-grade patterns.

---

## License

MIT. See [`LICENSE`](LICENSE).

You can use, modify, and redistribute this however you want. No warranty
of any kind.

---

## Disclaimer

This software is provided as-is. Use it at your own risk. The author is
not responsible for anything that happens as a result of running it.
Specifically:

- **You are responsible for your API keys.** Spotify, DeepSeek, and
  Last.fm each have their own terms of service. Using their APIs through
  this tool means agreeing to those terms. Review them yourself.
- **You are responsible for the playlists you create.** The tool
  generates suggestions. You decide what goes on your Spotify account.
- **You are responsible for API costs.** DeepSeek charges per token.
  Personal use is cheap but not free.
- **Keys are stored in plaintext** in `data/settings.json`. For local,
  personal use that's fine. For any shared or public deployment, add
  proper secrets management first.
- **Spotify rate limits and quotas apply.** If you hammer the API, your
  app will be rate-limited or your account flagged. That's between you
  and Spotify.
- **Do not use this to train machine learning models** on Spotify or
  Last.fm data. Both services prohibit it in their terms.
- **No affiliation.** This project is not affiliated with, endorsed by,
  or sponsored by Spotify AB, Last.fm Limited, or DeepSeek.

By using this software, you accept these conditions.

---

## Credits

- Track and artist metadata provided by [Last.fm](https://www.last.fm/).
- Music playback and playlist hosting by [Spotify](https://www.spotify.com/).
- Language model orchestration via [DeepSeek](https://www.deepseek.com/).

This app is in no way affiliated with Spotify AB or Last.fm Limited.