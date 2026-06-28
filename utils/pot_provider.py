# utils/pot_provider.py
"""Async lifecycle manager for the bgutil-ytdlp-pot-provider Node server."""

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import config

logger = logging.getLogger(__name__)


class PotProviderManager:
    """Builds, patches, starts, monitors, and stops the bgutil POT HTTP server."""

    def __init__(
        self,
        provider_path: str | None = None,
        port: int | None = None,
        plugin_path: str | None = None,
    ):
        self.provider_path = Path(provider_path or config.YTDLP_POT_PROVIDER_PATH).resolve()
        self.port = port or config.YTDLP_POT_PORT
        self.plugin_path = Path(plugin_path or config.YTDLP_POT_PLUGIN_PATH).resolve()
        self.build_path = self.provider_path / "build"
        self.main_js = self.build_path / "main.js"
        self.proc: asyncio.subprocess.Process | None = None
        self._last_health_ok = False
        self._consecutive_failures = 0
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Build / patch helpers
    # ------------------------------------------------------------------
    def _node_version_ok(self) -> bool:
        """Return True if Node.js >= 20 is available."""
        try:
            result = shutil.which("node")
            if not result:
                return False
            output = os.popen("node -p 'process.version'").read().strip()
            if not output.startswith("v"):
                return False
            major = int(output[1:].split(".")[0])
            return major >= 20
        except Exception:
            return False

    async def _run_npm(self, *args, cwd: Path) -> None:
        cmd = ["npm", *args]
        logger.info(f"[POT] Running: {' '.join(cmd)} in {cwd}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"npm {' '.join(args)} failed (exit {proc.returncode}):\n"
                f"{stdout.decode(errors='replace')}\n{stderr.decode(errors='replace')}"
            )
        logger.info(f"[POT] npm {' '.join(args)} completed")

    async def _ensure_build(self) -> None:
        if not self._node_version_ok():
            raise RuntimeError(
                "Node.js >= 20 is required for the PO-token provider. "
                "Install it with: sudo apt-get install -y nodejs"
            )

        node_modules = self.provider_path / "node_modules"
        if not node_modules.exists():
            await self._run_npm("ci", cwd=self.provider_path)

        # Build if missing or source is newer
        src_main = self.provider_path / "src" / "main.ts"
        if not self.main_js.exists() or (
            src_main.exists() and self.main_js.stat().st_mtime < src_main.stat().st_mtime
        ):
            await self._run_npm("exec", "tsc", cwd=self.provider_path)

        self._patch_bind_host()

    def _patch_bind_host(self) -> None:
        """Force the built server to bind only to 127.0.0.1. Idempotent."""
        if not self.main_js.exists():
            return
        content = self.main_js.read_text(encoding="utf-8")
        marker = '// BALEBOT_LOCALHOST_PATCH'
        if marker in content:
            return

        patched = content.replace('host: "::",', f'host: "127.0.0.1", {marker}')
        patched = patched.replace('host: "0.0.0.0",', f'host: "127.0.0.1", {marker}')
        if patched == content:
            # If the upstream code changed shape, append a warning comment so we notice
            patched += f"\n{marker}\n"
        self.main_js.write_text(patched, encoding="utf-8")
        logger.info(f"[POT] Patched {self.main_js} to bind localhost only")

    def _yt_dlp_plugins_dir(self) -> Path:
        """Return a writable yt-dlp plugins directory."""
        candidates = [
            Path.home() / ".yt-dlp" / "plugins",
        ]
        # Also try to place it next to the yt_dlp package so it is discovered
        try:
            import yt_dlp
            candidates.append(Path(yt_dlp.__file__).parent.parent / "yt_dlp_plugins")
        except Exception:
            pass

        for directory in candidates:
            directory.mkdir(parents=True, exist_ok=True)
            test_file = directory / ".write_test"
            try:
                test_file.write_text("ok")
                test_file.unlink()
                return directory
            except OSError:
                continue
        # Fallback: create inside the project
        fallback = Path.cwd() / "yt_dlp_plugins"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _install_plugin(self) -> None:
        """Symlink or copy the bgutil plugin so yt-dlp discovers it."""
        plugins_dir = self._yt_dlp_plugins_dir()
        link_name = plugins_dir / "bgutil"
        if link_name.exists() or link_name.is_symlink():
            try:
                if link_name.is_symlink() and Path(os.readlink(link_name)).resolve() == self.plugin_path:
                    return
                if link_name.is_dir():
                    shutil.rmtree(link_name)
                else:
                    link_name.unlink()
            except Exception:
                pass

        try:
            os.symlink(self.plugin_path, link_name, target_is_directory=True)
            logger.info(f"[POT] Linked plugin: {link_name} -> {self.plugin_path}")
        except OSError:
            shutil.copytree(self.plugin_path, link_name, dirs_exist_ok=True)
            logger.info(f"[POT] Copied plugin to: {link_name}")

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------
    async def _pipe_logger(self, stream: asyncio.StreamReader | None, prefix: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.info(f"{prefix} {text}")

    async def start(self) -> None:
        if self._running:
            return

        await self._ensure_build()
        self._install_plugin()

        cmd = ["node", str(self.main_js), "--port", str(self.port)]
        logger.info(f"[POT] Starting server: {' '.join(cmd)}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.provider_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._running = True

        self._stdout_task = asyncio.create_task(
            self._pipe_logger(self.proc.stdout, "[POT stdout]")
        )
        self._stderr_task = asyncio.create_task(
            self._pipe_logger(self.proc.stderr, "[POT stderr]")
        )

        # Wait briefly for the server to come up
        for _ in range(20):
            await asyncio.sleep(0.25)
            if self.proc.returncode is not None:
                raise RuntimeError(
                    f"PO-token provider exited early with code {self.proc.returncode}"
                )
            try:
                if await self._ping():
                    self._last_health_ok = True
                    self._consecutive_failures = 0
                    logger.info(f"[POT] Provider is healthy on 127.0.0.1:{self.port}")
                    return
            except Exception:
                pass

        raise RuntimeError("PO-token provider did not become healthy within 5 seconds")

    async def stop(self) -> None:
        self._running = False
        if self.proc is None:
            return

        try:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("[POT] Provider did not terminate gracefully, killing it")
                self.proc.kill()
                await self.proc.wait()
        except ProcessLookupError:
            pass
        finally:
            self.proc = None
            for task in (self._stdout_task, self._stderr_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self._stdout_task = None
            self._stderr_task = None
            logger.info("[POT] Provider stopped cleanly")

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------
    async def _ping(self) -> bool:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            request = (
                f"GET /ping HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()

            response = b""
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                response += chunk

            if b"200 OK" not in response:
                return False
            body = response.split(b"\r\n\r\n", 1)[-1]
            data = json.loads(body.decode("utf-8", errors="replace"))
            return isinstance(data.get("server_uptime"), (int, float))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def health_check_loop(self) -> None:
        """Run forever while the bot is up; restart the provider if it dies."""
        while self._running:
            await asyncio.sleep(10)
            if not self._running:
                break

            if self.proc is None or self.proc.returncode is not None:
                logger.warning("[POT] Provider process is gone; will restart")
                self._consecutive_failures += 1
            else:
                try:
                    ok = await self._ping()
                except Exception as exc:
                    logger.debug(f"[POT] Health ping failed: {exc}")
                    ok = False

                if ok:
                    self._last_health_ok = True
                    self._consecutive_failures = 0
                    continue

                self._consecutive_failures += 1
                logger.warning(
                    f"[POT] Provider health check failed "
                    f"({self._consecutive_failures} times)"
                )

            # Restart with backoff
            try:
                await self.stop()
            except Exception as exc:
                logger.warning(f"[POT] Error stopping provider for restart: {exc}")

            backoff = min(60, 5 * (2 ** (self._consecutive_failures - 1)))
            logger.info(f"[POT] Restarting provider in {backoff}s...")
            await asyncio.sleep(backoff)

            try:
                await self.start()
            except Exception as exc:
                logger.error(f"[POT] Failed to restart provider: {exc}")

    def is_running(self) -> bool:
        if not self._running or self.proc is None:
            return False
        if self.proc.returncode is not None:
            return False
        return self._last_health_ok
