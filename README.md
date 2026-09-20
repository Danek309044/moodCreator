# moodCreator

Turn a text description into a Spotify playlist.

Type a mood, an artist, a genre, or any mix. The app uses DeepSeek + Last.fm
to find real tracks that match, shows you a preview, and lets you commit the
playlist to your Spotify account.

Examples:
- `yeat feat don`
- `drake and travis scott mix`
- `chill jazz for a rainy day`
- `morning drive to school`

## Features

- Reads a mood, artist list, genre, or any mix
- Resolves artist nicknames with context (`don` becomes Don Toliver)
- Pulls real tracks from Last.fm - never hallucinated names
- Preview mode: remove tracks, rename the playlist, regenerate
- Creates private or public playlists on Spotify
- Per-user history with one-click recreate
- Cross-device last preview

## Requirements

- Python 3.10 or newer
- A Spotify Developer app (free)
- A DeepSeek API key
- A Last.fm API key

Links:
- Spotify: https://developer.spotify.com/dashboard
- DeepSeek: https://platform.deepseek.com
- Last.fm: https://www.last.fm/api/account/create

## Quick start

Windows:

    start.bat

The first run creates a virtual environment and installs dependencies.

Manual:

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python -m uvicorn server:app --host 0.0.0.0 --port 4444

Then open http://127.0.0.1:4444/ in a browser.

## First-time setup

1. Create a Spotify app in the developer dashboard.

2. Add this redirect URI:

       http://127.0.0.1:4444/callback

3. Under "Users and Access", add the email of every Spotify account you want
   to allow. Dev-mode apps are capped at 25 users.

4. Copy the Client ID.

5. Open the app. It redirects to /setup. Paste:
   - Spotify Client ID
   - DeepSeek API key
   - Last.fm API key
   - (optional) Redirect URI - only if you're hosting behind a reverse proxy

6. Save. You'll land on /login.

7. Click "Continue with Spotify". The first user to log in becomes the admin.

## Usage

- Type a mood into the input
- Pick a track count (5 to 100)
- Toggle deep cuts if you want lesser-known tracks
- Press Enter or click Generate
- Wait for the stream log to finish
- Review the preview. Remove anything that doesn't fit.
- Click Create playlist

## Deploying on a homelab

Run the app on one machine, expose it through a reverse proxy on another.
Spotify only accepts HTTPS for non-loopback redirect URIs, so you need a
proxy that terminates TLS.

Caddy example:

    mood.yourdomain.com {
        reverse_proxy 10.10.1.100:4444 {
            header_up X-Forwarded-Proto {scheme}
            header_up X-Forwarded-Host {host}
        }
    }

Then:
- Register https://mood.yourdomain.com/callback in the Spotify dashboard
- In /setup, set the Redirect URI explicitly to that URL

Alternative: Cloudflare Tunnel.

    cloudflared tunnel --url http://127.0.0.1:4444

Copy the trycloudflare.com URL it prints, register .../callback in Spotify,
paste into /setup.

## Runtime state

Everything lives under data/:

    data/settings.json                        API keys and configuration
    data/tokens/{user_id}.json                per-user Spotify tokens
    data/history/{user_id}.jsonl              playlist history
    data/previews/{user_id}_latest.json       last preview (cross-device)
    data/app.log                              application log

Do not commit data/. It contains plaintext keys.

To factory-reset:

    python reset.py

Or just delete the data/ directory. It gets recreated on next start.

## CLI

The pipeline is also available as a command-line tool:

    python main.py "chill dnb" 15 --dry-run
    python main.py "chill dnb" 15 --deep-cuts --json

Flags:
- --dry-run     print a preview, do not touch Spotify
- --deep-cuts   prefer lesser-known tracks over hits
- --json        machine-readable output

Note: the CLI only previews. Creating playlists needs the web UI because it
requires a user context for the Spotify token.

## Troubleshooting

**Rate limited for XXXXXs**

Spotify has flagged the app. The cooldown decays on its own - hours, not
days. Wait it out. Do not spam Create. If it happens repeatedly, reduce the
playlist count and space out your runs.

**Last.fm API key rejected**

The key is wrong or you hit a Last.fm rate limit. Verify the key on
last.fm, wait a minute, retry.

**No tracks returned for a mood**

DeepSeek may not know that artist. Try a more canonical name
("yzomandias" instead of "yzo"), or add a genre hint.

**Avatar stays as a letter**

The profile cache is written at login. Log out and log back in to refresh.

**Cache poisoning**

If a mood suddenly returns "not found" for something that worked before,
delete .lastfm_cache.json and restart the server.

## File layout

    server.py            FastAPI app + SSE + auth routes
    main.py              Pipeline: generate + commit
    deepseek.py          LLM agent with tool calling
    lastfm.py            Last.fm wrapper
    spotify_auth.py      Spotify OAuth (PKCE)
    spotify_client.py    Spotify Web API client
    settings.py          Settings loader
    sessions.py          Session cookies
    history.py           Per-user history + stats
    previews.py          Preview counter + last preview storage
    validation.py        Gibberish filter
    logger.py            Logging setup
    config.py            Paths and constants
    reset.py             Wipe runtime state
    start.bat            Windows launcher
    stop.bat             Windows stop script
    requirements.txt
    data/                Runtime state (gitignored)
    static/              Frontend files

## Credits

This app was fully vibecoded by Deepseek.
Data provided by Last.fm Limited.
This app is in no way affiliated with Spotify AB.
