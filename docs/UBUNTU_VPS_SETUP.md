# Ubuntu 24.04 VPS Setup Guide for Balebot

This guide is written for the newest users who have just rented an Ubuntu 24.04 VPS and want to run Balebot directly (no Docker). Follow every step in order.

---

## What you need before you start

1. An Ubuntu 24.04 VPS with root (or sudo) access.
2. A Bale bot token from [@BotFather](https://t.me/BotFather) on Bale.
3. Your numeric Bale user ID (send `/start` to `@userinfobot` on Bale).
4. A private Bale channel ID where logs will be sent (optional but recommended).
5. A GitHub Personal Access Token (optional, for GitHub features).
6. SSH access to the VPS.

---

## Step 1: Log in and update the server

Open your terminal and SSH into the VPS. Replace `root` and `YOUR_VPS_IP` with your actual user and IP.

```bash
ssh root@YOUR_VPS_IP
```

Once inside, update the package list and install the required system packages:

```bash
apt-get update && apt-get upgrade -y
apt-get install -y git python3 python3-venv python3-pip ffmpeg tmux
```

Check that FFmpeg is installed:

```bash
ffmpeg -version | head -n 1
```

You should see something like `ffmpeg version 6.1.1 ...`.

---

## Step 2: Create a non-root user (recommended)

Running the bot as `root` is not recommended. Create a dedicated user:

```bash
adduser balebot
usermod -aG sudo balebot
```

Set a strong password when prompted. Then switch to that user:

```bash
su - balebot
```

All remaining commands in this guide assume you are the `balebot` user.

---

## Step 3: Clone the repository

```bash
cd ~
git clone https://github.com/salehMomtaz/balebot.git
cd balebot
```

You are now inside the project folder: `~/balebot`.

---

## Step 4: Create the environment file

Create `.env` and fill in your real values:

```bash
nano .env
```

Paste this, replacing the example values:

```env
BALE_TOKEN=1234567890:YourActualBaleTokenHere
SYSTEM_CREATOR_ID=YourNumericUserID
LOG_CHANNEL_ID=YourNumericChannelID
GITHUB_TOKEN=ghp_YourGitHubTokenHere
YTDLP_POT_ENABLED=false
YTDLP_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
```

- `BALE_TOKEN`: from @BotFather.
- `SYSTEM_CREATOR_ID`: your numeric Bale user ID.
- `LOG_CHANNEL_ID`: numeric ID of the private channel where logs go.
- `GITHUB_TOKEN`: optional; leave blank if you do not use GitHub features.
- `YTDLP_POT_ENABLED`: set to `true` if YouTube blocks this VPS IP even with cookies (see Step 11).
- `YTDLP_USER_AGENT`: optional browser User-Agent to pair with your cookies.

Save and exit: `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## Step 5: Create the Python virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

This installs aiogram, yt-dlp, FFmpeg-Python, and all other Python packages.

---

## Step 6: First start (test mode)

Run the bot once in the foreground to confirm everything works:

```bash
source venv/bin/activate
python main.py
```

You should see:

```text
Initializing balebot services...
[Logger] Standalone Bale Logging Service linked to Root Logger.
[Logger] Local log mirror active at: /home/balebot/balebot/logs/bot.log
[System] Disk usage: 12.3% used, 45.67 GB free.
Bale Bot Online.
Log Channel resolved successfully.
[Polling] Backlog successfully dropped.
```

If you see errors, fix them before continuing. Common issues:

- **Invalid token**: check `.env`.
- **Log channel not found**: make sure the bot is an admin in the channel.

Stop the bot with `Ctrl+C`.

---

## Step 7: Run the bot permanently with tmux

Use `tmux` so the bot keeps running after you close SSH.

```bash
tmux new-session -s balebot
```

Inside tmux, run:

```bash
cd ~/balebot
./run.sh
```

The bot starts. Detach from tmux by pressing `Ctrl+B` then `D`.

You can re-attach later with:

```bash
tmux attach -t balebot
```

To stop the bot, attach and press `Ctrl+C`, or run from outside:

```bash
tmux kill-session -t balebot
```

---

## Step 8: Check the logs

Logs are mirrored in two places:

1. Your Bale log channel (`LOG_CHANNEL_ID`).
2. Local file: `logs/bot.log`.

To watch logs live:

```bash
tail -f ~/balebot/logs/bot.log
```

To search for errors:

```bash
grep -i error ~/balebot/logs/bot.log
```

---

## Step 9: Keeping the bot up to date

When the developer pushes updates:

```bash
cd ~/balebot
tmux kill-session -t balebot
git pull origin master
source venv/bin/activate
pip install -r requirements.txt
tmux new-session -s balebot './run.sh'
```

This pulls the latest code, updates dependencies, and restarts the bot.

---

## Step 10: Adding YouTube cookies (very important for VPS)

YouTube often blocks VPS IPs and asks for sign-in. If your downloads fail with:

```text
Sign in to confirm you’re not a bot.
```

You must upload fresh cookies:

1. On your personal computer, install the **Get cookies.txt LOCALLY** browser extension (Chrome/Firefox).
2. Go to `youtube.com` while logged into your Google account.
3. Export cookies as `ytcookies.txt` in Netscape format.
4. Send the file to your bot in Bale as a **document** (not as text).
5. Open Admin Console → Cookies → `ytcookies.txt` → Replace.
6. Send the document when prompted.

After replacing, try the YouTube link again.

> **Cookie jar protection:** The live `ytcookies.txt` is kept read-only while the bot is running. yt-dlp always works on a disposable snapshot, so it can never corrupt your uploaded jar. Use Admin Console → Cookies → `ytcookies.txt` → **Save as Backup** to lock a known-good jar as `ytcookies.backup`.

---

## Step 11: PO-token setup (if cookies alone are not enough)

Some VPS IPs are heavily flagged by YouTube. If fresh cookies still give:

```text
No downloadable formats found.
```

or only storyboard formats, enable the PO-token provider:

1. Make sure Node.js >= 20 is installed:

   ```bash
   sudo apt-get install -y nodejs
   node -v
   ```

   You should see `v20` or higher.

2. Open `.env`:

   ```bash
   nano .env
   ```

3. Add this line:

   ```env
   YTDLP_POT_ENABLED=true
   ```

4. Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

5. Restart the bot:

   ```bash
   tmux kill-session -t balebot
   tmux new-session -s balebot
   cd ~/balebot
   ./run.sh
   # Detach with Ctrl+B then D
   ```

The provider source is cloned automatically by `run.sh` on first start when `YTDLP_POT_ENABLED=true`. The build (`npm ci` + `tsc`) happens automatically inside `bgutil-provider/server`; this may take a minute on first start.

> Do not commit `bgutil-provider/` to git. It is listed in `.gitignore` and managed locally.

---

## Step 12: Verify PO-token support

In Bale, open Admin Console and tap **PO Token**.

1. Tap **Run Diagnosis**. It compares three scenarios and tells you which one works.
2. If the diagnosis shows real formats only for "Cookies + PO token + mweb", the setup is correct.
3. Tap **Test Stack** to confirm a live extraction works.
4. Now send a YouTube link and choose a format.

If the diagnosis shows `0` real formats for all scenarios, this VPS IP is fully blocked even with PO tokens. Try a proxy, a different server, or warmer cookies.

---

## Step 13: Useful commands

| Task | Command |
|---|---|
| Attach to bot session | `tmux attach -t balebot` |
| Detach (keep running) | `Ctrl+B` then `D` |
| Stop bot | `tmux kill-session -t balebot` |
| View logs | `tail -f ~/balebot/logs/bot.log` |
| Check disk space | `df -h` |
| Check bot process | `pgrep -af 'python.*main\.py'` |
| Restart bot | kill session, then `tmux new-session -s balebot './run.sh'` |

---

## Step 14: Troubleshooting

### "Sign in to confirm you're not a bot"

- Upload fresh cookies (Step 10).
- If it persists, enable PO tokens (Step 11).

### "No downloadable formats found"

- YouTube may require fresh cookies (see Step 10).
- The VPS IP may be flagged; enable PO tokens (Step 11) and run the diagnosis.
- The link may be an ended live stream with only storyboards.
- The video may be region-blocked or members-only.

### Bot responds slowly or queue grows

- Only one instance should run. Check with `pgrep -af 'python.*main\.py'`.
- The queue is sequential; wait your turn.
- Disk usage above 95% pauses new jobs.

### Uploads fail with "Bale API Error"

- Make sure files are under ~20 MB after splitting.
- Check `logs/bot.log` for the exact error.

### Disk full warnings

- Clear old logs: `rm ~/balebot/logs/bot.log.*`
- Clear cache manually: `rm -rf ~/balebot/cache/*`
- Add more disk space from your VPS provider.

### PO-token provider errors in logs

- Confirm Node.js version: `node -v` should be `v20+`.
- Confirm `YTDLP_POT_ENABLED=true` is in `.env`.
- Check `logs/bot.log` for `[POT]` messages.
- Run Admin Console → PO Token → Run Diagnosis.

---

## Docker (optional)

If you prefer Docker, the files `Dockerfile` and `docker-compose.yml` are included. This guide focuses on the recommended native venv setup.

---

## Support

If something is wrong, copy the relevant lines from `logs/bot.log` and share them. The log file contains everything the bot does, which makes debugging fast.
