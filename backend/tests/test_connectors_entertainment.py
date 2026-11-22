import asyncio
import json
import socket
from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPSHandler, OpenerDirector, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

from hunter.connectors import http
from hunter.connectors.hacker_news import API_BASE, TOP_STORIES_URL, HackerNewsConnector
from hunter.connectors.hn_search import SEARCH_QUERIES, HackerNewsSearchConnector
from hunter.connectors.http import HttpConnectorError, HttpResponse
from hunter.connectors.registry import available_connectors, default_sources
from hunter.connectors.vn_entertainment_rss import VnEntertainmentRSSConnector
from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import ConnectorState, MetricSnapshot

NOW = datetime(2026, 11, 22, 4, tzinfo=UTC)
FIXTURES = Path(__file__).with_name("fixtures") / "connectors"
VNEXPRESS = "https://vnexpress.net/rss/giai-tri.rss"
TUOI_TRE = "https://tuoitre.vn/rss/giai-tri.rss"
THANH_NIEN = "https://thanhnien.vn/rss/giai-tri.rss"
SEARCH = "https://hn.algolia.com/api/v1/search"


@pytest.fixture(autouse=True)
def disallow_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_io(*args: object, **kwargs: object) -> None:
        pytest.fail("Only fake transports may be used in connector tests")

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


def rss_responses() -> dict[str, HttpResponse]:
    return {
        VNEXPRESS: HttpResponse(200, (FIXTURES / "vnexpress_giai_tri.xml").read_bytes()),
        TUOI_TRE: HttpResponse(200, (FIXTURES / "tuoitre_giai_tri.xml").read_bytes()),
        THANH_NIEN: HttpResponse(200, (FIXTURES / "thanhnien_giai_tri.xml").read_bytes()),
    }


def hn_hits() -> list[dict[str, object]]:
    return json.loads((FIXTURES / "hn_algolia_search.json").read_bytes())["hits"]


def json_response(data: object) -> HttpResponse:
    return HttpResponse(200, json.dumps(data).encode())


def query_url(query: str) -> str:
    cutoff = int((NOW - timedelta(days=7)).timestamp())
    params = urlencode({
        "query": query, "tags": "story", "numericFilters": f"created_at_i>{cutoff},points>=2", "hitsPerPage": 20,
    })
    return f"{SEARCH}?{params}"


def search_transport(overrides: dict[str, HttpResponse]) -> FakeTransport:
    empty = json_response({"hits": []})
    return FakeTransport({query_url(query): overrides.get(query, empty) for query in SEARCH_QUERIES})


def test_all_rss_fixtures_produce_clean_metadata_without_metrics() -> None:
    transport = FakeTransport(rss_responses())
    connector = VnEntertainmentRSSConnector(source_id="saved-news", transport=transport, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(timeout_seconds=2)))

    assert transport.calls == [(VNEXPRESS, 2), (TUOI_TRE, 2), (THANH_NIEN, 2)]
    assert len(items) == 9
    assert connector.dropped_items == 0
    first_by_publisher = {
        "VnExpress": (
            "'See The Light 2': Sức hút của Mỹ Tâm",
            datetime(2026, 11, 21, 22, 35, 23, tzinfo=UTC),
            "Mỹ Tâm đưa hàng chụ",
        ),
        "Tuổi Trẻ": (
            "Lại thêm mascot khán giả gọi là 'câu chống liệt' ở Ca sĩ mặt nạ",
            datetime(2026, 11, 22, 0, 11, tzinfo=UTC),
            "Tập mới Ca sĩ mặt nạ 2026",
        ),
        "Thanh Niên": (
            "Công nương Kate bật khóc trong bộ phim tài liệu kể về hành trình chữa ung thư",
            datetime(2026, 11, 22, 1, 43, tzinfo=UTC),
            "",
        ),
    }
    for item in items:
        assert item.source_id == "saved-news"
        assert item.source_url.scheme == "https"
        assert item.published_at is not None and item.published_at.tzinfo is UTC
        assert item.metrics is None and item.metrics_snapshot_at is None
        assert set(item.metadata) == {"language", "category", "publisher", "description"}
        assert item.metadata["language"] == "vi" and item.metadata["category"] == "giải trí"
        description = item.metadata["description"]
        assert isinstance(description, str) and len(description) <= 300
        assert "<" not in description and ">" not in description
    for item, (publisher, (title, published_at, description_start)) in zip(items[:3], first_by_publisher.items()):
        assert item.title == title and item.published_at == published_at
        assert item.metadata["publisher"] == publisher
        assert str(item.metadata["description"]).startswith(description_start)
        if publisher == "Thanh Niên":
            assert item.metadata["description"] == ""
        assert item.external_id == str(item.source_url)


def test_rss_decodes_entities_collapses_whitespace_and_caps_descriptions() -> None:
    description = '<a title="fixture > text"><img src="fixture"></a>   Tin &amp;  phim&nbsp; ' + "x" * 500
    transport = FakeTransport({
        **rss_responses(),
        VNEXPRESS: HttpResponse(200, f"""<rss><channel><item>
            <guid>fixture-guid</guid><title>Fixture story</title><link>https://vnexpress.net/fixture</link>
            <description><![CDATA[{description}]]></description>
        </item></channel></rss>""".encode()),
    })
    connector = VnEntertainmentRSSConnector(transport=transport, clock=lambda: NOW)
    item, = asyncio.run(connector.fetch(None, FetchLimits(max_items=1)))

    assert item.external_id == "fixture-guid"
    assert item.metadata["description"] == "Tin & phim " + "x" * 289


def test_one_failed_rss_feed_keeps_the_other_publishers() -> None:
    transport = FakeTransport({
        **rss_responses(),
        TUOI_TRE: HttpResponse(503, headers={"Retry-After": "10"}),
    })
    connector = VnEntertainmentRSSConnector(transport=transport, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits()))

    assert len(items) == 6
    assert {item.metadata["publisher"] for item in items} == {"VnExpress", "Thanh Niên"}
    assert connector.dropped_items == 1
    assert connector.health().last_success_at == NOW


def test_all_rss_feeds_failing_raises() -> None:
    transport = FakeTransport({
        VNEXPRESS: HttpResponse(503), TUOI_TRE: HttpResponse(200, b"<broken"), THANH_NIEN: HttpResponse(403),
    })
    connector = VnEntertainmentRSSConnector(transport=transport, clock=lambda: NOW)

    with pytest.raises(ConnectorError):
        asyncio.run(connector.fetch(None, FetchLimits()))

    assert len(transport.calls) == connector.dropped_items == 3
    assert connector.health().status == ConnectorState.UNAVAILABLE
    assert connector.health().last_error


def test_rss_round_robins_before_returning_a_second_item_from_one_publisher() -> None:
    connector = VnEntertainmentRSSConnector(transport=FakeTransport(rss_responses()), clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(max_items=4)))

    assert [item.metadata["publisher"] for item in items] == ["VnExpress", "Tuổi Trẻ", "Thanh Niên", "VnExpress"]


def test_hn_search_uses_expected_queries_and_matches_top_stories_url() -> None:
    transport = search_transport({
        "microdrama": HttpResponse(200, (FIXTURES / "hn_algolia_search.json").read_bytes()),
    })
    connector = HackerNewsSearchConnector(source_id="saved-search", transport=transport, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits(timeout_seconds=3)))

    expected_queries = [
        "AI short film", "AI generated film", "AI video generation", "text-to-video",
        "microdrama", "micro drama", "short drama", "AI animation", "AI actors",
    ]
    assert len(transport.calls) == len(expected_queries)
    for (url, timeout), query in zip(transport.calls, expected_queries, strict=True):
        assert timeout == 3
        assert parse_qs(urlsplit(url).query) == {
            "query": [query],
            "tags": ["story"],
            "numericFilters": [f"created_at_i>{int((NOW - timedelta(days=7)).timestamp())},points>=2"],
            "hitsPerPage": ["20"],
        }
    assert [item.external_id for item in items] == ["49196596", "50411326", "49369853"]
    first, second, _ = items
    assert first.source_id == "saved-search"
    assert first.title == "AI generated over 95% of China's new microdramas in Q1 2026"
    assert first.creator == "qikouki"
    assert first.published_at == datetime(2026, 8, 6, 13, 44, 20, tzinfo=UTC)
    assert first.metrics == MetricSnapshot(comments=3)
    assert second.metrics == MetricSnapshot(comments=0)
    assert first.metrics_snapshot_at == first.fetched_at == NOW
    assert first.metadata == {
        "hn_score": 5, "matched_query": "microdrama",
        "article_url": "https://www.channelnewsasia.com/east-asia/ai-microdrama-china-film-industry-actors-jobs-6229191",
    }

    top_stories = HackerNewsConnector(transport=FakeTransport({
        TOP_STORIES_URL: json_response([49196596]),
        f"{API_BASE}item/49196596.json": json_response({"id": 49196596, "type": "story", "title": first.title}),
    }), clock=lambda: NOW)
    top_item, = asyncio.run(top_stories.fetch(None, FetchLimits()))
    assert first.source_url == top_item.source_url
    assert str(first.source_url) == "https://news.ycombinator.com/item?id=49196596"


def test_hn_search_keeps_first_match_skips_missing_titles_and_stops_when_full() -> None:
    first_hit, second_hit, _ = hn_hits()
    no_title = {**second_hit, "title": None}
    no_comments = {**second_hit, "num_comments": None, "url": "http://localhost/private"}
    transport = search_transport({
        "AI short film": json_response({"hits": [first_hit, no_title]}),
        "AI generated film": json_response({"hits": [first_hit, no_comments]}),
    })
    connector = HackerNewsSearchConnector(transport=transport, clock=lambda: NOW)
    first, second = asyncio.run(connector.fetch(None, FetchLimits(max_items=2)))

    assert first.external_id == "49196596" and second.external_id == "50411326"
    assert first.metadata["matched_query"] == "AI short film"
    assert second.metadata["matched_query"] == "AI generated film"
    assert "article_url" not in second.metadata
    assert second.metrics is None and second.metrics_snapshot_at is None
    assert connector.dropped_items == 1
    assert transport.calls == [(query_url("AI short film"), 30), (query_url("AI generated film"), 30)]


def test_hn_search_continues_after_failed_queries() -> None:
    first_hit, second_hit, _ = hn_hits()
    transport = search_transport({
        "AI short film": json_response({"hits": [first_hit]}),
        "AI generated film": HttpResponse(503),
        "AI video generation": json_response({"hits": {"fixture": "invalid hits list"}}),
        "text-to-video": json_response({"hits": [second_hit]}),
    })
    connector = HackerNewsSearchConnector(transport=transport, clock=lambda: NOW)
    items = asyncio.run(connector.fetch(None, FetchLimits()))

    assert [item.external_id for item in items] == ["49196596", "50411326"]
    assert connector.dropped_items == 2
    assert connector.health().last_success_at == NOW


def test_hn_search_raises_if_all_queries_fail() -> None:
    transport = search_transport(dict.fromkeys(SEARCH_QUERIES, HttpResponse(403)))
    connector = HackerNewsSearchConnector(transport=transport, clock=lambda: NOW)

    with pytest.raises(ConnectorError):
        asyncio.run(connector.fetch(None, FetchLimits()))

    assert len(transport.calls) == connector.dropped_items == len(SEARCH_QUERIES)
    assert connector.health().status == ConnectorState.UNAVAILABLE


@pytest.mark.parametrize("has_success", [True, False])
def test_hn_search_stops_at_server_backoff(has_success: bool) -> None:
    first_hit, *_ = hn_hits()
    backoff = HttpResponse(429, headers={"Retry-After": "10"})
    transport = search_transport({
        "AI short film": json_response({"hits": [first_hit]}) if has_success else backoff,
        "AI generated film": backoff,
    })
    connector = HackerNewsSearchConnector(transport=transport, clock=lambda: NOW)

    if has_success:
        item, = asyncio.run(connector.fetch(None, FetchLimits()))
        assert item.external_id == "49196596"
        assert len(transport.calls) == 2
    else:
        with pytest.raises(HttpConnectorError) as failure:
            asyncio.run(connector.fetch(None, FetchLimits()))
        assert failure.value.retry_after_seconds == 10
        assert len(transport.calls) == 1
    assert connector.dropped_items == 1


def test_registry_adds_one_source_per_entertainment_connector() -> None:
    factories = available_connectors()
    assert factories["vn_entertainment_rss"] is VnEntertainmentRSSConnector
    assert factories["hn_search"] is HackerNewsSearchConnector
    assert factories["vn_entertainment_rss"].capabilities == (ConnectorCapability.BROAD_DISCOVERY,)
    assert factories["hn_search"].capabilities == (ConnectorCapability.BROAD_DISCOVERY, ConnectorCapability.CROSS_MARKET)
    defaults = [
        (source.connector_id, source.name, source.platform, str(source.url))
        for source in default_sources() if source.connector_id in {"vn_entertainment_rss", "hn_search"}
    ]
    assert defaults == [
        ("vn_entertainment_rss", "Báo giải trí Việt Nam (VnExpress, Tuổi Trẻ, Thanh Niên)", "vn_news", VNEXPRESS),
        ("hn_search", "Hacker News — phim ngắn, micro-drama, AI video", "hacker_news", SEARCH),
    ]


def test_connectors_send_only_anonymous_https_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Request] = []
    responses = {**rss_responses(), query_url("AI short film"): json_response({"hits": hn_hits()})}

    class FakeHTTPSHandler(HTTPSHandler):
        def https_open(self, request: Request) -> addinfourl:
            requests.append(request)
            body = responses[request.full_url].body
            response = addinfourl(BytesIO(body), Message(), request.full_url, 200)
            response.msg = "OK"
            return response

    def fake_build_opener(
        proxy: ProxyHandler, redirects: http._NoRedirects, https: HTTPSHandler,
    ) -> OpenerDirector:
        return build_opener(proxy, redirects, FakeHTTPSHandler())

    monkeypatch.setattr(http, "build_opener", fake_build_opener)
    for connector in (VnEntertainmentRSSConnector(clock=lambda: NOW), HackerNewsSearchConnector(clock=lambda: NOW)):
        assert len(asyncio.run(connector.fetch(None, FetchLimits(max_items=1)))) == 1

    assert [request.full_url for request in requests] == list(responses)
    assert {urlsplit(request.full_url).hostname for request in requests} == {
        "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "hn.algolia.com",
    }
    for request in requests:
        url = urlsplit(request.full_url)
        assert request.get_method() == "GET" and request.data is None
        assert url.scheme == "https" and url.username is None and url.password is None
        assert dict(request.header_items()) == {"Host": url.hostname, "User-agent": http.USER_AGENT}
