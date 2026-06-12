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
├── main.py                # [UPDATED] Bootloader registering github, translate, and admin routers
└── utils/
    ├── __init__.py
    ├── gate.py            # Whitelist & Settings database handlers
    ├── downloader.py      # yt-dlp with 48MB chunk splitter
    ├── id_validator.py    # Handles digit checks and Telegram ID boundary verification
    ├── uploader.py        # 48MB sequential split uploader
    ├── shared.py          # Globally shared queue and database cache registries
    └── logger.py          # Standalone logging handler (Piping root logs to Bale)
└── modules/
    ├── __init__.py
    ├── admin.py           # Secure Admin Console (aiogram v3 middleware and router)
    ├── github.py          # [ADDED] Direct async GitHub cloner, branches, commits, & release explorer
    ├── translate.py       # Direct async Google Translate engine (/tr command)
    ├── youtube.py         # YouTube download, search, & transcripts
    └── direct_dl.py       # Direct URL downloader & webpage text extractor
```

## 🛠 Progress Log
- [x] **Phase 1: Project Setup & Environment Configurations**
- [x] **Phase 2: Core Bootloader & API Redirects**
- [x] **Phase 3: Bale Bot Admin Console & Input Validator**
- [x] **Phase 4: Google Translate Module** (Direct async translation engine written in `modules/translate.py` and registered in `main.py` [1.1.2])
- [x] **Phase 5: GitHub Assistant Module** (Direct async repository cloner, zip installer, commits, and branch explorer written in `modules/github.py` and registered in `main.py` [1.1.2])
- [ ] **Phase 6: YouTube Assistant Module (Transcripts, video/audio formats, search)**