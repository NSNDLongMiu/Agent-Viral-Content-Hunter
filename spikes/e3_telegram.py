"""Send one real Telegram smoke test when both credential variables exist."""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common import OUT, Result, save, standalone


DESIGN = ("Durably reserve one test key per bot/chat before sending. Keep ambiguous sends pending "
          "for manual review. Telegram sendMessage has no client idempotency key, so a crash "
          "between reservation and confirmation can leave the test undelivered without a retry.")
SETUP = ("Use @BotFather `/newbot` to create a dedicated test bot. Open the chat, press Start "
         "and send a message. Make a private Bot API `getUpdates` call and read "
         "`result[].message.chat.id` (or `channel_post.chat.id` for a test channel). Use a client "
         "that keeps the token URL out of logs and history. Supply both values only through "
         "`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. [Telegram Bot API](https://core.telegram.org/bots/api)")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class BotError(Exception):
    def __init__(self, message, blocked=True):
        super().__init__(message)
        self.blocked = blocked


def call(method, token, evidence, **fields):
    evidence.append({"method": method, "http_status": None})
    entry = evidence[-1]
    request = Request(f"https://api.telegram.org/bot{token}/{method}",
                      data=urlencode(fields).encode("ascii"), method="POST",
                      headers={"User-Agent": "ViralContentHunterSpike/0.1"})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        try:
            response = opener.open(request, timeout=8)
        except HTTPError as exc:
            response = exc
        with response:
            entry["http_status"] = response.code
            header = response.headers.get("Retry-After", "")
            if re.fullmatch(r"[0-9A-Za-z., :+-]{1,70}", header):
                entry["retry_after_header"] = header
            if 300 <= response.code < 400:
                raise BotError(f"{method} returned a redirect. Request stopped.")
            if header and response.code == 200:
                raise BotError(f"{method} requested backoff. Probe stopped.")
            data = json.loads(response.read(128 * 1024))
            if type(data.get("parameters", {}).get("retry_after")) is int:
                entry["retry_after_seconds"] = data["parameters"]["retry_after"]
            entry["ok"] = data.get("ok") is True
            if not entry["ok"]:
                code = data.get("error_code")
                if type(code) is int:
                    entry["api_error_code"] = code
                raise BotError(f"{method} rejected the request (HTTP {response.code}). No retry.")
            return data["result"]
    except (URLError, OSError, ValueError, AttributeError, KeyError) as exc:
        entry["error_type"] = type(exc).__name__
        # Exceptions and response text can contain the Bot API URL, token or chat information.
        raise BotError(f"{method} response unavailable ({type(exc).__name__}). No retry.") from None


def ledger(path):
    db = sqlite3.connect(path, timeout=5)
    db.execute("""CREATE TABLE IF NOT EXISTS sends (
                   send_key TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('pending','sent'))
                )""")
    return db


def reserve(db, key):
    with db:
        return db.execute("INSERT OR IGNORE INTO sends VALUES (?, 'pending')", (key,)).rowcount == 1


def confirm(db, key):
    with db:
        db.execute("UPDATE sends SET status='sent' WHERE send_key=?", (key,))


def check_idempotency():
    with TemporaryDirectory(dir=OUT, prefix="telegram-check-") as directory:
        path = os.path.join(directory, "check.sqlite")
        with closing(ledger(path)) as initial, closing(ledger(path)) as another:
            first = reserve(initial, "local-idempotency-check")
            pending_duplicate = reserve(another, "local-idempotency-check")
            confirm(initial, "local-idempotency-check")
        with closing(ledger(path)) as reopened:
            sent_duplicate = reserve(reopened, "local-idempotency-check")
    return {"first_reservation_accepted": first, "pending_duplicate_accepted": pending_duplicate,
            "sent_duplicate_accepted_after_reopen": sent_duplicate}


def smoke_test(token, chat, evidence):
    requests = evidence["requests"]
    bot = call("getMe", token, requests)
    if bot.get("is_bot") is not True or type(bot.get("id")) is not int:
        raise BotError("getMe returned no valid bot identity.", blocked=False)
    key = hashlib.sha256(f"t0-test:{bot['id']}:{chat}".encode()).hexdigest()
    with closing(ledger(OUT / "e3_send_ledger.sqlite")) as db:
        if not reserve(db, key):
            status = db.execute("SELECT status FROM sends WHERE send_key=?", (key,)).fetchone()[0]
            evidence["existing_reservation"] = status
            if status == "sent":
                return "Existing API-confirmed send in ledger. This run confirmed the bot and suppressed a duplicate."
            raise BotError("Pending test reservation already exists. Resolve it before resending.")
        message = call("sendMessage", token, requests, chat_id=chat,
                       text="Viral Content Hunter feasibility spike test.")
        target = message.get("chat", {})
        matched = str(target.get("id")) == chat
        evidence["send_receipt_matches_chat"] = matched and type(message.get("message_id")) is int
        if not evidence["send_receipt_matches_chat"]:
            raise BotError("Telegram receipt lacked a message ID for the configured chat.", blocked=False)
        confirm(db, key)
    confirmed_bot = call("getMe", token, requests)
    evidence["same_bot_after_send"] = confirmed_bot.get("id") == bot["id"]
    if not evidence["same_bot_after_send"]:
        raise BotError("getMe returned a different bot identity after the send.", blocked=False)
    return "sendMessage returned a receipt for the configured chat and getMe confirmed the same bot."


def run():
    OUT.mkdir(exist_ok=True)
    checks = check_idempotency()
    evidence = {"local_idempotency": checks, "requests": []}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not checks["first_reservation_accepted"] or checks["pending_duplicate_accepted"] or checks["sent_duplicate_accepted_after_reopen"]:
        verdict, note = "FAIL", "Local idempotency check failed. No send attempted."
    elif not token or not chat:
        verdict, note = "BLOCKED", "Needs user credentials. No Bot API requests were made."
    elif not re.fullmatch(r"\d{5,16}:[A-Za-z0-9_-]{24,}", token) or not re.fullmatch(r"-?\d{1,20}", chat, re.ASCII):
        verdict, note = "BLOCKED", "Credential variables have an unexpected format. Use the numeric chat ID."
    else:
        try:
            note = smoke_test(token, str(int(chat)), evidence)
            verdict = "PASS"
        except BotError as exc:
            verdict, note = ("BLOCKED" if exc.blocked else "FAIL"), str(exc)
        except (sqlite3.Error, TypeError, AttributeError) as exc:
            verdict, note = "FAIL", f"Telegram check interrupted ({type(exc).__name__})."
    evidence.update(verdict=verdict, note=note)
    save("e3_telegram.json", evidence)
    local = ("Local SQLite check suppressed pending and sent duplicates." if checks == {
             "first_reservation_accepted": True, "pending_duplicate_accepted": False,
             "sent_duplicate_accepted_after_reopen": False} else "Local SQLite check failed.")
    return [Result("E3 Telegram", verdict, f"{note} {local} [Evidence](out/e3_telegram.json).",
                   DESIGN + " An API receipt does not establish that a recipient read the message.",
                   "Verify with a dedicated test bot before enabling Telegram alerts.")]


if __name__ == "__main__":
    standalone(run)
