"""Check official AI CLI help/auth locally and gate model prompts on included usage."""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from common import OUT, Result, child_env, save, standalone


PROMPT = "Return only a JSON object with boolean ok set to true. Use no tools."
BILLING_CONFIRMATION = "T0_SPIKE_INCLUDED_USAGE_ONLY"
CLAUDE_FLAGS = ["--print", "--output-format", "--no-session-persistence", "--strict-mcp-config",
                "--restricted", "--setting-sources", "--tools"]
CODEX_FLAGS = ["--json", "--output-schema", "--sandbox", "--ephemeral",
               "--ignore-user-config", "--skip-git-repo-check", "--config"]
DIAGNOSTICS = {
    "quota": r"\b(?:usage limit (?:reached|exceeded)|quota (?:exceeded|exhausted)|"
             r"rate limit(?:ed| exceeded| reached)?|too many requests|hit your (?:usage )?limit|429)\b",
    "auth": r"\b(?:not logged in|unauthorized|authentication (?:required|failed)|"
            r"invalid api key|please run /login|401)\b",
    "permissions": r"\b(?:permission denied|access denied|access is denied|os error 5|EACCES)\b",
    "environment": r"\bcould not find home directory\b",
    "transport": r"\b(?:unable to connect|connection refused|network is unreachable|"
                 r"failed to connect|error sending request|stream disconnected)\b",
}


def cli_env(directory):
    # Read only known OS/runtime variable values. Provider keys, overrides, cloud auth,
    # host session credentials, proxy variables and dotenv settings are not inherited.
    env = child_env("CLAUDE_CODE_GIT_BASH_PATH", "CODEX_HOME", "CODEX_SANDBOX_NETWORK_DISABLED")
    env.update(TEMP=str(directory), TMP=str(directory), TMPDIR=str(directory),
               DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1",
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", GIT_CEILING_DIRECTORIES=str(OUT))
    return env


def executable(name):
    found = shutil.which(name)
    if not found:
        return None
    path = Path(found)
    # Use the npm package's native binary when present so the deadline terminates the CLI itself.
    if os.name == "nt" and path.suffix.lower() == ".cmd":
        arch = {"amd64": "x64", "arm64": "arm64"}.get(platform.machine().lower())
        if arch and name == "claude":
            base = path.parent / "node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai"
            native = base / f"claude-code-win32-{arch}/claude.exe"
            if native.is_file():
                return str(native)
        if arch and name == "codex":
            base = path.parent / "node_modules/@openai/codex/node_modules/@openai"
            target = "x86_64" if arch == "x64" else "aarch64"
            native = base / f"codex-win32-{arch}/vendor/{target}-pc-windows-msvc/bin/codex.exe"
            if native.is_file():
                return str(native)
    return str(path)


def call(args, directory, timeout=10):
    try:
        completed = subprocess.run(args, cwd=directory, env=cli_env(directory), stdin=subprocess.DEVNULL,
                                   capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"exit": None, "timeout_seconds": timeout}, "", ""
    except OSError as exc:
        return {"exit": None, "launch_error": type(exc).__name__, "os_error": exc.errno}, "", ""
    status = {"exit": completed.returncode}
    for channel, body in (("stderr", completed.stderr), ("stdout", completed.stdout)):
        matches = {kind: match.group(0) for kind, regex in DIAGNOSTICS.items()
                   if (match := re.search(regex, body, re.I))}
        if matches:
            status[channel + "_patterns"] = matches
    # Raw output can contain account information, credential errors, or session identifiers.
    return status, completed.stdout, completed.stderr


def parse_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def verified_object(value):
    return isinstance(value, dict) and value.keys() == {"ok"} and value["ok"] is True


def claude_auth(stdout, stderr):
    data = parse_json(stdout)
    if not isinstance(data, dict):
        return {"subscription": False, "mode": "status could not be parsed"}
    method = data.get("authMethod")
    provider = data.get("apiProvider")
    plan = data.get("subscriptionType")
    allowed_plans = {"pro", "max", "ultra", "team", "enterprise"}
    subscription = (data.get("loggedIn") is True and provider == "firstParty" and
                    method in ("claude.ai", "claudeai", "oauth") and plan in allowed_plans)
    return {"subscription": subscription,
            "mode": "Claude subscription" if subscription else "unverified subscription",
            "logged_in": data.get("loggedIn") is True,
            "provider": "firstParty" if provider == "firstParty" else "other/unavailable",
            "subscription_tier": plan if plan in allowed_plans else None,
            "auth_method": method if method in ("claude.ai", "claudeai", "oauth", "console", "api_key", "none") else "other/unavailable"}


def codex_auth(stdout, stderr):
    output = (stdout + "\n" + stderr).splitlines()
    for line in output:
        if line.strip().casefold() == "logged in using chatgpt":
            return {"subscription": True, "mode": "ChatGPT login (plan unverified)"}
        if line.strip().casefold() == "not logged in":
            return {"subscription": False, "mode": "Not logged in"}
    return {"subscription": False, "mode": "ChatGPT login could not be verified"}


def claude_prompt(path, directory):
    args = [path, "--print", "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--restricted", "--setting-sources", "", "--tools", "", "--", PROMPT]
    status, stdout, _ = call(args, directory, timeout=35)
    envelope = parse_json(stdout)
    if isinstance(envelope, dict):
        status["parsed_json_envelope"] = envelope.get("type") == "result"
        status["validated_payload"] = (status["parsed_json_envelope"] and envelope.get("is_error") is False
                                       and verified_object(parse_json(envelope.get("result"))))
    return status


def codex_prompt(path, directory):
    schema = directory / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"ok": {"type": "boolean"}},
                                  "required": ["ok"], "additionalProperties": False}), encoding="utf-8")
    args = [path, "exec", "--json", "--output-schema", str(schema),
            "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
            "-c", "model_provider=openai", "-c", "forced_login_method=chatgpt", "-c", "approval_policy=never",
            "-c", "web_search=disabled", "-c", "mcp_servers={}", "--", PROMPT]
    status, stdout, _ = call(args, directory, timeout=35)
    events = [parse_json(line) for line in stdout.splitlines() if line.strip()]
    status["parsed_jsonl"] = bool(events) and all(isinstance(event, dict) for event in events)
    if status["parsed_jsonl"]:
        status["turn_completed"] = any(event.get("type") == "turn.completed" for event in events)
        messages = [event["item"].get("text") for event in events if event.get("type") == "item.completed"
                    and isinstance(event.get("item"), dict) and event["item"].get("type") == "agent_message"]
        status["validated_payload"] = (status["turn_completed"] and bool(messages)
                                       and verified_object(parse_json(messages[-1])))
    return status


def version_line(body):
    for line in body.splitlines():
        if re.fullmatch(r"(?:codex-cli )?\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.]+)?(?: \(Claude Code\))?", line.strip()):
            return line.strip()
    return "unverified version"


def probe(name, directory, confirmation):
    path = executable(name)
    evidence = {"installed_on_path": bool(path), "model_attempted": False}
    if not path:
        return "BLOCKED", "Executable absent from PATH.", evidence
    evidence["version_probe"], stdout, _ = call([path, "--version"], directory)
    version = evidence["version"] = version_line(stdout)
    if name == "gemini":
        evidence["help_probe"], help_text, _ = call([path, "--help"], directory)
        evidence["help_flags_found"] = [flag for flag in ("--prompt", "--output-format") if flag in help_text]
        return "BLOCKED", f"{version}. Existing subscription auth for headless execution is unverified.", evidence

    if name == "claude":
        help_args, auth_args, flags = ["--help"], ["auth", "status", "--json"], CLAUDE_FLAGS
        auth_reader, prompt_runner = claude_auth, claude_prompt
    else:
        help_args, auth_args, flags = ["exec", "--help"], ["login", "status"], CODEX_FLAGS
        auth_reader, prompt_runner = codex_auth, codex_prompt
    evidence["help_probe"], help_text, _ = call([path, *help_args], directory)
    missing = evidence["help_flags_missing"] = [flag for flag in flags if flag not in help_text]
    evidence["help_flags_found"] = [flag for flag in flags if flag not in missing]
    evidence["auth_probe"], stdout, stderr = call([path, *auth_args], directory)
    auth = evidence["auth"] = auth_reader(stdout, stderr)
    status = evidence["auth_probe"]
    diagnostic = ", ".join(f"{channel} matched '{match}'" for channel in ("stderr", "stdout")
                            for match in status.get(channel + "_patterns", {}).values())
    prefix = f"{version}. Auth status exit {status['exit']}: {auth['mode']}."
    if diagnostic:
        prefix += f" {diagnostic}."
    if missing:
        return "BLOCKED", f"{prefix} Required help flags missing: {', '.join(missing)}.", evidence
    if status["exit"] != 0 or not auth["subscription"]:
        return "BLOCKED", f"{prefix} Subscription login is required for the model probe.", evidence
    if name not in confirmation:
        return "BLOCKED", f"{prefix} Included-only billing could not be confirmed. No model prompt was sent.", evidence
    if os.name == "nt" and Path(path).suffix.lower() in {".cmd", ".bat"}:
        return "BLOCKED", f"{prefix} A direct executable is required for a bounded model probe.", evidence

    evidence["model_attempted"] = True
    result = evidence["model_probe"] = prompt_runner(path, directory)
    if result["exit"] == 0 and result.get("validated_payload"):
        return "PASS", f"{prefix} Model exit 0 returned the expected JSON object.", evidence
    patterns = {**result.get("stdout_patterns", {}), **result.get("stderr_patterns", {})}
    if "quota" in patterns:
        return "BLOCKED", f"{prefix} BLOCKED (quota). Model exit {result['exit']} matched '{patterns['quota']}'.", evidence
    if patterns.keys() & {"auth", "transport", "permissions", "environment"}:
        return "BLOCKED", f"{prefix} Model exit {result['exit']} with {', '.join(patterns.values())}.", evidence
    if "timeout_seconds" in result:
        return "FAIL", f"{prefix} Model hit the {result['timeout_seconds']}-second launcher deadline.", evidence
    return "FAIL", f"{prefix} Model probe returned no validated JSON. Exit {result['exit']}.", evidence


DOCS = {
    "claude": ("Claude Code", "`claude -p … --output-format json` is advertised. Check `auth status --json` "
               "for login state. `--bare` in this version excludes OAuth. Subscription quota errors and "
               "generation auth-loss exits are unverified. [CLI reference](https://code.claude.com/docs/en/cli-reference), "
               "[Team usage credits](https://support.claude.com/en/articles/12005970-manage-usage-credits-for-team-and-seat-based-enterprise-plans)."),
    "codex": ("Codex", "`codex exec --json --output-schema … --output-last-message …` is advertised. "
              "Use `login status` to check the mode. Use `turn.failed` and the exit status when parsing errors. "
              "Quota and generation auth-loss exits are unverified. [Non-interactive docs](https://learn.chatgpt.com/docs/non-interactive-mode), "
              "[ChatGPT credit settings](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-plus-pro)."),
    "gemini": ("Gemini CLI", "Install with `npm install -g @google/gemini-cli` on a supported Node.js version, run "
               "`gemini`, and select Sign in with Google for the existing plan. Verify local `--help` first. "
               "Google documents `-p` and `--output-format json`, and lists API-key/Vertex auth for headless use. "
               "A cached subscription login in headless mode, quota and exit patterns remain unverified. "
               "[Install](https://geminicli.com/docs/get-started/installation/), "
               "[Sign-in](https://geminicli.com/docs/get-started/authentication/), "
               "[Headless](https://geminicli.com/docs/cli/headless/)."),
}


def run():
    OUT.mkdir(exist_ok=True)
    confirmation = {name.strip().lower() for name in os.environ.get(BILLING_CONFIRMATION, "").split(",")}
    rows = []
    with TemporaryDirectory(prefix="cli-", dir=OUT) as folder:
        directory = Path(folder)
        timeout, _, _ = call([sys.executable, "-I", "-c", "import time; time.sleep(2)"], directory, timeout=0.4)
        save("e1_timeout.json", {"local_subprocess_only": True, **timeout})
        for name, (label, docs) in DOCS.items():
            verdict, note, evidence = probe(name, directory, confirmation)
            filename = f"e1_{name}.json"
            save(filename, {"verdict": verdict, **evidence})
            recommendation = ("Prototype the adapter against the verified subscription CLI." if verdict == "PASS"
                              else "Keep disabled until an included-only end-to-end run passes.")
            rows.append(Result(f"E1 {label}", verdict, f"{note} [Evidence](out/{filename}).",
                               docs, recommendation))
    return rows


if __name__ == "__main__":
    standalone(run)
