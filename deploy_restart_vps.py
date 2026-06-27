#!/usr/bin/env python3
"""Deploy latest balebot code to the VPS and restart the bot."""
import os
import sys
import time
import paramiko

HOST = "66.23.198.52"
PORT = 1605
USER = "root"
PASS = "yGknqdlzu2EzQ991udKc"
REPO_REMOTE = "https://github.com/salehMomtaz/balebot.git"


def run_command(ssh: paramiko.SSHClient, command: str, timeout: int = 30) -> tuple:
    """Run a command on the remote host and return (stdout, stderr, exit_status)."""
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    return out, err, exit_status


def main():
    print(f"[*] Connecting to {HOST} as {USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=PASS, timeout=20, banner_timeout=20)
    except Exception as e:
        print(f"[!] SSH connection failed: {e}")
        sys.exit(1)
    print("[+] SSH connected.")

    # Discover bot directory by looking for existing repo or running process
    bot_dir = None

    # Try common paths first
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
        # Find by running main.py
        out, err, status = run_command(ssh, "ps aux | grep -E 'python.*main.py' | grep -v grep")
        if out:
            for line in out.splitlines():
                parts = line.split()
                for i, part in enumerate(parts):
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

    # Pull latest code
    print("[*] Pulling latest code...")
    out, err, status = run_command(ssh, f"cd {bot_dir} && git reset --hard HEAD && git clean -fd && git pull origin master")
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
        out, err, status = run_command(ssh, f"cd {bot_dir} && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt")
        print(out)
        if status != 0:
            print("[!] Failed to set up venv.")
            ssh.close()
            sys.exit(1)
    else:
        print("[+] venv exists.")

    # Install paramiko is not needed on VPS, but ensure requirements are current
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
    out, err, status = run_command(ssh, start_cmd)
    time.sleep(3)

    # Verify process is running
    out, err, status = run_command(ssh, "ps aux | grep -E 'python.*main.py' | grep -v grep")
    if out:
        print("[+] Bot process is running:")
        print(out)
    else:
        print("[!] Bot process not found after start.")
        # Show tail of output log
        out, err, _ = run_command(ssh, f"tail -n 30 {bot_dir}/bot.out")
        print("Last bot output:")
        print(out)

    ssh.close()
    print("[+] Done.")


if __name__ == "__main__":
    main()
