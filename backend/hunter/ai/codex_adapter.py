"""Structured analysis through the official Codex CLI and ChatGPT login."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hunter.interfaces import AIResult, AIStatus, AITask
from hunter.models import AIName

from ._adapter import (
    CLIAdapter, analysis_prompt, failure, failure_excerpt, failure_status, structured_result,
    subscription_executable,
)
from .cli_runner import OUTPUT_LIMIT

FAILURE_TEXT = {
    AIStatus.QUOTA_EXHAUSTED: ("you've hit your usage limit", "usage limit", "try again at"),
    AIStatus.AUTH_LOST: (
        "access token could not be refreshed", "signed in to another account",
        "please sign in again", "not logged in",
    ),
}


class CodexAdapter(CLIAdapter):
    name = AIName.CODEX

    async def _run(self, task: AITask) -> AIResult:
        executable = subscription_executable(self.name, self.executable)
        with TemporaryDirectory(prefix="hunter-codex-") as folder:
            workdir = Path(folder)
            schema = workdir / "schema.json"
            message = workdir / "last-message.json"
            schema.write_text(json.dumps(task.output_schema, allow_nan=False), encoding="utf-8")
            prompt = analysis_prompt(task)
            result = await self.runner.run(
                [
                    executable, "exec", "--json", "--output-schema", str(schema),
                    "--output-last-message", str(message), "--sandbox", "read-only",
                    "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                    "-c", "model_provider=openai", "-c", "forced_login_method=chatgpt",
                    "-c", "approval_policy=never", "-c", "web_search=disabled",
                    "-c", "mcp_servers={}", "-",
                ],
                stdin=prompt, timeout=task.timeout_seconds, cwd=workdir,
            )
            if result.timed_out:
                return failure(AIStatus.TIMEOUT)
            diagnostic = result.stderr + "\n" + result.stdout

            final_text = ""
            completed = False
            failed = False
            errors: list[str] = []
            error_message: str | None = None
            for line in result.stdout.splitlines():
                try:
                    event = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") in ("turn.failed", "error"):
                    errors.append(line)
                    error = event.get("error")
                    if isinstance(error, dict):
                        error = error.get("message")
                    if not isinstance(error, str):
                        error = event.get("message")
                    if isinstance(error, str) and error.strip():
                        error_message = error
                if event.get("type") == "turn.failed":
                    failed = True
                if event.get("type") == "turn.completed":
                    completed = True
                item = event.get("item")
                if event.get("type") == "item.completed" and isinstance(item, dict):
                    if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                        final_text = item["text"]
            if result.exit_code != 0 or failed or (errors and not completed):
                if result.exit_code == 0:
                    diagnostic = "\n".join([result.stderr, *errors])
                return failure(failure_status(diagnostic, FAILURE_TEXT), failure_excerpt(
                    prompt, FAILURE_TEXT, result, error=error_message,
                ))
            if message.is_file():
                with message.open("rb") as file:
                    captured = file.read(OUTPUT_LIMIT + 1)
                if len(captured) > OUTPUT_LIMIT:
                    return failure(AIStatus.ERROR, "The Codex output exceeded the capture limit.")
                return structured_result(task, captured.decode("utf-8"))
            if completed and not result.truncated:
                return structured_result(task, final_text)
            status = failure_status(diagnostic, FAILURE_TEXT)
            excerpt = failure_excerpt(prompt, FAILURE_TEXT, result)
            if status != AIStatus.ERROR:
                return failure(status, excerpt)
            return failure(AIStatus.ERROR, excerpt or "Codex returned no final structured response.")
