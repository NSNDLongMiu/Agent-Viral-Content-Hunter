"""Shared report and evidence helpers for the feasibility spike."""

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"

SECRET = re.compile(
    r"(?i)(?:\b(?:sk-(?:ant-|proj-|svcacct-)?[a-z0-9_-]{16,}|"
    r"gh[pousr]_[a-z0-9]{16,}|github_pat_[a-z0-9_]{16,}|AIza[a-z0-9_-]{25,})\b"
    r"|\b\d{6,16}:[a-z0-9_-]{24,}\b"
    r"|\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b"
    r"|\b(?:bearer\s+|(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password|cookie)"
    r"\s*[:=]\s*['\"]?)[^\s,;'\"<>]+)"
)

OS_ENV = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "USERPROFILE",
          "HOMEDRIVE", "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
          "PROGRAMFILES(X86)", "PROGRAMW6432", "OS", "PROCESSOR_ARCHITECTURE", "LANG"}


@dataclass
class Result:
    experiment: str
    verdict: str
    evidence: str
    limits: str
    recommendation: str


def redact(value):
    return SECRET.sub("[redacted]", value)


def child_env(*allowed):
    names = OS_ENV.union(allowed)
    return {key: os.environ[key] for key in os.environ if key.upper() in names}


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                            dir=path.parent, delete=False) as handle:
        pending = Path(handle.name)
        handle.write(value)
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def save(name, value):
    def scrub(item):
        if isinstance(item, str):
            return redact(item)
        if isinstance(item, dict):
            return {key: scrub(child) for key, child in item.items()}
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return item

    write_text(OUT / name, json.dumps(scrub(value), indent=2, ensure_ascii=False) + "\n")


def standalone(run):
    # Escape non-ASCII on stdout for Windows consoles with legacy code pages.
    print(redact(json.dumps([asdict(row) for row in run()], indent=2)))
