"""Run one schema-bound probe using an existing, included-only subscription."""

import argparse
import asyncio

from hunter.interfaces import AITask, AIStatus, AIWorker
from hunter.models import AIName

from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .gemini_adapter import GeminiAdapter
from .local_adapter import LocalAdapter


async def _probe(adapter: AIWorker) -> int:
    result = await adapter.run(AITask(
        id="hunter-smoke",
        instructions='Return the JSON object {"ok": true}.',
        input={},
        output_schema={
            "type": "object", "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"], "additionalProperties": False,
        },
    ))
    if result.status == AIStatus.OK:
        if result.output == {"ok": True}:
            print('OK {"ok":true}')
            return 0
        print("ERROR")
        return 1
    print(f"{result.status.value} {result.error or ''}".rstrip())
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", choices=[name.value for name in AIName])
    parser.add_argument(
        "--enable-claude", action="store_true",
        help="Confirm that paid Claude usage credits are disabled on the existing subscription.",
    )
    args = parser.parse_args()
    adapters: dict[str, AIWorker] = {
        "codex": CodexAdapter(), "gemini": GeminiAdapter(),
        "claude": ClaudeAdapter(enabled=args.enable_claude), "local": LocalAdapter(),
    }
    return asyncio.run(_probe(adapters[args.adapter]))


if __name__ == "__main__":
    raise SystemExit(main())
