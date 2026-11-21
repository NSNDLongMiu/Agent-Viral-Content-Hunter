from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree.ElementTree import Element

from pydantic import JsonValue

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import RawItem

from ._base import FetchBatch, PublicConnector, parse_feed, public_link

RSS_URL = "https://trends.google.com/trending/rss?geo=VN"
_EXPLORE_URL = "https://trends.google.com/trends/explore"


def _local_name(node: Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _fields(node: Element) -> dict[str, str]:
    return {_local_name(child): child.text.strip() for child in node if child.text and child.text.strip()}


class GoogleTrendsVNConnector(PublicConnector):
    id = "google_trends_vn"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY,)

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        root = parse_feed(await self._get(RSS_URL, limits))
        channel = root.find("channel")
        if root.tag != "rss" or channel is None:
            raise ConnectorError("Google Trends returned an invalid RSS channel.")

        for node in channel.findall("item"):
            batch.add(lambda: self._parse_query(node))
            if len(batch.items) == limits.max_items:
                break

    def _parse_query(self, node: Element) -> RawItem:
        fields = _fields(node)
        title = fields.get("title")
        if not title:
            raise ValueError
        date_label = fields.get("pubDate")
        published_at = parsedate_to_datetime(date_label) if date_label else None
        if date_label and published_at is not None and published_at.tzinfo is None:
            if "-0000" in date_label.split():
                published_at = published_at.replace(tzinfo=UTC)

        news: list[JsonValue] = []
        first_link: str | None = None
        for child in node:
            if _local_name(child) != "news_item":
                continue
            entry = {
                name.removeprefix("news_item_"): value
                for name, value in _fields(child).items()
                if name in {"news_item_title", "news_item_url", "news_item_source", "news_item_snippet"}
            }
            link = entry.pop("url", None)
            if first_link is None and link:
                first_link = link
            url = public_link(link)
            if url:
                entry["url"] = url
            picture = public_link(child.findtext("{*}news_item_picture"))
            if picture:
                entry["picture"] = picture
            if entry:
                news.append(entry)

        metadata: dict[str, JsonValue] = {"news": news}
        if "approx_traffic" in fields:
            metadata["search_traffic_label"] = fields["approx_traffic"]
        source_url = public_link(first_link) or f"{_EXPLORE_URL}?{urlencode({'geo': 'VN', 'q': title})}"
        return RawItem(
            source_id=self._source_id, source_url=source_url, external_id=title, title=title,
            published_at=published_at, fetched_at=self._now(), metadata=metadata,
        )
