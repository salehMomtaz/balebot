#!/usr/bin/env python3
"""Upload environment file to the VPS and restart the bot.

Required env vars: VPS_HOST, VPS_USER, VPS_PASSWORD
Optional: VPS_PORT (default 22), VPS_BOT_DIR (default /root/balebot)
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("VPS_HOST")
PORT = int(os.environ.get("VPS_PORT", "22"))
USER = os.environ.get("VPS_USER")
PASS = os.environ.get("VPS_PASSWORD")
BOT_DIR = os.environ.get("VPS_BOT_DIR", "/root/balebot")

ENV_CONTENT = """# Bale bot environment variables - generated automatically.
# This file is loaded by deploy_restart_vps.py before starting the bot.
BALE_TOKEN=1166452835:4p7R009SGNGt07NtiUAGomCo3tv8X4cWtVc
SYSTEM_CREATOR_ID=1058935006
LOG_CHANNEL_ID=5035194843
"""


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 30) -> tuple:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    return out, err, exit_status


def main():
    if not HOST or not USER or not PASS:
        print("Set VPS_HOST, VPS_USER, and VPS_PASSWORD environment variables.")
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)

    print(f"[*] Writing {BOT_DIR}/.env ...")
    sftp = ssh.open_sftp()
    env_path = f"{BOT_DIR}/.env"
    with sftp.file(env_path, "w") as f:
        f.write(ENV_CONTENT)
    sftp.close()
    run_command(ssh, f"chmod 600 {env_path}")
    print("[+] .env written.")

    print("[*] Stopping any running bot process...")
    run_command(ssh, "pkill -f 'python.*main.py' || true")
    time.sleep(2)

    print("[*] Starting bot with .env sourced...")
    start_cmd = (
        f"cd {BOT_DIR} && nohup bash -c 'set -a && source .env && set +a && "
        f"source venv/bin/activate && python main.py' > {BOT_DIR}/bot.out 2>&1 &"
    )
    run_command(ssh, start_cmd)
    time.sleep(3)

    out, err, status = run_command(ssh, "ps aux | grep -E 'python.*main.py' | grep -v grep")
    if out:
        print("[+] Bot process is running:")
        print(out)
    else:
        print("[!] Bot process not found after start.")
        out, err, _ = run_command(ssh, f"tail -n 30 {BOT_DIR}/bot.out")
        print("Last bot output:")
        print(out)

    ssh.close()
    print("[+] Done.")


if __name__ == "__main__":
    main()
