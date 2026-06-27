#!/usr/bin/env python3
"""Deploy latest balebot code to the VPS and restart the bot.

Credentials are loaded from environment variables so they are never committed.
Required env vars:
    VPS_HOST, VPS_PORT (optional, default 22), VPS_USER, VPS_PASSWORD
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("VPS_HOST")
PORT = int(os.environ.get("VPS_PORT", "22"))
USER = os.environ.get("VPS_USER")
PASS = os.environ.get("VPS_PASSWORD")
REPO_REMOTE = "https://github.com/salehMomtaz/balebot.git"


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 30) -> tuple:
    """Run a command on the remote host and return (stdout, stderr, exit_status)."""
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    return out, err, exit_status


def main():
    if not HOST or not USER or not PASS:
        print(
            "[!] Set VPS_HOST, VPS_USER, and VPS_PASSWORD environment variables. "
            "Optionally set VPS_PORT (default 22)."
        )
        sys.exit(1)

    print(f"[*] Connecting to {HOST}:{PORT} as {USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)
    except Exception as e:
        print(f"[!] SSH connection failed: {e}")
        sys.exit(1)
    print("[+] SSH connected.")

    # Discover bot directory by looking for existing repo or running process
    bot_dir = None
    candidates = [
        "/root/balebot",
        "/root/balebot/balebot",
        "/opt/balebot",
        "/home/*/balebot",
    ]
    for cand in candidates:
        out, err, status = run_command(ssh, f"test -d {cand}/.git && echo {cand}")
        if status == 0 and out:
            bot_dir = out.strip()
            break

    if not bot_dir:
        out, err, status = run_command(ssh, "ps aux | grep -E 'python.*main.py' | grep -v grep")
        if out:
            for line in out.splitlines():
                parts = line.split()
                for part in parts:
                    if part.endswith("main.py"):
                        bot_dir = os.path.dirname(part)
                        break
                if bot_dir:
                    break

    if not bot_dir:
        print("[!] Could not locate bot directory on VPS.")
        ssh.close()
        sys.exit(1)

    print(f"[+] Bot directory: {bot_dir}")

    # Stop running bot
    print("[*] Stopping any running bot process...")
    run_command(ssh, "pkill -f 'python.*main.py' || true")
    time.sleep(2)

    # Pull latest code. Do NOT run git clean -fd because that would delete
    # untracked runtime files like logs, cookie files, and database.json.
    print("[*] Pulling latest code...")
    out, err, status = run_command(ssh, f"cd {bot_dir} && git reset --hard HEAD && git pull origin master")
    print(out)
    if err:
        print("[stderr]", err)
    if status != 0:
        print("[!] Git pull failed.")
        ssh.close()
        sys.exit(1)

    # Ensure virtual environment exists
    print("[*] Checking virtual environment...")
    out, err, status = run_command(ssh, f"cd {bot_dir} && test -d venv && echo yes || echo no")
    if out.strip() != "yes":
        print("[*] Creating virtual environment...")
        out, err, status = run_command(
            ssh,
            f"cd {bot_dir} && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt",
        )
        print(out)
        if status != 0:
            print("[!] Failed to set up venv.")
            ssh.close()
            sys.exit(1)
    else:
        print("[+] venv exists.")

    # Ensure requirements are current
    print("[*] Updating requirements...")
    out, err, status = run_command(ssh, f"cd {bot_dir} && source venv/bin/activate && pip install -q -r requirements.txt")
    if status != 0:
        print("[!] pip install failed:", err)
    else:
        print("[+] Requirements up to date.")

    # Start bot in background with nohup
    print("[*] Starting bot in background...")
    start_cmd = (
        f"cd {bot_dir} && nohup bash -c 'source venv/bin/activate && python main.py' "
        f"> {bot_dir}/bot.out 2>&1 &"
    )
    run_command(ssh, start_cmd)
    time.sleep(3)

    # Verify process is running
    out, err, status = run_command(ssh, "ps aux | grep -E 'python.*main.py' | grep -v grep")
    if out:
        print("[+] Bot process is running:")
        print(out)
    else:
        print("[!] Bot process not found after start.")
        out, err, _ = run_command(ssh, f"tail -n 30 {bot_dir}/bot.out")
        print("Last bot output:")
        print(out)

    ssh.close()
    print("[+] Done.")


if __name__ == "__main__":
    main()
