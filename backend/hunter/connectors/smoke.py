"""Run a one-shot live check from a shell with network access."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from hunter.interfaces import ConnectorError, FetchLimits

from .registry import available_connectors


def main(argv: Sequence[str] | None = None) -> int:
    factories = available_connectors()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connector", choices=tuple(factories))
    args = parser.parse_args(argv)

    connector = factories[args.connector]()

    try:
        items = asyncio.run(connector.fetch(None, FetchLimits(max_items=3, timeout_seconds=10)))
    except ConnectorError as error:
        print(error, file=sys.stderr)
        return 1
    first = {"title": items[0].title, "url": str(items[0].source_url)} if items else None
    print(json.dumps({"count": len(items), "dropped_items": connector.dropped_items, "first": first}))
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
