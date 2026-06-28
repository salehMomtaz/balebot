# Balebot Blueprint

A private, multi-functional Telegram/Bale bot for downloading media, browsing GitHub, translating text, and admin-managed user access. Designed to run directly on an Ubuntu 24.04 VPS inside a Python virtual environment (no Docker required).

---

## 1. System Overview

| Layer | Technology | Notes |
|---|---|---|
| Runtime | Python 3.12 venv | No Docker required; see `run.sh` for safe startup |
| Bot Framework | aiogram 3.12.0 | Redirected to `https://tapi.bale.ai` |
| Media Extraction | yt-dlp (auto-updated nightly) | Cookie-aware per-domain; optional PO-token provider for flagged YouTube IPs |
| Post-processing | FFmpeg 6.x | Thumbnails, metadata embedding, splitting |
| PO Token Provider | Node.js bgutil HTTP server | Localhost-only subprocess managed by `utils/pot_provider.py` |
| Web server | FastAPI + uvicorn | Optional, currently not the primary interface |
| Queue | In-memory `DownloadQueue` | Sequential worker, max 20 queued jobs |
| Logging | Root logger + two handlers | Bale channel (`LOG_CHANNEL_ID`) + local `logs/bot.log` |

### Key Safeguards

- **Upload cap:** Hard limit `20 MB`; target split size `18 MB` for video/audio/binary chunks.
- **Disk guard:** Refuses new jobs above `95%` disk usage; startup aborts above `95%`.
- **Memory guard:** `run.sh` sets `ulimit` virtual/resident memory to ~4 GB.
- **Queue guard:** Max queue depth of `20`; disk check before enqueue.
- **Cleanup:** Hourly cache sweep removes entries older than `max_cache_age_hours` (default 2).

---

## 2. Directory Structure

```text
balebot/
├── .env                          # Secrets: BALE_TOKEN, GITHUB_TOKEN, IDs (not tracked)
├── .gitignore                    # Ignores venv, logs, cache, env, cookies
├── blueprint.md                  # This file
├── config.py                     # Environment-driven configuration
├── database.json                 # Authorized/blacklisted users
├── main.py                       # Bootloader, logger setup, polling loop
├── requirements.txt              # Python dependencies
├── run.sh                        # Safe startup wrapper (venv + ulimits)
├── Dockerfile                    # Optional Docker layout (for others)
├── docker-compose.yml            # Optional Docker layout (for others)
├── cache/                        # Working downloads, GitHub cache, temp files
├── logs/                         # Local rotating log mirror
├── *cookies.txt                  # Site-specific cookie jars
│
├── modules/                      # aiogram routers
│   ├── admin/                    # Creator-only admin console
│   │   ├── router.py
│   │   ├── middleware.py
│   │   ├── keyboards.py
│   │   └── cookies.py
│   ├── direct_dl/                # Direct URL downloader
│   ├── downloader/               # Social-media link downloader (YouTube, IG, TT, X)
│   ├── github/                   # GitHub repo browser / ZIP downloader
│   ├── translate/                # Google Translate command
│   ├── user/                     # User-facing commands
│   └── youtube/                  # YouTube-specific commands
│
├── operators/                    # Heavy I/O workers
│   ├── downloader.py             # yt-dlp extraction, metadata, splitting
│   └── uploader.py               # Bale multipart upload + split orchestration
│
├── tools/                        # Optional VPS helper scripts
│   ├── vps_deploy.py
│   ├── vps_logs.py
│   └── vps_run.py
│
└── utils/                        # Shared utilities
    ├── gate.py                   # Authorization + database
    ├── id_validator.py
    ├── logger.py                 # BaleChannelHandler + local rotating handler
    ├── queue_manager.py          # Sequential task queue
    ├── shared.py                 # Global settings + caches
    └── updater.py                # yt-dlp nightly updater
```

---

## 3. Data Flows

### 3.1 Social Media Download

1. User sends URL (`https://...`); `downloader_router` receives it.
2. `is_authorized()` gate check.
3. `extract_formats()` calls yt-dlp with domain cookies, then retries without cookies on failure.
4. Formats are filtered into video/audio options (storyboards skipped).
5. Inline keyboard presented; selection cached in `DOWNLOAD_CACHE`.
6. On callback, `download_media()` downloads into `cache/{cache_id}/`.
7. FFmpeg embeds metadata/cover art (audio) or title metadata (video).
8. `process_split_and_upload()` splits if needed and uploads chunks sequentially, deleting each chunk immediately after upload.
9. `finally` block removes `cache/{cache_id}/`.

### 3.2 GitHub Repository Browser

1. User sends `https://github.com/owner/repo`.
2. Session created with 8-char ID and persisted to `cache/github_cache.json` (30-min TTL).
3. Callbacks answered immediately; network/disk work queued.
4. Files/Info/Branches/Tags/Releases fetched via GitHub API.
5. ZIP downloads stream to `cache/` and are uploaded/split as documents.
6. Temp ZIP removed on success or failure.

### 3.3 Direct URL Download

1. User sends generic `http(s)://` URL.
2. File streamed to `cache/{cache_id}/` via aiohttp.
3. Uploaded/split as document, then directory removed.

---

## 4. Configuration (`config.py`)

Loaded from `.env` via `python-dotenv`:

| Variable | Purpose |
|---|---|
| `BALE_TOKEN` | Bot token from @BotFather on Bale |
| `SYSTEM_CREATOR_ID` | Numeric Bale user ID with admin powers |
| `LOG_CHANNEL_ID` | Numeric channel ID for log mirroring |
| `GITHUB_TOKEN` | GitHub PAT for API calls |
| `SOCKS5_PROXY` / `ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY` | Optional proxy for yt-dlp/aiohttp/requests |
| `YTDLP_USER_AGENT` | Browser User-Agent string to pair with cookies |
| `YTDLP_POT_ENABLED` | Enable the local PO-token provider for flagged YouTube IPs (`true`/`false`) |
| `YTDLP_POT_PORT` | Local port for the bgutil PO-token provider (default `4416`) |
| `YTDLP_POT_PROVIDER_PATH` | Path to `bgutil-provider/server` (default: built-in) |
| `YTDLP_POT_PLUGIN_PATH` | Path to `bgutil-provider/plugin` (default: built-in) |

Cookie file paths are fixed relative filenames: `ytcookies.txt`, `igcookies.txt`, `ttcookies.txt`, `xcookies.txt`, `cookies.txt`.

**Cookie jar protection:** The live `ytcookies.txt` is locked read-only after bot startup. yt-dlp receives a writable snapshot copy, so it can never rewrite or corrupt the uploaded jar. Admin replace/restore/savebackup handlers unlock the file briefly, update it, then re-lock it.

---

## 5. Admin Console

Available only to `SYSTEM_CREATOR_ID` via `/admin`, `/start`, or "🛠 Console".

Features:
- Add/remove authorized users
- View/unban blacklisted users
- Toggle document mode
- Set runtime limits (`bale_hard_limit_mb`, `split_target_mb`, `binary_chunk_mb`, `max_cache_age_hours`)
- Cookie jar browser: download current jar or replace by uploading a `.txt` document
- PO-token provider control: diagnose YouTube access, test full stack, toggle on/off
- Abort queue

---

## 6. Security Notes

- No `eval`/`exec` or `shell=True` in project code.
- Subprocess calls use argument lists (FFmpeg, ffprobe, pip).
- File paths are built under `cache/{uuid}/`; user-provided filenames are sanitized via `os.path.basename`/`re`.
- Admin actions require `SYSTEM_CREATOR_ID`.
- Unauthorized users are blacklisted automatically by middleware.
- Cookie replacement only accepts `.txt` / `text/*` documents.

---

## 7. Operational Notes

- **Single instance only.** Running multiple instances causes update-fighting.
- **Run in tmux/screen:** Use `./run.sh` inside a tmux session so the bot survives SSH disconnect.
- **Logs:** Every log sent to the Bale channel is also written to `logs/bot.log` (rotated at 5 MB, 3 backups).
- **Cookies:** YouTube frequently challenges VPS IPs. If downloads fail with "Sign in to confirm you're not a bot", upload a fresh `ytcookies.txt` from a logged-in browser via Admin Console → Cookies.
- **PO Tokens:** If fresh cookies still yield only storyboards, set `YTDLP_POT_ENABLED=true`, ensure Node.js ≥ 20 is installed, and use Admin Console → PO Token → Run Diagnosis.
- **yt-dlp:** Auto-updated every 6 hours via `utils/updater.py`.

---

## 8. Current Status

- [x] Core bootloader + aiogram v3 Bale redirect
- [x] Admin console + middleware + user database
- [x] Google Translate module
- [x] GitHub repository browser with persistent sessions
- [x] YouTube/social-media downloader with format selection
- [x] Large-file splitting via FFmpeg `-c copy` and binary chunking
- [x] Metadata embedding via FFmpeg (title/artist/cover art)
- [x] Local log mirroring + rotating file handler
- [x] Disk/queue resource guards
- [x] Direct URL downloader
- [x] Ubuntu 24.04 VPS native run script (`run.sh`)
- [x] Optional Docker files retained for users who prefer containers
- [x] YouTube PO-token provider integration (bgutil + mweb client)
