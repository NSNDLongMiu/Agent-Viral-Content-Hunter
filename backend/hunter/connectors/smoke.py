"""Run a one-shot live check from a shell with network access."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from hunter.interfaces import ConnectorError, FetchLimits

from .registry import available_connectors
from .youtube_channel import YouTubeChannelConnector


def main(argv: Sequence[str] | None = None) -> int:
    factories = available_connectors()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connector", choices=tuple(factories))
    parser.add_argument("--channel-id", help="Public YouTube channel ID (required for youtube_channel)")
    args = parser.parse_args(argv)

    factory = factories[args.connector]
    if args.connector == YouTubeChannelConnector.id:
        if args.channel_id is None:
            parser.error("youtube_channel requires --channel-id.")
        try:
            connector = factory(channel_id=args.channel_id)
        except ValueError:
            parser.error("A valid YouTube channel ID is required.")
    else:
        if args.channel_id is not None:
            parser.error("--channel-id applies to youtube_channel only.")
        connector = factory()

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
