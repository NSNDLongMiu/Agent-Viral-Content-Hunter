import asyncio
import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest

from hunter.connectors import http, smoke
from hunter.connectors.google_trends_vn import RSS_URL, GoogleTrendsVNConnector
from hunter.connectors.hacker_news import API_BASE as HN_API
from hunter.connectors.hacker_news import TOP_STORIES_URL, HackerNewsConnector
from hunter.connectors.http import HttpConnectorError, HttpResponse
from hunter.connectors.registry import available_connectors, default_sources
from hunter.connectors.wikimedia_top import API_BASE as WIKI_API
from hunter.connectors.wikimedia_top import WikimediaTopConnector
from hunter.interfaces import ConnectorError, FetchLimits
from hunter.models import ConnectorState, MetricSnapshot

NOW = datetime(2026, 11, 22, 4, tzinfo=UTC)
FIXTURES = Path(__file__).with_name("fixtures") / "connectors"


@pytest.fixture(autouse=True)
def disallow_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_io(*args: object, **kwargs: object) -> None:
        pytest.fail("Only the fake transport may be used in connector tests")

    monkeypatch.setattr(http, "build_opener", unexpected_io)
    monkeypatch.setattr(socket, "create_connection", unexpected_io)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_io)


class FakeTransport:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float) -> HttpResponse:
        self.calls.append((url, timeout))
        return self.responses[url]


def json_fixture(data: object) -> HttpResponse:
    return HttpResponse(200, json.dumps(data).encode())


def hn_story_url(story_id: int) -> str:
    return f"{HN_API}item/{story_id}.json"


def hn_story_fixture(story_id: int, **fields: object) -> HttpResponse:
    return json_fixture({
        "id": story_id, "type": "story", "title": f"Fixture story {story_id}", "by": "fixture-user",
        "time": 1795267200, **fields,
    })


def test_hn_backfills_bad_records_and_preserves_the_metrics_meaning() -> None:
    fake = FakeTransport({
        TOP_STORIES_URL: json_fixture([1, 2, 2, 3, 4, 5]),
        hn_story_url(1): hn_story_fixture(1, title=" "),
        hn_story_url(2): hn_story_fixture(2, url="https://example.org/article", descendants=0, score=12),
        hn_story_url(3): json_fixture({"id": 3, "deleted": True}),
        hn_story_url(4): hn_story_fixture(4, score=5),
    })
    connector = HackerNewsConnector(source_id="saved-source", transport=fake, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(max_items=2, timeout_seconds=1.25)))

    assert [item.external_id for item in items] == ["2", "4"]
    assert sorted(url for url, _ in fake.calls) == sorted([TOP_STORIES_URL, *map(hn_story_url, range(1, 5))])
    assert all(timeout == 1.25 for _, timeout in fake.calls)
    first, second = items
    assert first.source_id == "saved-source"
    assert str(first.source_url) == "https://news.ycombinator.com/item?id=2"
    assert first.metadata == {"article_url": "https://example.org/article", "hn_score": 12}
    assert first.metrics == MetricSnapshot(comments=0)
    assert first.metrics_snapshot_at == first.fetched_at == NOW
    assert first.published_at == datetime.fromtimestamp(1795267200, UTC)
    assert second.metrics is None and second.metrics_snapshot_at is None
    assert connector.dropped_items == 1


def test_hn_fetches_four_in_parallel_and_never_requests_excess_items() -> None:
    ids = range(1, 7)
    fake = FakeTransport({TOP_STORIES_URL: json_fixture(list(ids)), **{
        hn_story_url(story_id): hn_story_fixture(story_id) for story_id in ids
    }})
    first_batch = {hn_story_url(story_id) for story_id in range(1, 5)}
    ready = Barrier(4)

    def fake_parallel_transport(url: str, timeout: float) -> HttpResponse:
        if url in first_batch:
            ready.wait(timeout=5)
        return fake(url, timeout)

    connector = HackerNewsConnector(transport=fake_parallel_transport)
    items = asyncio.run(connector.fetch(None, FetchLimits(max_items=5)))

    assert [item.external_id for item in items] == ["1", "2", "3", "4", "5"]
    assert {url for url, _ in fake.calls[1:5]} == first_batch
    assert fake.calls[-1][0] == hn_story_url(5)
    assert len(fake.calls) == 6


def test_hn_throttle_stops_further_requests() -> None:
    fake = FakeTransport({
        TOP_STORIES_URL: json_fixture(list(range(1, 8))),
        hn_story_url(1): HttpResponse(429, headers={"Retry-After": "15"}),
        **{hn_story_url(story_id): hn_story_fixture(story_id) for story_id in range(2, 5)},
    })
    connector = HackerNewsConnector(transport=fake)
    with pytest.raises(HttpConnectorError) as failure:
        asyncio.run(connector.fetch(None, FetchLimits(max_items=6)))
    assert failure.value.retry_after_seconds == 15
    assert len(fake.calls) == 5
    assert connector.health().status == ConnectorState.UNAVAILABLE


def test_trends_rss_preserves_traffic_label_and_news_and_falls_back() -> None:
    fake = FakeTransport({RSS_URL: HttpResponse(200, (FIXTURES / "google_trends_vn.xml").read_bytes())})
    connector = GoogleTrendsVNConnector(transport=fake, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(max_items=3, timeout_seconds=3)))

    assert fake.calls == [(RSS_URL, 3)]
    assert connector.dropped_items == 1
    assert [item.title for item in items] == ["Mưa sao băng", "Lễ hội"]
    first, second = items
    assert first.published_at == datetime(2026, 11, 21, 17, tzinfo=UTC)
    assert first.metadata == {
        "search_traffic_label": "2,000+",
        "news": [
            {"title": "Fixture sky watch", "source": "Fixture News", "url": "https://example.com/science?id=40"},
            {"title": "Fixture event listing", "url": "https://example.org/events/sky"},
        ],
    }
    assert str(first.source_url) == "https://example.com/science?id=40"
    assert first.metrics is None and first.metrics_snapshot_at is None
    assert second.published_at == datetime(2026, 11, 21, 16, tzinfo=UTC)
    assert second.metadata["news"] == []
    assert parse_qs(urlsplit(str(second.source_url)).query) == {"geo": ["VN"], "q": ["Lễ hội"]}


def test_wikimedia_uses_yesterday_then_falls_back_and_skips_non_articles() -> None:
    yesterday = WIKI_API + "2026/11/21"
    previous_day = WIKI_API + "2026/11/20"
    fake = FakeTransport({
        yesterday: HttpResponse(404),
        previous_day: json_fixture({"items": [{"articles": [
            {"article": "Main_Page", "rank": 1, "views": 100},
            {"article": "Special:Search", "rank": 2, "views": 99},
            {"article": "Wikipedia:Contents", "rank": 3, "views": 98},
            {"article": "-", "rank": 4, "views": 97},
            {"article": "Broken_fixture", "rank": 5, "views": -1},
            {"article": "Đà_Nẵng", "rank": 6, "views": 96},
            {"article": "Another_fixture", "rank": 7, "views": 95},
        ]}]}),
    })
    connector = WikimediaTopConnector(transport=fake, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(max_items=1)))

    assert fake.calls == [(yesterday, 30), (previous_day, 30)]
    assert len(items) == 1 and connector.dropped_items == 1
    first = items[0]
    assert str(first.source_url) == "https://en.wikipedia.org/wiki/%C4%90%C3%A0_N%E1%BA%B5ng"
    assert first.title == "Đà Nẵng" and first.published_at is None
    assert first.metadata == {"pageviews_date": "2026-11-20", "rank": 6}
    assert first.metrics == MetricSnapshot(views=96)
    assert first.metrics_snapshot_at == first.fetched_at == NOW


def test_wikimedia_stops_at_yesterday_when_data_is_available() -> None:
    fake = FakeTransport({WIKI_API + "2026/11/21": json_fixture({"items": [{"articles": [
        {"article": "Climate_change", "rank": 1, "views": 100},
    ]}]})})
    connector = WikimediaTopConnector(transport=fake, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits()))
    assert len(items) == len(fake.calls) == 1
    assert items[0].metadata["pageviews_date"] == "2026-11-21"


def test_wikimedia_does_not_fall_back_when_the_server_requests_backoff() -> None:
    fake = FakeTransport({WIKI_API + "2026/11/21": HttpResponse(404, headers={"Retry-After": "12"})})
    connector = WikimediaTopConnector(transport=fake, clock=lambda: NOW)
    with pytest.raises(HttpConnectorError) as failure:
        asyncio.run(connector.fetch(None, FetchLimits()))
    assert failure.value.retry_after_seconds == 12
    assert len(fake.calls) == 1


def test_health_starts_unavailable_tracks_success_and_degrades_on_failure() -> None:
    now = NOW
    fake = FakeTransport({RSS_URL: HttpResponse(403, b"private response body")})
    connector = GoogleTrendsVNConnector(transport=fake, clock=lambda: now)
    assert connector.health().status == ConnectorState.UNAVAILABLE
    assert connector.health().last_success_at is None

    with pytest.raises(ConnectorError, match=r"^HTTP 403 from public endpoint\.$"):
        asyncio.run(connector.fetch(None, FetchLimits()))
    assert connector.health().status == ConnectorState.UNAVAILABLE

    fake.responses[RSS_URL] = HttpResponse(200, b"<rss><channel /></rss>")
    assert asyncio.run(connector.fetch(None, FetchLimits())) == []
    assert connector.health().status == ConnectorState.AVAILABLE
    assert connector.health().last_success_at == NOW
    assert connector.health().last_error is None

    now += timedelta(minutes=1)
    fake.responses[RSS_URL] = HttpResponse(200, b"<html><title>private error</title></html>")
    with pytest.raises(ConnectorError, match=r"invalid RSS channel"):
        asyncio.run(connector.fetch(None, FetchLimits()))
    assert connector.health().status == ConnectorState.DEGRADED
    assert connector.health().checked_at == now
    assert connector.health().last_success_at == NOW
    assert connector.health().last_error == "Google Trends returned an invalid RSS channel."

    fake.responses[RSS_URL] = HttpResponse(200, b"<rss><channel><item /></channel></rss>")
    assert asyncio.run(connector.fetch(None, FetchLimits())) == []
    assert connector.dropped_items == 1
    assert connector.health().status == ConnectorState.DEGRADED
    assert connector.health().last_success_at == NOW


def test_feed_does_not_expand_xml_entities() -> None:
    fake = FakeTransport({RSS_URL: HttpResponse(200, b'<!DOCTYPE rss [<!ENTITY fixture "data">]><rss><channel /></rss>')})
    connector = GoogleTrendsVNConnector(transport=fake)
    with pytest.raises(ConnectorError, match=r"document type declaration"):
        asyncio.run(connector.fetch(None, FetchLimits()))


def test_registry_lists_factories_and_defaults_for_supported_sources() -> None:
    factories = available_connectors()
    assert set(factories) == {
        "hacker_news", "google_trends_vn", "wikimedia_top", "vn_entertainment_rss", "hn_search",
    }
    defaults = default_sources()
    assert [source.connector_id for source in defaults] == [
        "hacker_news", "google_trends_vn", "wikimedia_top", "vn_entertainment_rss", "hn_search",
    ]
    assert all(source.url.scheme == "https" for source in defaults)


def test_smoke_prints_counts_and_only_the_first_items_title_and_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTransport({
        TOP_STORIES_URL: json_fixture([1, 2]),
        hn_story_url(1): hn_story_fixture(1, descendants=3),
        hn_story_url(2): hn_story_fixture(2),
    })
    monkeypatch.setattr(smoke, "available_connectors", lambda: {
        "hacker_news": lambda: HackerNewsConnector(transport=fake),
    })
    assert smoke.main(["hacker_news"]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {
        "count": 2, "dropped_items": 0,
        "first": {"title": "Fixture story 1", "url": "https://news.ycombinator.com/item?id=1"},
    }
