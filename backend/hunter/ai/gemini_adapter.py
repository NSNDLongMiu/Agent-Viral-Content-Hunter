"""Gemini analysis through Antigravity CLI.

The quota and authentication text patterns are unverified against live agy failures.
"""

import json
import math
import os
import re
import shutil
from pathlib import Path
from subprocess import list2cmdline
from tempfile import TemporaryDirectory

from hunter.config import BudgetSettings
from hunter.interfaces import AIResult, AIStatus, AITask
from hunter.models import AIName

from ._adapter import (
    CLIAdapter, analysis_prompt, failure, failure_excerpt, failure_status,
)
from .cli_runner import Runner

_PROMPT_LIMIT = 24_000
_WINDOWS_COMMAND_LIMIT = 32_767
_PROMPT_LIMIT_ERROR = "prompt too long for the CLI argument limit"
FAILURE_TEXT = {
    AIStatus.QUOTA_EXHAUSTED: ("quota", "rate limit"),
    AIStatus.AUTH_LOST: ("sign in", "login", "unauthorized"),
    AIStatus.TIMEOUT: ("timed out", "deadline exceeded"),
}


def agy_executable(configured: str | None) -> str:
    if configured is not None:
        return configured
    if found := shutil.which("agy"):
        return found
    if local := os.environ.get("LOCALAPPDATA"):
        candidate = Path(local) / "agy" / "bin" / "agy.exe"
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError


class GeminiAdapter(CLIAdapter):
    name = AIName.GEMINI

    def __init__(
        self, *, runner: Runner | None = None, executable: str | Path | None = None,
        budget: BudgetSettings | None = None, model: str = "gemini-3.8-flash-high",
    ) -> None:
        super().__init__(runner=runner, executable=executable, budget=budget)
        self.model = model

    async def _run(self, task: AITask) -> AIResult:
        prompt = analysis_prompt(task)
        if len(prompt) > _PROMPT_LIMIT:
            return failure(AIStatus.ERROR, _PROMPT_LIMIT_ERROR)
        executable = agy_executable(self.executable)
        with TemporaryDirectory(prefix="hunter-agy-") as folder:
            workdir = Path(folder)
            schema = workdir / "schema.json"
            argv = [
                executable, "-p", prompt, "--output-format", "json", "--model", self.model,
                "--mode", "plan", "--print-timeout", f"{math.ceil(task.timeout_seconds)}s",
                "--json-schema", str(schema), "--sandbox",
            ]
            if os.name == "nt":
                command_length = len(list2cmdline(argv).encode("utf-16-le", errors="surrogatepass")) // 2
                if command_length >= _WINDOWS_COMMAND_LIMIT:  # Count the terminating NUL as well.
                    return failure(AIStatus.ERROR, _PROMPT_LIMIT_ERROR)
            schema.write_text(json.dumps(task.output_schema, allow_nan=False), encoding="utf-8")
            result = await self.runner.run(argv, timeout=task.timeout_seconds, cwd=workdir)
        if result.timed_out:
            return failure(AIStatus.TIMEOUT)
        diagnostic = result.stderr + "\n" + result.stdout
        process_failed = result.exit_code != 0 or result.truncated
        try:
            decoded = json.loads(result.stdout)
        except (ValueError, RecursionError):
            decoded = {}
        envelope = decoded if isinstance(decoded, dict) else {}
        envelope_status = envelope.get("status")
        if process_failed or envelope_status != "SUCCESS":
            status = AIStatus.ERROR
            if not process_failed and envelope_status == "TIMEOUT":
                status = AIStatus.TIMEOUT
            elif process_failed or isinstance(decoded, dict):
                status = failure_status(diagnostic, FAILURE_TEXT)
            error = envelope.get("error")
            return failure(status, failure_excerpt(
                prompt, FAILURE_TEXT, result, error=error if isinstance(error, str) else None,
            ))
        if envelope.get("denied_actions"):
            return failure(AIStatus.ERROR, "Antigravity reported denied actions.")
        output = envelope.get("structured_output")
        if not isinstance(output, dict):
            response = envelope.get("response")
            if not isinstance(response, str) or not response.strip():
                return failure(AIStatus.ERROR, "Antigravity returned an empty response.")
            response = re.sub(r"\A```(?:json)?[ \t]*\r?\n", "", response.lstrip(), flags=re.I)
            # A closing fence or repeated response may follow the first object.
            output, _ = json.JSONDecoder().raw_decode(response.lstrip())
            if not isinstance(output, dict):
                return failure(AIStatus.ERROR)
        json.dumps(output, allow_nan=False)
        return AIResult.success(task, output)
