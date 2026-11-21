import re
from collections.abc import Callable
from datetime import datetime
from math import isfinite
from urllib.parse import urlencode
from xml.etree.ElementTree import Element

from pydantic import JsonValue

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import MetricSnapshot, RawItem
from hunter.models.common import utcnow

from ._base import FetchBatch, PublicConnector, parse_feed
from .http import Transport, urllib_transport

FEED_URL = "https://www.youtube.com/xml/feeds/videos.xml"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def _count(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError
    return int(value)


class YouTubeChannelConnector(PublicConnector):
    id = "youtube_channel"
    capabilities = (ConnectorCapability.TARGETED_MONITORING,)

    def __init__(
        self, channel_id: str, *, source_id: str | None = None, transport: Transport = urllib_transport,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        channel_id = channel_id.strip()
        if not _CHANNEL_ID.fullmatch(channel_id):
            raise ValueError("A valid YouTube channel ID is required.")
        super().__init__(source_id=source_id, transport=transport, clock=clock)
        self._feed_url = f"{FEED_URL}?{urlencode({'channel_id': channel_id})}"

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        root = parse_feed(await self._get(self._feed_url, limits))
        if root.tag != f"{{{_NS['atom']}}}feed":
            raise ConnectorError("YouTube returned an invalid Atom feed.")

        for entry in root.findall("atom:entry", _NS):
            batch.add(lambda: self._parse_video(entry))
            if len(batch.items) == limits.max_items:
                break

    def _parse_video(self, entry: Element) -> RawItem:
        video_id = entry.findtext("yt:videoId", namespaces=_NS)
        if not video_id:
            atom_id = entry.findtext("atom:id", default="", namespaces=_NS)
            video_id = atom_id.removeprefix("yt:video:") if atom_id.startswith("yt:video:") else ""
        title = entry.findtext("atom:title", namespaces=_NS)
        if not _VIDEO_ID.fullmatch(video_id) or not title:
            raise ValueError

        published = entry.findtext("atom:published", namespaces=_NS)
        published_at = datetime.fromisoformat(published.strip()) if published else None
        community = entry.find("media:group/media:community", _NS)
        metrics = None
        metadata: dict[str, JsonValue] = {}
        if community is not None:
            stats = community.find("media:statistics", _NS)
            if stats is not None and (views := stats.get("views")) is not None:
                metrics = MetricSnapshot(views=_count(views))
            rating_node = community.find("media:starRating", _NS)
            if rating_node is not None:
                rating: dict[str, JsonValue] = {
                    name: _count(value) for name, value in rating_node.attrib.items()
                    if name in {"count", "min", "max"}
                }
                if (average := rating_node.get("average")) is not None:
                    number = float(average)
                    if not isfinite(number) or number < 0:
                        raise ValueError
                    rating["average"] = number
                if rating:
                    metadata["star_rating"] = rating

        fetched_at = self._now()
        return RawItem(
            source_id=self._source_id, source_url=f"https://www.youtube.com/watch?v={video_id}",
            external_id=video_id, title=title, creator=entry.findtext("atom:author/atom:name", namespaces=_NS),
            published_at=published_at, fetched_at=fetched_at, metrics=metrics,
            metrics_snapshot_at=fetched_at if metrics else None, metadata=metadata,
        )
