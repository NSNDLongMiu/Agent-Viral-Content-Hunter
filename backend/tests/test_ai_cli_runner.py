import asyncio
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from hunter.ai.cli_runner import FORBIDDEN_ENV, SubprocessRunner, child_environment


class FakeEnvironment(Mapping[str, str]):
    def __iter__(self) -> Iterator[str]:
        return iter((*FORBIDDEN_ENV, "EXAMPLE_API_KEY", "FIXTURE_ALLOWED"))

    def __len__(self) -> int:
        return len(FORBIDDEN_ENV) + 2

    def __getitem__(self, name: str) -> str:
        assert name == "FIXTURE_ALLOWED", "Forbidden variable values must never be read"
        return "fixture"


class FakeProcess:
    def __init__(self, exit_code: int | None, *, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.pid = 2701
        self.returncode = None
        self.stdin: FakeStdin | None = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        self.finished = asyncio.Event()
        self.terminated = False
        if exit_code is not None:
            self.finish(exit_code)

    def finish(self, exit_code: int) -> None:
        self.returncode = exit_code
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.finished.set()

    def terminate(self) -> None:
        self.terminated = True
        self.finish(1)

    async def wait(self) -> int:
        await self.finished.wait()
        assert self.returncode is not None
        return self.returncode


class FakeStdin:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_child_environment_does_not_read_forbidden_values() -> None:
    assert child_environment(FakeEnvironment()) == {"FIXTURE_ALLOWED": "fixture"}
    assert child_environment({"openai_api_key": "fixture", "Path": "fixture"}) == {"Path": "fixture"}


def test_runner_uses_filtered_environment_and_caps_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hunter.ai.cli_runner.os", SimpleNamespace(environ=FakeEnvironment()))

    async def spawn(
        program: str, /, *args: str, stdin: int, stdout: int, stderr: int,
        env: Mapping[str, str], cwd: Path | None = None, start_new_session: bool = False,
    ) -> asyncio.subprocess.Process:
        assert (program, *args) == ("fixture.exe", "a; b")
        assert env == {"FIXTURE_ALLOWED": "fixture"}
        assert stdin == asyncio.subprocess.DEVNULL
        assert stdout == stderr == asyncio.subprocess.PIPE
        fake = FakeProcess(0, stdout=b"1234567890", stderr=b"abcdefghij")
        return cast(asyncio.subprocess.Process, fake)

    result = asyncio.run(SubprocessRunner(spawn=spawn, output_limit=12).run(
        ["fixture.exe", "a; b"], timeout=1,
    ))
    assert (result.exit_code, result.stdout, result.stderr) == (0, "123456", "abcdef")
    assert result.truncated and "123456" not in repr(result) and "abcdef" not in repr(result)


def test_runner_sends_prompt_as_utf8_on_stdin() -> None:
    prompt = "fixture: dữ liệu & |"
    pipe = FakeStdin()

    async def spawn(
        program: str, /, *args: str, stdin: int, stdout: int, stderr: int,
        env: Mapping[str, str], cwd: Path | None = None, start_new_session: bool = False,
    ) -> asyncio.subprocess.Process:
        assert stdin == asyncio.subprocess.PIPE
        assert (program, args) == ("fixture.exe", ("-p", ""))
        fake = FakeProcess(0)
        fake.stdin = pipe
        return cast(asyncio.subprocess.Process, fake)

    result = asyncio.run(SubprocessRunner(spawn=spawn).run(
        ["fixture.exe", "-p", ""], timeout=1, stdin=prompt,
    ))
    assert result.exit_code == 0
    assert pipe.closed and pipe.data.decode("utf-8") == prompt


@pytest.mark.parametrize("tree_succeeds", [True, False])
def test_timeout_uses_injected_windows_tree_kill_then_fallback(tree_succeeds: bool) -> None:
    async def check() -> None:
        process = FakeProcess(None)
        calls: list[tuple[str, ...]] = []

        async def spawn(
            program: str, /, *args: str, stdin: int, stdout: int, stderr: int,
            env: Mapping[str, str], cwd: Path | None = None, start_new_session: bool = False,
        ) -> asyncio.subprocess.Process:
            calls.append((program, *args))
            assert not any(name.upper() in FORBIDDEN_ENV for name in env)
            if len(calls) == 1:
                return cast(asyncio.subprocess.Process, process)
            if tree_succeeds:
                process.finish(1)
                return cast(asyncio.subprocess.Process, FakeProcess(0))
            raise PermissionError("fixture access denied")

        result = await SubprocessRunner(spawn=spawn, windows=True).run(["fixture.exe"], timeout=0.02)
        assert result.timed_out and result.exit_code is None
        assert calls[1][0].lower().endswith("taskkill.exe")
        assert calls[1][1:] == ("/T", "/F", "/PID", str(process.pid))
        assert process.terminated is (not tree_succeeds)

    asyncio.run(check())
