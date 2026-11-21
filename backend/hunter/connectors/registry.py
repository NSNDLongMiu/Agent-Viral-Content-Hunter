from collections.abc import Callable

from hunter.models import SourceInput

from ._base import PublicConnector
from .google_trends_vn import RSS_URL, GoogleTrendsVNConnector
from .hacker_news import TOP_STORIES_URL, HackerNewsConnector
from .wikimedia_top import WikimediaTopConnector

type ConnectorFactory = Callable[..., PublicConnector]


def available_connectors() -> dict[str, ConnectorFactory]:
    """Factories accept the saved source ID as source_id."""
    return {
        HackerNewsConnector.id: HackerNewsConnector,
        GoogleTrendsVNConnector.id: GoogleTrendsVNConnector,
        WikimediaTopConnector.id: WikimediaTopConnector,
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
    ]
