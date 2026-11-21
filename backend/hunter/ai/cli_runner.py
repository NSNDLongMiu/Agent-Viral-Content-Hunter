"""Bounded, shell-free execution for subscription CLI adapters."""

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

FORBIDDEN_ENV = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY",
    "GEMINI_API_KEY", "GEMINI_BASE_URL", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GEMINI_BASE_URL",
    "GOOGLE_VERTEX_BASE_URL", "NODE_OPTIONS",
})
OUTPUT_LIMIT = 1024 * 1024
_CLEANUP_SECONDS = 1.0


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {
        name: source[name] for name in source
        if name.upper() not in FORBIDDEN_ENV and not name.upper().endswith("_API_KEY")
    }


@dataclass(frozen=True)
class RunResult:
    """Raw streams are for machine parsing only and are excluded from diagnostics."""

    exit_code: int | None
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    timed_out: bool = False
    truncated: bool = False


class Runner(Protocol):
    async def run(
        self, argv: Sequence[str], *, timeout: float, stdin: str | None = None,
        cwd: Path | None = None,
    ) -> RunResult: ...


class ProcessSpawner(Protocol):
    async def __call__(
        self, program: str, /, *args: str, stdin: int, stdout: int, stderr: int,
        env: Mapping[str, str], cwd: Path | None = None, start_new_session: bool = False,
    ) -> asyncio.subprocess.Process: ...


async def _capture(stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
    data = bytearray()
    truncated = False
    while chunk := await stream.read(64 * 1024):
        remaining = limit - len(data)
        truncated |= len(chunk) > remaining
        data.extend(chunk[:remaining])
    return data.decode("utf-8", errors="replace"), truncated


async def _communicate(
    process: asyncio.subprocess.Process, stdin: str | None, limit: int,
) -> RunResult:
    async def write_input() -> None:
        if process.stdin is None:
            return
        try:
            assert stdin is not None
            process.stdin.write(stdin.encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    assert process.stdout is not None and process.stderr is not None
    exit_code, stdout, stderr, _ = await asyncio.gather(
        process.wait(), _capture(process.stdout, limit // 2),
        _capture(process.stderr, limit - limit // 2), write_input(),
    )
    return RunResult(exit_code, stdout[0], stderr[0], truncated=stdout[1] or stderr[1])


class SubprocessRunner:
    def __init__(
        self, *, spawn: ProcessSpawner = asyncio.create_subprocess_exec,
        windows: bool = os.name == "nt", output_limit: int = OUTPUT_LIMIT,
    ) -> None:
        if output_limit < 2:
            raise ValueError("The capture limit must be at least two bytes")
        self._spawn = spawn
        self._windows = windows
        self._output_limit = output_limit

    async def run(
        self, argv: Sequence[str], *, timeout: float, stdin: str | None = None,
        cwd: Path | None = None,
    ) -> RunResult:
        if self._windows and Path(argv[0]).suffix.lower() in {".bat", ".cmd", ".ps1"}:
            raise FileNotFoundError("A native CLI executable is required on Windows")
        env = child_environment()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            async with asyncio.timeout_at(deadline):
                process = await self._spawn(
                    *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
                    start_new_session=not self._windows,
                )
        except TimeoutError:
            return RunResult(None, timed_out=True)
        communication = asyncio.create_task(_communicate(process, stdin, self._output_limit))
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(communication)
        except TimeoutError:
            await self._stop(process, communication, env)
            return RunResult(None, timed_out=True)
        except BaseException:
            await self._stop(process, communication, env)
            raise

    async def _stop(
        self, process: asyncio.subprocess.Process, communication: asyncio.Task[RunResult],
        env: Mapping[str, str],
    ) -> None:
        try:
            if self._windows:
                await self._taskkill(process.pid, env)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            if process.returncode is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        try:
            await asyncio.wait_for(asyncio.shield(communication), _CLEANUP_SECONDS)
        except (TimeoutError, OSError):
            communication.cancel()
            await asyncio.gather(communication, return_exceptions=True)

    async def _taskkill(self, pid: int, env: Mapping[str, str]) -> None:
        system_root = env.get("SYSTEMROOT") or env.get("SystemRoot") or r"C:\Windows"
        executable = Path(system_root) / "System32" / "taskkill.exe"
        async with asyncio.timeout(_CLEANUP_SECONDS):
            killer = await self._spawn(
                str(executable), "/T", "/F", "/PID", str(pid), env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                if await killer.wait() != 0:
                    raise OSError("Windows process-tree termination failed")
            except asyncio.CancelledError:
                try:
                    killer.terminate()
                except OSError:
                    pass
                raise
