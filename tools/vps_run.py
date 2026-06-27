#!/usr/bin/env python3
"""Run arbitrary command on VPS via SSH for diagnostics."""
import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(__file__))
from _env_loader import require_env

HOST = require_env("VPS_HOST")["VPS_HOST"]
PORT = int(os.environ.get("VPS_PORT", "22"))
USER = require_env("VPS_USER")["VPS_USER"]
PASS = require_env("VPS_PASSWORD")["VPS_PASSWORD"]


def run_command(ssh, command, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    status = stdout.channel.recv_exit_status()
    return out, err, status


def main():
    command = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "echo hello"
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)
    out, err, status = run_command(ssh, command)
    print(f"exit={status}")
    if out:
        print("STDOUT:")
        print(out)
    if err:
        print("STDERR:")
        print(err)
    ssh.close()


if __name__ == "__main__":
    main()
