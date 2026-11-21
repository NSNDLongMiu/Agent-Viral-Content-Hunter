"""SQLite connections and atomic, versioned schema upgrades."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

from hunter.models.common import utc_iso, utcnow

_SQLITE_TIMEOUT = 10


def _statements(script: str) -> Iterator[str]:
    start = 0
    for end, character in enumerate(script, start=1):
        if character == ";" and sqlite3.complete_statement(script[start:end]):
            yield script[start:end]
            start = end
    if script[start:].strip():
        yield script[start:]


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=_SQLITE_TIMEOUT, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _enable_wal(self) -> None:
        with self.connection() as connection:
            deadline = monotonic() + _SQLITE_TIMEOUT
            while True:
                try:
                    if connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                        return
                    mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                    if mode != "wal":
                        raise RuntimeError("SQLite WAL mode is required")
                    return
                except sqlite3.OperationalError as error:
                    # A journal mode change can report SQLITE_BUSY without waiting for
                    # the busy timeout when another process is opening a fresh file.
                    if error.sqlite_errorcode & 0xff not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        raise
                    if monotonic() >= deadline:
                        raise
                    sleep(0.025)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._enable_wal()
        migrations = sorted(Path(__file__).with_name("migrations").glob("*.sql"))
        versions = [int(path.name.split("_", 1)[0]) for path in migrations]
        if not versions or versions != list(range(1, len(versions) + 1)):
            raise RuntimeError("SQLite migrations must be present and consecutive")
        with self.transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                )"""
            )
            applied = [row[0] for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )]
            if applied != versions[:len(applied)]:
                raise RuntimeError("SQLite migration history is incompatible with this backend")
            for version, path in zip(versions[len(applied):], migrations[len(applied):], strict=True):
                # executescript() can commit the transaction. Execute complete statements
                # individually so a failed migration and its version record roll back together.
                for statement in _statements(path.read_text(encoding="utf-8")):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)", (version, utc_iso(utcnow()))
                )
