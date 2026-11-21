"""Durable Telegram receipts, explicit acknowledgements and the polling cursor."""

import sqlite3
from contextlib import closing, contextmanager
from collections.abc import Iterator
from pathlib import Path

from hunter.interfaces import SendResult, SendStatus


class Ledger:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    key_hash TEXT PRIMARY KEY,
                    callback_data TEXT UNIQUE,
                    state TEXT NOT NULL CHECK(state IN ('reserved', 'sent', 'failed', 'unknown')),
                    receipt TEXT UNIQUE,
                    CHECK ((state = 'sent') = (receipt IS NOT NULL))
                );
                CREATE TABLE IF NOT EXISTS acknowledgements (
                    receipt TEXT NOT NULL,
                    callback_data TEXT NOT NULL,
                    PRIMARY KEY (receipt, callback_data)
                );
                CREATE TABLE IF NOT EXISTS poll_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    next_offset INTEGER NOT NULL
                );
            """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path, timeout=5)) as db, db:
            yield db

    def reserve(self, key_hash: str, callback_data: str | None) -> bool:
        with self._transaction() as db:
            return db.execute(
                """INSERT INTO deliveries (key_hash, callback_data, state) VALUES (?, ?, 'reserved')
                   ON CONFLICT(key_hash) DO UPDATE SET state = 'reserved'
                   WHERE deliveries.state = 'failed'""",
                (key_hash, callback_data),
            ).rowcount == 1

    def finish(self, key_hash: str, result: SendResult) -> None:
        with self._transaction() as db:
            db.execute(
                "UPDATE deliveries SET state = ?, receipt = ? WHERE key_hash = ? AND state = 'reserved'",
                (result.status.lower(), result.external_id, key_hash),
            )

    def lookup(self, key_hash: str) -> SendResult:
        with self._transaction() as db:
            row = db.execute(
                "SELECT state, receipt, callback_data FROM deliveries WHERE key_hash = ?", (key_hash,),
            ).fetchone()
            if row is not None and row[0] == "unknown" and row[2] is not None:
                # A callback may have committed while the send was still reserved,
                # or before callback-based recovery was available.
                ack = db.execute(
                    """SELECT MIN(receipt) FROM acknowledgements WHERE callback_data = ?
                       HAVING COUNT(*) = 1""", (row[2],),
                ).fetchone()
                if ack is not None:
                    self._confirm_callback(db, ack[0], row[2])
                    row = db.execute(
                        "SELECT state, receipt FROM deliveries WHERE key_hash = ?", (key_hash,),
                    ).fetchone()
        if row is None or row[0] == "reserved":
            return SendResult(status=SendStatus.UNKNOWN)
        return SendResult(status=SendStatus(row[0].upper()), external_id=row[1])

    def acknowledged(self, key_hash: str, receipt: str) -> bool:
        with self._transaction() as db:
            return db.execute(
                """SELECT 1 FROM deliveries AS delivery
                   JOIN acknowledgements AS ack ON ack.receipt = delivery.receipt
                   WHERE delivery.key_hash = ? AND delivery.receipt = ?
                     AND ack.callback_data IN ('', delivery.callback_data)""",
                (key_hash, receipt),
            ).fetchone() is not None

    def offset(self) -> int:
        with self._transaction() as db:
            row = db.execute("SELECT next_offset FROM poll_state WHERE id = 1").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _confirm_callback(db: sqlite3.Connection, receipt: str, data: str) -> None:
        # The receipt is unique to one delivery in this chat. An existing
        # receipt is never replaced or attached to another handoff.
        db.execute(
            """UPDATE OR IGNORE deliveries SET state = 'sent', receipt = ?
               WHERE callback_data = ? AND state = 'unknown'""", (receipt, data),
        )

    def apply_updates(
        self, next_offset: int, replies: list[tuple[str, bool]], callbacks: list[tuple[str, str, str]],
    ) -> list[str]:
        """Commit the cursor with the evidence, including replies during receipt confirmation."""
        answers = []
        with self._transaction() as db:
            db.executemany(
                """INSERT OR IGNORE INTO acknowledgements (receipt, callback_data)
                   SELECT ?, '' WHERE ? OR EXISTS (SELECT 1 FROM deliveries WHERE receipt = ?)""",
                [(receipt, from_bot, receipt) for receipt, from_bot in replies],
            )
            for receipt, data, query_id in callbacks:
                self._confirm_callback(db, receipt, data)
                known = db.execute(
                    """SELECT 1 FROM deliveries WHERE callback_data = ?
                       AND (receipt = ? OR state = 'reserved')""",
                    (data, receipt),
                ).fetchone()
                if known:
                    db.execute("INSERT OR IGNORE INTO acknowledgements VALUES (?, ?)", (receipt, data))
                    answers.append(query_id)
            db.execute(
                """INSERT INTO poll_state VALUES (1, ?)
                   ON CONFLICT(id) DO UPDATE SET next_offset = MAX(next_offset, excluded.next_offset)""",
                (next_offset,),
            )
        return answers
