#!/usr/bin/env python3
"""Tail the bot log on the VPS via SSH.

Required env vars: VPS_HOST, VPS_USER, VPS_PASSWORD
Optional: VPS_PORT (default 22), VPS_BOT_DIR (default /root/balebot)
"""
import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from _env_loader import require_env

HOST = require_env("VPS_HOST")["VPS_HOST"]
PORT = int(os.environ.get("VPS_PORT", "22"))
USER = require_env("VPS_USER")["VPS_USER"]
PASS = require_env("VPS_PASSWORD")["VPS_PASSWORD"]
BOT_DIR = os.environ.get("VPS_BOT_DIR", "/root/balebot")
LINES = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 30) -> tuple:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace").strip()
    status = stdout.channel.recv_exit_status()
    return out, err, status


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)

    log_paths = [
        f"{BOT_DIR}/logs/bot.log",
        f"{BOT_DIR}/bot.out",
    ]
    for path in log_paths:
        out, err, status = run_command(ssh, f"tail -n {LINES} {path} 2>/dev/null")
        if status == 0 and out.strip():
            print(f"=== {path} ===")
            print(out)
            print()

    ssh.close()


if __name__ == "__main__":
    main()
