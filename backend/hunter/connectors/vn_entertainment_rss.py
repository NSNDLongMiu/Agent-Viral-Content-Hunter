import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from itertools import zip_longest
from xml.etree.ElementTree import Element

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import RawItem

from ._base import FetchBatch, PublicConnector, parse_feed, public_link

VNEXPRESS_RSS_URL = "https://vnexpress.net/rss/giai-tri.rss"
_FEEDS = (
    ("VnExpress", VNEXPRESS_RSS_URL),
    ("Tuổi Trẻ", "https://tuoitre.vn/rss/giai-tri.rss"),
    ("Thanh Niên", "https://thanhnien.vn/rss/giai-tri.rss"),
)
_VIETNAM_TIME = timezone(timedelta(hours=7))
# Feed descriptions can be truncated in the middle of a tag.
_HTML_MARKUP = re.compile(
    r"""<!--.*?(?:-->|$)|</?[a-z](?:[^<>"']|"[^"]*"|'[^']*')*>|</?[a-z][^<>]*$|</?$""",
    re.IGNORECASE | re.DOTALL,
)


def _parse_date(label: str, publisher: str) -> datetime:
    try:
        return parsedate_to_datetime(label)
    except ValueError:
        if publisher != "Tuổi Trẻ":
            raise
    # This feed uses local AM/PM item dates and declares GMT+7 in its channel date.
    local_date = datetime.strptime(" ".join(label.split()), "%m/%d/%Y %I:%M:%S %p")
    return local_date.replace(tzinfo=_VIETNAM_TIME)


class VnEntertainmentRSSConnector(PublicConnector):
    id = "vn_entertainment_rss"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY,)

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        feeds: list[list[tuple[str, Element]]] = []
        failures: list[ConnectorError] = []
        for publisher, url in _FEEDS:
            try:
                root = parse_feed(await self._get(url, limits))
                channel = root.find("channel")
                if root.tag != "rss" or channel is None:
                    raise ConnectorError(f"{publisher} returned an invalid RSS channel.")
            except ConnectorError as error:
                failures.append(error)
                batch.dropped_items += 1
                continue
            feeds.append([(publisher, node) for node in channel.findall("item")])

        if not feeds:
            raise failures[-1]

        for row in zip_longest(*feeds):
            for entry in row:
                if entry is not None:
                    publisher, node = entry
                    batch.add(lambda: self._parse_item(publisher, node))
                    if len(batch.items) == limits.max_items:
                        return

    def _parse_item(self, publisher: str, node: Element) -> RawItem:
        title = unescape(node.findtext("title", "")).strip()
        link = node.findtext("link", "").strip()
        source_url = public_link(link)
        if not title or source_url is None or not source_url.startswith("https://"):
            raise ValueError

        guid = node.findtext("guid", "").strip()
        date_label = node.findtext("pubDate", "").strip()
        published_at = _parse_date(date_label, publisher) if date_label else None
        description = unescape(_HTML_MARKUP.sub(" ", node.findtext("description", "")))
        return RawItem(
            source_id=self._source_id, source_url=source_url, external_id=guid or link,
            title=title, published_at=published_at, fetched_at=self._now(),
            metadata={
                "language": "vi",
                "category": "giải trí",
                "publisher": publisher,
                "description": " ".join(description.split())[:300].rstrip(),
            },
        )
