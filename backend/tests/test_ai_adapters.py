import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from hunter.ai import ClaudeAdapter, CodexAdapter, GeminiAdapter, LocalAdapter
from hunter.ai._adapter import analysis_prompt
from hunter.ai.cli_runner import RunResult
from hunter.ai.smoke import _probe
from hunter.config import BudgetSettings, PaidAPIForbidden
from hunter.db import Database
from hunter.interfaces import AIStatus, AITask
from hunter.orchestrator import report_adapters_health, report_health
from hunter.services.monitor import MonitorService


class FakeRunner:
    def __init__(self, *results: RunResult | OSError | Callable[[Sequence[str]], RunResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[Sequence[str], str | None, float, Path | None]] = []

    async def run(
        self, argv: Sequence[str], *, timeout: float, stdin: str | None = None, cwd: Path | None = None,
    ) -> RunResult:
        self.calls.append((argv, stdin, timeout, cwd))
        result = next(self.results)
        if isinstance(result, OSError):
            raise result
        return result(argv) if callable(result) else result


class FakeAgyRunner(FakeRunner):
    async def run(
        self, argv: Sequence[str], *, timeout: float, stdin: str | None = None, cwd: Path | None = None,
    ) -> RunResult:
        if argv[argv.index("-p") + 1] == "":
            self.calls.append((argv, stdin, timeout, cwd))
            return RunResult(1, json.dumps({
                "status": "ERROR", "response": "",
                "error": 'Error: empty prompt. Usage: agy --print "your prompt here"',
            }))
        return await super().run(argv, timeout=timeout, stdin=stdin, cwd=cwd)


@pytest.fixture
def ai_task() -> AITask:
    return AITask(
        id="fixture-task", instructions="Answer the fixture question.", input={"text": "xin chào"},
        output_schema={
            "type": "object", "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"], "additionalProperties": False,
        },
    )


@pytest.mark.parametrize(("text", "status"), [
    ("You've hit your usage limit", AIStatus.QUOTA_EXHAUSTED),
    ("USAGE LIMIT", AIStatus.QUOTA_EXHAUSTED),
    ("try again at 08:00", AIStatus.QUOTA_EXHAUSTED),
    ("Access token could not be refreshed", AIStatus.AUTH_LOST),
    ("signed in to another account", AIStatus.AUTH_LOST),
    ("PLEASE SIGN IN AGAIN", AIStatus.AUTH_LOST),
    ("not logged in", AIStatus.AUTH_LOST),
    ("unrecognized failure", AIStatus.ERROR),
])
def test_codex_failure_text(text: str, status: AIStatus, ai_task: AITask) -> None:
    runner = FakeRunner(RunResult(1, stderr=f"{text} Bearer fixture-credential"))
    adapter = CodexAdapter(executable="fixture-codex.exe", runner=runner)
    assert adapter.health().status == AIStatus.UNAVAILABLE
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == adapter.health().status == status
    assert adapter.health().available is False
    assert adapter.health().quota_exhausted is (status == AIStatus.QUOTA_EXHAUSTED)
    assert result.error == adapter.health().last_error == f"{text} [redacted]"


def test_codex_structured_file_and_prompt_delivery(ai_task: AITask) -> None:
    def write_response(argv: Sequence[str]) -> RunResult:
        schema = Path(argv[argv.index("--output-schema") + 1])
        assert json.loads(schema.read_text(encoding="utf-8")) == ai_task.output_schema
        response = Path(argv[argv.index("--output-last-message") + 1])
        response.write_text('{"ok": true}', encoding="utf-8")
        return RunResult(0)

    runner = FakeRunner(write_response)
    adapter = CodexAdapter(executable="fixture-codex.exe", runner=runner)
    assert asyncio.run(adapter.run(ai_task)).output == {"ok": True}
    assert adapter.health().status == AIStatus.OK
    assert adapter.health().available
    argv, stdin, timeout, cwd = runner.calls[0]
    assert argv[:3] == ["fixture-codex.exe", "exec", "--json"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "forced_login_method=chatgpt" in argv
    assert stdin is not None and "xin chào" in stdin and "Do not use tools" in stdin
    assert argv[-1] == "-" and "xin chào" not in argv
    assert timeout == ai_task.timeout_seconds
    assert cwd is not None and not cwd.exists()


def test_codex_reads_completed_jsonl_and_classifies_failed_turn(ai_task: AITask) -> None:
    event = json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": '{"ok": true}',
    }})
    completed = json.dumps({"type": "turn.completed"})
    failed = json.dumps({"type": "turn.failed", "error": {"message": "not logged in"}})
    adapter = CodexAdapter(executable="fixture-codex.exe", runner=FakeRunner(
        RunResult(0, f"{event}\n{completed}"), RunResult(0, f"{event}\n{failed}"),
    ))
    assert asyncio.run(adapter.run(ai_task)).status == AIStatus.OK
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == AIStatus.AUTH_LOST
    assert result.error == adapter.health().last_error == "not logged in"


@pytest.mark.parametrize(("result", "status"), [
    (RunResult(None, timed_out=True), AIStatus.TIMEOUT),
    (FileNotFoundError("fixture-private-path"), AIStatus.UNAVAILABLE),
    (RunResult(0, "unparseable"), AIStatus.ERROR),
    (RunResult(0, stderr="Please sign in again"), AIStatus.AUTH_LOST),
])
def test_codex_runner_outcomes(
    result: RunResult | OSError, status: AIStatus, ai_task: AITask,
) -> None:
    adapter = CodexAdapter(executable="fixture-codex.exe", runner=FakeRunner(result))
    assert asyncio.run(adapter.run(ai_task)).status == status


@pytest.mark.parametrize(("envelope_fields", "expected_output"), [
    ({"response": '{"ok": true}\n{"ok":true}\n', "structured_output": {"ok": True}}, {"ok": True}),
    ({
        "response": '```json\n{"ok": false}\n```\n{"ok":true}\n',
        "structured_output": {"ok": True},
    }, {"ok": True}),
    ({"response": '```json\n{"ok": true}\n```\n{"ok":false}\n'}, {"ok": True}),
    ({"response": '{"ok": true}\n{"ok":false}\n', "structured_output": []}, {"ok": True}),
    ({"response": '{"ok": true}'}, {"ok": True}),
    ({"response": '```json\n{"ok": true}\n```'}, {"ok": True}),
    ({"response": "", "structured_output": {"ok": True}}, {"ok": True}),
    ({"response": ""}, None),
    ({"response": " \n"}, None),
    ({
        "response": '{"ok": true}', "structured_output": {"ok": True},
        "denied_actions": ["fixture-denied-command"],
    }, None),
    ({"response": '{"ok": true}', "structured_output": {"ok": "true"}}, None),
    ({"response": '{"ok": "true"}'}, None),
    ({"response": "[]"}, None),
    ({"response": "unparseable Bearer fixture-credential"}, None),
])
def test_agy_success_envelope(
    envelope_fields: dict[str, object], expected_output: dict[str, bool] | None, ai_task: AITask,
) -> None:
    def fixture_agy(argv: Sequence[str]) -> RunResult:
        schema = Path(argv[argv.index("--json-schema") + 1])
        json_schema = json.loads(schema.read_text(encoding="utf-8"))
        assert json_schema == ai_task.output_schema
        return RunResult(0, json.dumps({
            "conversation_id": "fixture-conversation", "status": "SUCCESS",
            "duration_seconds": 7.7, "num_turns": 2, "json_schema": json_schema, "usage": {},
            **envelope_fields,
        }))

    runner = FakeAgyRunner(fixture_agy)
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=runner, model="fixture-model")
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == (AIStatus.ERROR if expected_output is None else AIStatus.OK)
    assert result.output == expected_output
    assert "fixture-denied-command" not in repr(result)
    assert "fixture-credential" not in repr(result)
    argv, stdin, timeout, _ = runner.calls[0]
    assert argv[:5] == ["fixture-agy.exe", "-p", analysis_prompt(ai_task), "--output-format", "json"]
    assert argv[argv.index("--mode") + 1] == "plan"
    assert argv[argv.index("--model") + 1] == "fixture-model"
    assert argv[argv.index("--print-timeout") + 1] == f"{int(timeout)}s"
    assert "--disable-slash-commands" not in argv and "--sandbox" in argv
    assert stdin is None and "xin chào" in argv[2] and "Do not use tools" in argv[2]


def test_analysis_prompt_has_fixed_prefix_for_dash_instructions(ai_task: AITask) -> None:
    task = ai_task.model_copy(update={"instructions": "--mode accept-edits"})
    prompt = analysis_prompt(task)
    assert prompt.startswith("Use only the supplied input. ")
    assert "\n\n--mode accept-edits\n\n" in prompt


@pytest.mark.parametrize("length", [24_000, 24_001])
def test_agy_prompt_argument_limit(length: int, ai_task: AITask) -> None:
    task = ai_task.model_copy(update={"instructions": "x"})
    task = task.model_copy(update={"instructions": "x" * (length - len(analysis_prompt(task)) + 1)})
    runner = FakeAgyRunner(RunResult(0, json.dumps({"status": "SUCCESS", "response": '{"ok": true}'})))
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=runner)
    prompt = analysis_prompt(task)
    assert len(prompt) == length
    result = asyncio.run(adapter.run(task))
    if length == 24_000:
        assert result.status == AIStatus.OK
        assert runner.calls[0][0][2] == prompt
    else:
        assert result.status == AIStatus.ERROR
        assert result.error == adapter.health().last_error == "prompt too long for the CLI argument limit"
        assert not runner.calls


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line limit")
def test_agy_checks_windows_utf16_command_length(ai_task: AITask) -> None:
    task = ai_task.model_copy(update={"instructions": "\U0001f680" * 17_000})
    runner = FakeAgyRunner()
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=runner)
    assert len(analysis_prompt(task)) < 24_000
    result = asyncio.run(adapter.run(task))
    assert result.status == AIStatus.ERROR
    assert result.error == "prompt too long for the CLI argument limit"
    assert not runner.calls


@pytest.mark.parametrize(("text", "status"), [
    ("Quota reached", AIStatus.QUOTA_EXHAUSTED),
    ("RATE LIMIT", AIStatus.QUOTA_EXHAUSTED),
    ("sign in", AIStatus.AUTH_LOST),
    ("LOGIN required", AIStatus.AUTH_LOST),
    ("unauthorized", AIStatus.AUTH_LOST),
    ("deadline exceeded", AIStatus.TIMEOUT),
    ("unexpected failure", AIStatus.ERROR),
])
def test_agy_failure_patterns(text: str, status: AIStatus, ai_task: AITask) -> None:
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=FakeAgyRunner(
        RunResult(0, json.dumps({"status": "FAILURE", "response": text, "structured_output": {"ok": True}})),
        RunResult(1, stderr=text),
    ))
    assert asyncio.run(adapter.run(ai_task)).status == status
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == status
    assert result.error == adapter.health().last_error == text


def test_agy_empty_print_error_is_visible_in_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["fixture-agy.exe", "-p", "", "--output-format", "json"]
    empty_print = asyncio.run(FakeAgyRunner().run(argv, stdin="fixture prompt", timeout=1))
    assert empty_print.exit_code == 1
    assert json.loads(empty_print.stdout) == {
        "status": "ERROR", "response": "",
        "error": 'Error: empty prompt. Usage: agy --print "your prompt here"',
    }
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=FakeAgyRunner(empty_print))
    assert asyncio.run(_probe(adapter)) == 1
    assert capsys.readouterr().out.startswith("ERROR Error: empty prompt.")
    assert (adapter.health().last_error or "").startswith("Error: empty prompt.")


@pytest.mark.parametrize(("exit_code", "detail_length"), [(0, 10), (1, 210)])
def test_cli_error_messages_are_redacted_and_bounded(ai_task: AITask, exit_code: int, detail_length: int) -> None:
    error = (
        "Service unavailable at https://fixture.invalid/path?token=fixture-url-secret "
        "Bearer fixture-credential " + "x" * detail_length + "\nfixture-private-file-contents"
    )
    gemini_stdout = json.dumps({"status": "ERROR", "error": error, "response": "fixture-response"})
    codex_stdout = json.dumps({"type": "error", "message": error})
    adapters = [
        GeminiAdapter(executable="fixture-agy.exe", runner=FakeAgyRunner(RunResult(exit_code, gemini_stdout))),
        CodexAdapter(executable="fixture-codex.exe", runner=FakeRunner(RunResult(exit_code, codex_stdout))),
    ]
    for adapter in adapters:
        result = asyncio.run(adapter.run(ai_task))
        assert result.status == AIStatus.ERROR
        assert result.error is not None and result.error == adapter.health().last_error
        expected = "Service unavailable at [redacted] [redacted] " + "x" * detail_length
        assert result.error == expected[:200]


def test_agy_stdout_failure_drops_prompt_echo(ai_task: AITask) -> None:
    stdout = f"Starting Antigravity\nError: invalid argument {analysis_prompt(ai_task)}"
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=FakeAgyRunner(RunResult(1, stdout)))
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == AIStatus.ERROR
    assert result.error == adapter.health().last_error == "Error: invalid argument"


def test_codex_stderr_failure_drops_inline_file_contents(ai_task: AITask) -> None:
    stderr = 'Starting Codex\nERROR invalid schema. File contents: {"private": "fixture-secret"}'
    adapter = CodexAdapter(executable="fixture-codex.exe", runner=FakeRunner(RunResult(1, stderr=stderr)))
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == AIStatus.ERROR
    assert result.error == adapter.health().last_error == "ERROR invalid schema."


def test_agy_skips_incomplete_diagnostic_lines_after_capture_truncation(ai_task: AITask) -> None:
    failure = RunResult(
        1, stdout="Error: request failed\n", stderr="Error: using sk-fixture", truncated=True,
    )
    adapter = GeminiAdapter(executable="fixture-agy.exe", runner=FakeAgyRunner(failure))
    result = asyncio.run(adapter.run(ai_task))
    assert result.status == AIStatus.ERROR
    assert result.error == adapter.health().last_error == "Error: request failed"


def test_disabled_claude_and_local_stay_unavailable(ai_task: AITask, tmp_path: Path) -> None:
    runner = FakeRunner()
    claude = ClaudeAdapter(runner=runner)
    local = LocalAdapter()
    assert claude.health().status == local.health().status == AIStatus.UNAVAILABLE
    assert asyncio.run(claude.run(ai_task)).status == AIStatus.UNAVAILABLE
    assert asyncio.run(local.run(ai_task)).status == AIStatus.UNAVAILABLE
    assert not runner.calls
    database = Database(tmp_path / "fixture.sqlite3")
    database.migrate()
    monitor = MonitorService(database)
    assert report_health(monitor, claude) == claude.health()
    expected = report_adapters_health(monitor, [claude, local])
    assert monitor.ai() == expected
    assert "paid usage credits are disabled" in (claude.health().last_error or "")


def test_enabled_claude_requires_subscription_auth(ai_task: AITask) -> None:
    login = {"loggedIn": True, "apiProvider": "firstParty", "authMethod": "claude.ai",
             "subscriptionType": "team"}
    runner = FakeRunner(
        RunResult(0, json.dumps({**login, "authMethod": "api_key"})),
        RunResult(0, json.dumps(login)),
        RunResult(0, json.dumps({"type": "result", "is_error": False, "result": '{"ok": true}'})),
    )
    adapter = ClaudeAdapter(enabled=True, executable="fixture-claude.exe", runner=runner)
    assert asyncio.run(adapter.run(ai_task)).status == AIStatus.AUTH_LOST
    assert len(runner.calls) == 1
    assert asyncio.run(adapter.run(ai_task)).output == {"ok": True}
    argv, stdin, _, _ = runner.calls[-1]
    assert argv[:4] == ["fixture-claude.exe", "-p", "--output-format", "json"]
    assert stdin is not None and "xin chào" in stdin


def test_budget_check_precedes_cli_invocation(ai_task: AITask) -> None:
    class DenyingFakeBudget(BudgetSettings):
        def require_allowed(self, *, incurs_cost: bool | None) -> None:
            assert incurs_cost is False
            raise PaidAPIForbidden("fixture policy rejection")

    runner = FakeRunner()
    adapter = CodexAdapter(
        executable="fixture-codex.exe", runner=runner, budget=DenyingFakeBudget(),
    )
    with pytest.raises(PaidAPIForbidden):
        asyncio.run(adapter.run(ai_task))
    assert not runner.calls
