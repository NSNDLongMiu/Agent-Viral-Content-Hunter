"""Exercise live public collection and ingest in a temporary SQLite database."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from hunter.connectors.registry import available_connectors, default_sources
from hunter.db import Database
from hunter.interfaces import ConnectorError, FetchLimits
from hunter.models import ConnectorState
from hunter.services.operations import OperationsService

from .cluster import ClusterService
from .service import Ingestor, collect


def main(argv: Sequence[str] | None = None) -> int:
    factories = available_connectors()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connector", nargs="?", choices=tuple(factories), help="Defaults to all discovery sources")
    args = parser.parse_args(argv)

    with TemporaryDirectory() as directory:
        database = Database(Path(directory) / "ingest-smoke.sqlite3")
        database.migrate()
        operations = OperationsService(database)
        ingestor = Ingestor(database)
        clusters = ClusterService(database)
        limits = FetchLimits(max_items=10, timeout_seconds=10)
        failed = False
        item_ids: list[str] = []
        for data in default_sources():
            if args.connector is not None and args.connector != data.connector_id:
                continue
            source = operations.save_source(data, reason="Temporary ingest smoke test")
            connector = factories[source.connector_id](source_id=source.id)
            try:
                result = asyncio.run(collect(connector, source, ingestor, operations, since=None, limits=limits))
            except ConnectorError as error:
                print(f"{source.connector_id}: {error}", file=sys.stderr)
                failed = True
                continue

            item_ids.extend(result.new_item_ids)
            round_trip = [ingestor.get_item(item_id) for item_id in result.new_item_ids]
            replay = ingestor.ingest(source, round_trip)
            health = next(record.status for record in operations.connector_health() if record.connector_id == connector.id)
            print(json.dumps({
                "connector": source.connector_id, "health": health, "new_items": len(round_trip),
                "duplicates": result.duplicate_count, "rejected": result.rejected_count,
                "replay_duplicates": replay.duplicate_count,
            }))
            failed |= (
                health != ConnectorState.AVAILABLE or not (round_trip or result.duplicate_count)
                or result.rejected_count > 0 or replay.duplicate_count != len(round_trip)
            )
        cluster_ids = {clusters.assign(item_id) for item_id in item_ids}
        cluster_ids.discard(None)
        print(json.dumps({"stored_items": len(item_ids), "clusters": len(cluster_ids)}))
        return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
