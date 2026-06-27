#!/usr/bin/env python3
"""Deploy and run the balebot on the VPS using systemd-run.

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

ENV_VARS = {
    "BALE_TOKEN": "1166452835:4p7R009SGNGt07NtiUAGomCo3tv8X4cWtVc",
    "SYSTEM_CREATOR_ID": "1058935006",
    "LOG_CHANNEL_ID": "5035194843",
}


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 60) -> tuple:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    return out, err, exit_status


def main():
    if not HOST or not USER or not PASS:
        print("Set VPS_HOST, VPS_USER, and VPS_PASSWORD environment variables.")
        sys.exit(1)

    print(f"[*] Connecting to {HOST}:{PORT} as {USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20, banner_timeout=20)
    print("[+] SSH connected.")

    # Ensure bot directory exists and is up to date
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

    # Write .env file on the VPS
    print("[*] Writing environment file...")
    sftp = ssh.open_sftp()
    env_path = f"{BOT_DIR}/.env"
    with sftp.file(env_path, "w") as f:
        for key, value in ENV_VARS.items():
            f.write(f"{key}={value}\n")
    sftp.close()
    run_command(ssh, f"chmod 600 {env_path}")
    print("[+] Environment file written.")

    # Ensure virtual environment exists and requirements are installed
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

    # Stop any existing bot service or process
    print("[*] Stopping existing bot processes...")
    run_command(ssh, "systemctl stop balebot 2>/dev/null || true; pkill -9 -f 'python.*main.py' || true")
    time.sleep(2)

    # Start the bot as a systemd transient service
    print("[*] Starting bot via systemd-run...")
    env_args = " ".join(f'--setenv={k}={v}' for k, v in ENV_VARS.items())
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
