# Blueprint: Private Multi-Functional Assistant Bale Bot

## 📂 System Layout
- **Docker Container:** Runs on Ubuntu 24.04 (Python 3.11 + FFmpeg + Deno) [1.1.6, 1.4.1].
- **Engine Framework:** aiogram v3 (dynamically redirected to tapi.bale.ai API server) [1.1.2, 1.1.5].
- **Web Stream Server:** FastAPI disabled (no local ports or exposed routes needed) [1.1.5].
- **Limits Safeguard:** Force-sets on-demand chunk splitting boundaries to 48 MB to cleanly bypass Bale's 50 MB upload caps [1.1.5].

## 📁 Directory Structure
```text
balebot/
├── Dockerfile             # Base container layout
├── docker-compose.yml     # Container mapping exposing port 9090
├── requirements.txt       # Target framework packages
├── config.py              # Holds Bale credentials, GitHub PAT, and paths
├── database.json          # Whitelisted, blacklisted, and setting registries
├── ytcookies.txt          # YouTube cookies
├── igcookies.txt          # Instagram cookies
├── ttcookies.txt          # TikTok cookies
├── xcookies.txt           # X/Twitter cookies
├── cookies.txt            # Fallback global cookies
├── main.py                # [ADDED] Asynchronous bootloader with Bale tapi API redirect
└── utils/
    ├── __init__.py
    ├── gate.py            # [ADDED] Whitelist & Settings database handlers
    ├── downloader.py      # yt-dlp with 48MB chunk splitter
    ├── id_validator.py    # Handles digit checks and Telegram ID boundary verification
    ├── uploader.py        # 48MB sequential split uploader
    ├── shared.py          # [ADDED] Globally shared queue and database cache registries
    └── logger.py          # [ADDED] Standalone logging handler (Piping root logs to Bale)
└── modules/
    ├── __init__.py
    ├── admin.py           # Admin Callback Console (Whitelist, Blacklist bans, Settings)
    ├── github.py          # GitHub API cloner & repository browser
    ├── translate.py       # Google Translate engine (/tr command)
    ├── youtube.py         # YouTube download, search, & transcripts
    └── direct_dl.py       # Direct URL downloader & webpage text extractor
```

## 🛠 Progress Log
- [x] **Phase 1: Project Setup & Environment Configurations**
- [x] **Phase 2: Core Bootloader & API Redirects** (aiogram v3 api redirect bootloader implemented in `main.py` and log thread structured in `utils/logger.py`)
- [ ] **Phase 3: Bale Bot Admin Console & Input Validator**