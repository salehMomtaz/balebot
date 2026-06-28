# Balebot

A private, multi-functional [Bale](https://bale.ai) bot for media downloads, GitHub browsing, translation, and admin-managed access.

- Download videos/audio from YouTube, Instagram, TikTok, X/Twitter, and direct URLs.
- Browse GitHub repositories, download ZIPs, view branches/tags/releases.
- Translate text with Google Translate.
- Creator-only admin console for users, settings, and cookie jars.
- Runs directly on Ubuntu 24.04 inside a Python venv — no Docker required.

## Quick Start

See the detailed guide: **[Ubuntu 24.04 VPS Setup Guide](docs/UBUNTU_VPS_SETUP.md)**

TL;DR:

```bash
# On your Ubuntu 24.04 VPS
apt-get install -y git python3-venv ffmpeg tmux
git clone https://github.com/salehMomtaz/balebot.git
cd balebot
nano .env          # fill BALE_TOKEN, SYSTEM_CREATOR_ID, LOG_CHANNEL_ID
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Run inside `tmux` so it stays alive after you disconnect.

## Logs

Every log sent to your Bale log channel is also written locally to `logs/bot.log`.

```bash
tail -f logs/bot.log
```

## Architecture

For a full technical overview see [blueprint.md](blueprint.md).

## License

See [LICENSE](LICENSE).
