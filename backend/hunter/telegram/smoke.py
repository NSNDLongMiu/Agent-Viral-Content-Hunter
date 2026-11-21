"""Run a live send or acknowledgment check with a dedicated test bot."""

import sqlite3
import sys

from hunter.interfaces import SendStatus

from .notifier import DEFAULT_LEDGER_PATH, TelegramError, TelegramNotifier

_SMOKE_KEY = "handoff:telegram-smoke-test-v1"


def main() -> int:
    args = sys.argv[1:]
    if args not in (["send-test"], ["poll"]):
        print("INVALID_COMMAND")
        return 2
    try:
        notifier = TelegramNotifier(ledger_path=DEFAULT_LEDGER_PATH.with_name("telegram-smoke.sqlite3"))
        if args == ["send-test"]:
            result = notifier.send("BÀN GIAO THỬ NGHIỆM\nNhấn nút xác nhận hoặc trả lời tin nhắn này.", _SMOKE_KEY)
        else:
            result = notifier.lookup_send(_SMOKE_KEY)
            if result.status == SendStatus.SENT and result.external_id is not None:
                notifier.poll_updates()
                acknowledged = notifier.check_ack(result.external_id, _SMOKE_KEY)
                print("ACKNOWLEDGED" if acknowledged else "PENDING")
                return 0 if acknowledged else 1
        if result.external_id is not None and len(result.external_id) > 2:
            print(f"{result.status} receipt=****{result.external_id[-2:]}")
        elif result.external_id is not None:
            print(f"{result.status} receipt=****")
        else:
            print(result.status)
        return 0 if result.status == SendStatus.SENT else 1
    except (TelegramError, sqlite3.Error, OSError, ValueError):
        print("UNAVAILABLE")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
