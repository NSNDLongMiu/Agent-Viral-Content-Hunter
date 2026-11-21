"""Explicitly opted-in Claude Code analysis using a subscription login."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hunter.config import BudgetSettings
from hunter.interfaces import AIResult, AIStatus, AITask
from hunter.models import AIName

from ._adapter import (
    CLIAdapter, analysis_prompt, failure, failure_status, structured_result, subscription_executable,
)
from .cli_runner import Runner

_DISABLED = "Headless Claude is off until the user confirms paid usage credits are disabled."
_FAILURE_TEXT = {
    AIStatus.QUOTA_EXHAUSTED: ("usage limit", "rate limit", "quota", "hit your limit"),
    AIStatus.AUTH_LOST: ("not logged in", "sign in", "please run /login", "unauthorized"),
}


class ClaudeAdapter(CLIAdapter):
    name = AIName.CLAUDE

    def __init__(
        self, *, enabled: bool = False, runner: Runner | None = None,
        executable: str | Path | None = None, budget: BudgetSettings | None = None,
    ) -> None:
        super().__init__(
            runner=runner, executable=executable, budget=budget,
            initial_reason="No CLI outcome has been observed." if enabled else _DISABLED,
        )
        self.enabled = enabled

    async def _run(self, task: AITask) -> AIResult:
        if not self.enabled:
            return failure(AIStatus.UNAVAILABLE, _DISABLED)
        executable = subscription_executable(self.name, self.executable)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + task.timeout_seconds
        with TemporaryDirectory(prefix="hunter-claude-") as folder:
            workdir = Path(folder)
            auth = await self.runner.run(
                [executable, "auth", "status", "--json"],
                timeout=min(task.timeout_seconds, 10), cwd=workdir,
            )
            if auth.timed_out:
                return failure(AIStatus.TIMEOUT)
            try:
                login = json.loads(auth.stdout)
            except ValueError:
                login = None
            if (
                auth.exit_code != 0 or not isinstance(login, dict)
                or login.get("loggedIn") is not True or login.get("apiProvider") != "firstParty"
                or login.get("authMethod") not in ("claude.ai", "claudeai", "oauth")
                or login.get("subscriptionType") not in ("pro", "max", "ultra", "team", "enterprise")
            ):
                return failure(AIStatus.AUTH_LOST, "A Claude subscription login could not be verified.")
            remaining = deadline - loop.time()
            if remaining <= 0:
                return failure(AIStatus.TIMEOUT)
            result = await self.runner.run(
                [
                    executable, "-p", "--output-format", "json", "--no-session-persistence",
                    "--restricted", "--strict-mcp-config", "--setting-sources", "", "--tools", "",
                ],
                stdin=analysis_prompt(task), timeout=remaining, cwd=workdir,
            )
        if result.timed_out:
            return failure(AIStatus.TIMEOUT)
        diagnostic = result.stderr + "\n" + result.stdout
        if result.exit_code != 0 or result.truncated:
            return failure(failure_status(diagnostic, _FAILURE_TEXT))
        envelope = json.loads(result.stdout)
        if not isinstance(envelope, dict) or envelope.get("type") != "result":
            return failure(AIStatus.ERROR)
        if envelope.get("is_error") is not False:
            return failure(failure_status(diagnostic, _FAILURE_TEXT))
        response = envelope.get("result")
        if not isinstance(response, str):
            return failure(AIStatus.ERROR)
        return structured_result(task, response)
