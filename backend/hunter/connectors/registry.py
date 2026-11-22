from collections.abc import Callable

from hunter.models import SourceInput

from ._base import PublicConnector
from .google_trends_vn import RSS_URL, GoogleTrendsVNConnector
from .hacker_news import TOP_STORIES_URL, HackerNewsConnector
from .hn_search import SEARCH_URL, HackerNewsSearchConnector
from .vn_entertainment_rss import VNEXPRESS_RSS_URL, VnEntertainmentRSSConnector
from .wikimedia_top import WikimediaTopConnector

type ConnectorFactory = Callable[..., PublicConnector]


def available_connectors() -> dict[str, ConnectorFactory]:
    """Factories accept the saved source ID as source_id."""
    return {
        HackerNewsConnector.id: HackerNewsConnector,
        GoogleTrendsVNConnector.id: GoogleTrendsVNConnector,
        WikimediaTopConnector.id: WikimediaTopConnector,
        VnEntertainmentRSSConnector.id: VnEntertainmentRSSConnector,
        HackerNewsSearchConnector.id: HackerNewsSearchConnector,
    }


def default_sources() -> list[SourceInput]:
    return [
        SourceInput(
            connector_id=HackerNewsConnector.id, name="Hacker News", platform="hacker_news", url=TOP_STORIES_URL,
        ),
        SourceInput(
            connector_id=GoogleTrendsVNConnector.id, name="Google Trends Vietnam", platform="google_trends",
            url=RSS_URL,
        ),
        SourceInput(
            connector_id=WikimediaTopConnector.id, name="Wikipedia (English)", platform="wikipedia",
            url="https://en.wikipedia.org/",
        ),
        SourceInput(
            connector_id=VnEntertainmentRSSConnector.id,
            name="Báo giải trí Việt Nam (VnExpress, Tuổi Trẻ, Thanh Niên)",
            platform="vn_news", url=VNEXPRESS_RSS_URL,
        ),
        SourceInput(
            connector_id=HackerNewsSearchConnector.id, name="Hacker News — phim ngắn, micro-drama, AI video",
            platform="hacker_news", url=SEARCH_URL,
        ),
    ]
