"""Explicitly register public sources in the configured local database."""

import argparse
import sqlite3
from collections.abc import Sequence

from hunter.config import SettingsError, load_settings
from hunter.connectors.registry import default_sources
from hunter.db import Database
from hunter.services.operations import OperationsService
from hunter.state import Conflict


def seed_sources(operations: OperationsService) -> int:
    existing = {(source.connector_id, source.url) for source in operations.list_sources(limit=-1)}
    created = 0
    for source in default_sources():
        key = (source.connector_id, source.url)
        if key in existing:
            continue
        try:
            operations.save_source(source, reason="Register default public collection source")
        except Conflict:
            # A concurrent seed or admin can win the insert. Propagate other conflicts.
            if not any((item.connector_id, item.url) == key for item in operations.list_sources(limit=-1)):
                raise
        else:
            created += 1
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hunter.runtime")
    parser.add_argument("command", choices=["seed-sources"])
    parser.parse_args(argv)
    try:
        database = Database(load_settings().database_path)
        database.migrate()
        count = seed_sources(OperationsService(database))
    except (SettingsError, OSError, sqlite3.Error, Conflict):
        print("Could not register default sources in the local database.")
        return 1
    print(f"Default sources added: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
