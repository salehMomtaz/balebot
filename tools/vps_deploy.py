#!/usr/bin/env python3
"""Deploy and run the balebot on the VPS using systemd-run.

Required env vars: VPS_HOST, VPS_USER, VPS_PASSWORD
Optional: VPS_PORT (default 22), VPS_BOT_DIR (default /root/balebot)
Bot credentials (BALE_TOKEN, SYSTEM_CREATOR_ID, LOG_CHANNEL_ID) are read from .env.
"""
import os
import sys
import time

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from _env_loader import require_env

HOST = require_env("VPS_HOST")["VPS_HOST"]
PORT = int(os.environ.get("VPS_PORT", "22"))
USER = require_env("VPS_USER")["VPS_USER"]
PASS = require_env("VPS_PASSWORD")["VPS_PASSWORD"]
BOT_DIR = os.environ.get("VPS_BOT_DIR", "/root/balebot")

BOT_ENV = require_env("BALE_TOKEN", "SYSTEM_CREATOR_ID", "LOG_CHANNEL_ID")


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 60) -> tuple:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    return out, err, exit_status


def main():
    print(f"[*] Connecting to {HOST}:{PORT} as {USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)
    print("[+] SSH connected.")

    print(f"[*] Updating {BOT_DIR}...")
    out, err, status = run_command(
        ssh,
        f"cd {BOT_DIR} && git fetch origin master && git reset --hard origin/master",
        timeout=60,
    )
    if status != 0:
        print("[!] Git update failed:")
        print(out)
        print(err)
        ssh.close()
        sys.exit(1)
    print("[+] Code updated.")

    print("[*] Writing environment file...")
    sftp = ssh.open_sftp()
    env_path = f"{BOT_DIR}/.env"
    with sftp.file(env_path, "w") as f:
        for key, value in BOT_ENV.items():
            f.write(f"{key}={value}\n")
    sftp.close()
    run_command(ssh, f"chmod 600 {env_path}")
    print("[+] Environment file written.")

    print("[*] Checking virtual environment...")
    out, err, status = run_command(ssh, f"cd {BOT_DIR} && test -d venv && echo yes || echo no")
    if out.strip() != "yes":
        print("[*] Creating virtual environment...")
        out, err, status = run_command(
            ssh,
            f"cd {BOT_DIR} && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt",
            timeout=300,
        )
        if status != 0:
            print("[!] Failed to create venv:", err)
            ssh.close()
            sys.exit(1)
        print("[+] venv created.")
    else:
        print("[*] Updating requirements...")
        out, err, status = run_command(
            ssh,
            f"cd {BOT_DIR} && source venv/bin/activate && pip install -q -r requirements.txt",
            timeout=300,
        )
        if status != 0:
            print("[!] pip install failed:", err)
        else:
            print("[+] Requirements up to date.")

    print("[*] Stopping existing bot processes...")
    run_command(ssh, "systemctl stop balebot 2>/dev/null || true; pkill -9 -f 'python.*main.py' || true")
    time.sleep(2)

    print("[*] Starting bot via systemd-run...")
    env_args = " ".join(f'--setenv={k}={v}' for k, v in BOT_ENV.items())
    start_cmd = (
        f"systemd-run --unit=balebot --uid=root --working-directory={BOT_DIR} "
        f"{env_args} --service-type=simple "
        f"--property=Restart=always --property=RestartSec=5 "
        f"--property=StandardOutput=append:{BOT_DIR}/bot.out "
        f"--property=StandardError=append:{BOT_DIR}/bot.out "
        f"{BOT_DIR}/venv/bin/python {BOT_DIR}/main.py"
    )
    out, err, status = run_command(ssh, start_cmd, timeout=30)
    print(out)
    if err:
        print("[stderr]", err)
    if status != 0:
        print("[!] Failed to start bot service.")
        ssh.close()
        sys.exit(1)

    time.sleep(3)
    out, err, status = run_command(ssh, "systemctl status balebot --no-pager")
    print(out)
    if err:
        print("[stderr]", err)

    ssh.close()
    print("[+] Done.")


if __name__ == "__main__":
    main()
