# Blueprint: Private Multi-Functional Assistant Bale Bot

## 📂 System Layout
- **Docker Container:** Runs on Ubuntu 24.04 (Python 3.11 + FFmpeg + Deno) [1.1.6, 1.4.1].
- **Engine Framework:** aiogram v3 (dynamically redirected to tapi.bale.ai API server) [1.1.2, 1.1.5].
- **Web Stream Server:** FastAPI running natively on port 9090 (with optional SSL parameters) [1.1.5].
- **Limits Safeguard:** Force-sets on-demand chunk splitting boundaries to 48 MB to cleanly bypass Bale's 50 MB upload caps [1.1.5].

## 📁 Directory Structure
```text
balebot/
├── Dockerfile             # [ADDED] Base container layout
├── docker-compose.yml     # [ADDED] Container mapping exposing port 9090
├── requirements.txt       # [ADDED] Target framework packages
├── config.py              # [ADDED] Holds Bale credentials, GtHub PAT, and paths
├── database.json          # Whitelisted, blacklisted, and setting registries
├── ytcookies.txt          # YouTube cookies
├── igcookies.txt          # Instagram cookies
├── ttcookies.txt          # TikTok cookies
├── xcookies.txt           # X/Twitter cookies
├── cookies.txt            # Fallback global cookies
├── main.py                # Main bootloader & api server redirect
└── utils/
    ├── __init__.py
    ├── gate.py            # Access control gates
    ├── downloader.py      # yt-dlp with 48MB chunk splitter
    ├── id_validator.py    # Numeric ID validator
    ├── uploader.py        # 48MB sequential split uploader
    ├── shared.py          # Shared queue instance
    └── logger.py          # Standalone logging handler
└── modules/
    ├── __init__.py
    ├── github.py          # GitHub API cloner & repository browser
    ├── translate.py       # Google Translate engine (/tr command)
    ├── youtube.py         # YouTube download, search, & transcripts
    ├── direct_dl.py       # Direct URL downloader & webpage text extractor
    └── stream_handler.py  # FastAPI Server Stream Bridge (with 24-hour token check)
```

## 🛠 Progress Log
- [x] **Phase 1: Project Setup & Environment Configurations** (Base configuration, dockerfiles, and blueprints created)
- [ ] **Phase 2: Core Bootloader & API Redirects**