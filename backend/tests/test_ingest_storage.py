import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest

from hunter.db import Database
from hunter.ingest import ClusterService, Ingestor, IngestResult, collect, smoke
from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import ConnectorHealth, ConnectorState, MetricSnapshot, RawItem, Source, SourceInput
from hunter.services.operations import OperationsService
from hunter.state import NotFound

NOW = datetime(2026, 11, 22, 4, tzinfo=UTC)


@pytest.fixture
def operations(tmp_path: Path) -> OperationsService:
    database = Database(tmp_path / "ingest-fixture.sqlite3")
    database.migrate()
    return OperationsService(database, clock=lambda: NOW)


def fixture_source(operations: OperationsService, connector_id: str, reliability: int | None = None) -> Source:
    return operations.save_source(SourceInput(
        connector_id=connector_id, name=connector_id, platform=f"fixture-{connector_id}",
        url=f"https://example.org/{connector_id}", reliability=reliability,
    ), reason="Ingest test fixture")


def fixture_item(source: Source, path: str, title: str | None = None, **fields: object) -> RawItem:
    return RawItem.model_validate({
        "source_id": source.id, "source_url": f"https://example.com/{path}",
        "title": title, "fetched_at": NOW, **fields,
    })


def test_exact_fingerprints_dedup_across_urls_external_ids_and_titles(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    other = fixture_source(operations, "wikimedia_top")
    ingestor = Ingestor(operations.database, clock=lambda: NOW)
    initial = fixture_item(source, "original/?utm_campaign=fixture", "Ａlpha  BETA Gamma", external_id="A")
    item_id, = ingestor.ingest(source, [initial]).new_item_ids

    duplicate_url = fixture_item(other, "original#fixture", "Different words completely", external_id="B")
    duplicate_external = fixture_item(source, "other", "Another fixture title", external_id="A")
    duplicate_title = fixture_item(other, "more", "alpha beta gamma", external_id="C")
    assert ingestor.ingest(other, [duplicate_url, duplicate_title]) == IngestResult(duplicate_count=2)
    assert ingestor.ingest(source, [duplicate_external]) == IngestResult(duplicate_count=1)

    with operations.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0] == 1
        digests = dict(connection.execute("SELECT kind, digest FROM fingerprints WHERE raw_item_id = ?", (item_id,)))
        assert connection.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0] == 3
    assert digests == {
        name: sha256(value.encode()).hexdigest() for name, value in {
            "url": "https://example.com/original", "external": f"{source.id}|A", "title": "alpha beta gamma",
        }.items()
    }
    assert len(ingestor.ingest(other, [
        fixture_item(other, "short-one", "Mars", external_id="A"),
        fixture_item(other, "short-two", "Mars", external_id="B"),
    ]).new_item_ids) == 2


def test_two_concurrent_ingests_persist_one_item(operations: OperationsService) -> None:
    source = fixture_source(operations, "wikimedia_top")
    item = fixture_item(source, "race", "Fixture item title", external_id="race")
    barrier = Barrier(2, timeout=5)

    def ingest_at_once() -> IngestResult:
        barrier.wait()
        return Ingestor(operations.database).ingest(source, [item])

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(ingest_at_once) for _ in range(2)]
        results = [future.result() for future in futures]

    assert sorted((len(result.new_item_ids), result.duplicate_count) for result in results) == [(0, 1), (1, 0)]
    assert not any(result.rejected_count for result in results)
    with operations.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0] == 3


def test_rejects_bad_items_and_continues(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    wrong_source = fixture_source(operations, "google_trends_vn")
    local = fixture_item(source, "local", source_url="https://127.0.0.1/fixture")
    bad_metrics = fixture_item(source, "bad-metrics").model_copy(update={"metrics": MetricSnapshot(views=4)})
    bad_metadata = fixture_item(source, "bad-metadata", metadata={"fixture": float("nan")})
    ingestor = Ingestor(operations.database)
    items = [local, fixture_item(wrong_source, "wrong"), bad_metrics, bad_metadata, fixture_item(source, "valid")]
    result = ingestor.ingest(source, items)
    assert result.rejected_count == 4 and result.duplicate_count == 0
    valid_id, = result.new_item_ids
    assert ingestor.get_item(valid_id).source_url.path == "/valid"
    with operations.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0] == 1


@pytest.mark.parametrize(("connector_id", "content_type"), [
    ("hacker_news", "tin công nghệ / thảo luận"), ("google_trends_vn", "xu hướng tìm kiếm"),
    ("wikimedia_top", "bài viết bách khoa"), ("fixture_unknown", None),
])
def test_raw_item_round_trip_and_metadata_defaults(
    operations: OperationsService, connector_id: str, content_type: str | None,
) -> None:
    source = fixture_source(operations, connector_id)
    local_time = NOW.astimezone(timezone(timedelta(hours=7)))
    original = fixture_item(
        source, "fixture/?q=1&gclid=2", "  Tin  mới về Hà Nội ", external_id="fixture-1",
        creator="Fixture Author", published_at=local_time - timedelta(hours=3), fetched_at=local_time,
        metrics_snapshot_at=local_time + timedelta(seconds=1), metrics={"comments": 2, "likes": 0},
        metadata={"fixture": {"labels": ["một", "二"], "active": False}},
    )
    ingestor = Ingestor(operations.database)
    item_id, = ingestor.ingest(source, [original]).new_item_ids
    stored = ingestor.get_item(item_id)
    expected_metadata = {
        **original.metadata, "platform": source.platform, "language": "vi", "canonical_url": "https://example.com/fixture?q=1",
    }
    if content_type is not None:
        expected_metadata["content_type"] = content_type
    assert stored == original.model_copy(update={"title": "Tin mới về Hà Nội", "metadata": expected_metadata})
    assert stored.fetched_at.tzinfo is UTC
    assert stored.published_at is not None and stored.published_at.tzinfo is UTC
    assert stored.metrics_snapshot_at is not None and stored.metrics_snapshot_at.tzinfo is UTC
    assert original.metadata == {"fixture": {"labels": ["một", "二"], "active": False}}
    with pytest.raises(NotFound, match="Raw item not found"):
        ingestor.get_item("missing-fixture")


def test_ingest_keeps_connector_metadata_and_uses_observed_url_for_dedup(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    ingestor = Ingestor(operations.database)
    supplied = {"platform": "fixture-override", "language": "zh", "content_type": None,
                "canonical_url": "https://example.net/supplied"}
    item = fixture_item(source, "observed", "Fixture title", metadata=supplied)
    item_id, = ingestor.ingest(source, [item]).new_item_ids
    assert ingestor.get_item(item_id).metadata == supplied
    assert ingestor.ingest(source, [fixture_item(source, "observed/?si=fixture")]).duplicate_count == 1
    assert len(ingestor.ingest(source, [fixture_item(source, "unrelated", metadata=supplied)]).new_item_ids) == 1


def test_shared_article_url_cluster_tracks_signals_trust_and_status(operations: OperationsService) -> None:
    first = fixture_source(operations, "hacker_news", reliability=70)
    second = fixture_source(operations, "wikimedia_top", reliability=69)
    cluster = ClusterService(operations.database, clock=lambda: NOW)
    ingestor = Ingestor(operations.database)
    oldest, = ingestor.ingest(first, [fixture_item(
        first, "observations/1", "Fixture discussion", fetched_at=NOW - timedelta(hours=3),
        metadata={"article_url": "https://example.com/article/?utm_medium=fixture", "hn_score": 9},
        metrics_snapshot_at=NOW, metrics={"comments": 0},
    )]).new_item_ids
    assert cluster.assign(oldest) is None
    assert cluster.related_items(oldest) == [ingestor.get_item(oldest)]

    middle, = ingestor.ingest(first, [fixture_item(
        first, "observations/2", "A different headline", fetched_at=NOW - timedelta(hours=2),
        metadata={"article_url": "https://example.com/article#fixture"},
    )]).new_item_ids
    cluster_id = cluster.assign(middle)
    assert cluster_id is not None
    with operations.database.connection() as connection:
        assert connection.execute("SELECT trend_status FROM trend_clusters").fetchone()[0] == "emerging"

    newest, = ingestor.ingest(second, [fixture_item(
        second, "article", "Reference page", metrics_snapshot_at=NOW, metrics={"views": 10},
        metadata={"rank": 2},
    )]).new_item_ids
    assert cluster.assign(newest) == cluster_id
    assert cluster.assign(oldest) == cluster.assign(middle) == cluster_id
    assert cluster.related_items(oldest) == [ingestor.get_item(item_id) for item_id in (oldest, newest, middle)]
    assert cluster.related_items(oldest, limit=2) == [ingestor.get_item(item_id) for item_id in (oldest, newest)]
    assert cluster.related_items(oldest, limit=1) == [ingestor.get_item(oldest)]

    with operations.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM trend_clusters").fetchone()[0] == 1
        row = connection.execute("SELECT * FROM trend_clusters WHERE id = ?", (cluster_id,)).fetchone()
        assert row["topic"] == "A different headline" and row["trend_status"] == "rising"
        assert json.loads(row["viral_signals_json"]) == [
            f"views=10 ({second.id})", f"rank=2 ({second.id})", f"comments=0 ({first.id})", f"hn_score=9 ({first.id})",
        ]
        trusted = dict(connection.execute("SELECT raw_item_id, trusted FROM trend_cluster_members"))
        assert trusted == {oldest: 1, middle: 1, newest: 0}


def test_cluster_accepts_jaccard_boundary_and_shared_legacy_url(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    cluster = ClusterService(operations.database)
    first, similar, too_short = Ingestor(operations.database).ingest(source, [
        fixture_item(source, "a", "Alpha beta gamma delta"),
        fixture_item(source, "b", "Beta gamma alpha epsilon"),
        fixture_item(source, "c", "Alpha beta"),
    ]).new_item_ids
    assert cluster.assign(too_short) is None
    cluster_id = cluster.assign(first)
    assert cluster_id is not None and cluster.assign(similar) == cluster_id

    legacy_a = operations.store_raw_item(fixture_item(source, "legacy/?utm_source=fixture", "One"))
    legacy_b = operations.store_raw_item(fixture_item(source, "legacy#fragment", "Two"))
    legacy_cluster = cluster.assign(legacy_a)
    assert legacy_cluster is not None and legacy_cluster != cluster_id and cluster.assign(legacy_b) == legacy_cluster


@pytest.mark.parametrize(("query", "title", "entities"), [
    ("Bão số 3", "Bản tin mới nhất về BÃO SỐ 3", []),
    ("Lunar Eclipse", "Astronomy viewing guide", ["Total Lunar-eclipse 2026"]),
    ("气象", "本地气象报道", []),
])
def test_cluster_matches_a_trends_query_in_a_title_or_entity(
    operations: OperationsService, query: str, title: str, entities: list[str],
) -> None:
    trends = fixture_source(operations, "google_trends_vn")
    news = fixture_source(operations, "hacker_news")
    ingestor = Ingestor(operations.database)
    cluster = ClusterService(operations.database)
    query_id, = ingestor.ingest(trends, [fixture_item(trends, "search", query)]).new_item_ids
    news_id, = ingestor.ingest(news, [fixture_item(news, "news", title, metadata={"entities": entities})]).new_item_ids
    cluster_id = cluster.assign(news_id)
    assert cluster_id is not None and cluster.assign(query_id) == cluster_id


def test_cluster_window_is_symmetric_and_inclusive(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    ingestor = Ingestor(operations.database)
    article = {"article_url": "https://example.com/fixture-article"}
    old, latest = ingestor.ingest(source, [
        fixture_item(source, "old", fetched_at=NOW - timedelta(hours=73), metadata=article),
        fixture_item(source, "latest", metadata=article),
    ]).new_item_ids
    assert ClusterService(operations.database).assign(old) is None
    assert ClusterService(operations.database).assign(latest) is None
    cluster = ClusterService(operations.database, window=timedelta(hours=73))
    cluster_id = cluster.assign(old)
    assert cluster_id is not None and cluster.assign(latest) == cluster_id


class FakeConnector:
    id = "hacker_news"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY,)

    def __init__(self, item: RawItem) -> None:
        self.item = item
        self.error: ConnectorError | None = None
        self.calls: list[tuple[datetime | None, FetchLimits]] = []

    async def fetch(self, since: datetime | None, limits: FetchLimits) -> list[RawItem]:
        self.calls.append((since, limits))
        if self.error is not None:
            raise self.error
        return [self.item]

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.id, status=ConnectorState.DEGRADED if self.error else ConnectorState.AVAILABLE,
            checked_at=NOW + timedelta(seconds=len(self.calls)), last_success_at=None if self.error else NOW,
            last_error=str(self.error) if self.error else None,
        )


def test_collect_records_connector_health_and_reraises_fetch_error(operations: OperationsService) -> None:
    source = fixture_source(operations, "hacker_news")
    connector = FakeConnector(fixture_item(source, "collect", "Fixture story title"))
    ingestor = Ingestor(operations.database)
    limits = FetchLimits(max_items=1)
    result = asyncio.run(collect(connector, source, ingestor, operations, since=NOW, limits=limits))
    item_id, = result.new_item_ids
    assert ingestor.get_item(item_id).title == "Fixture story title"
    assert connector.calls == [(NOW, limits)]
    assert operations.connector_health() == [connector.health()]

    connector.error = ConnectorError("Fixture endpoint unavailable")
    with pytest.raises(ConnectorError) as failure:
        asyncio.run(collect(connector, source, ingestor, operations, since=None, limits=limits))
    assert failure.value is connector.error
    assert operations.connector_health() == [connector.health().model_copy(update={"last_success_at": NOW})]
    with operations.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0] == 1


def test_ingest_smoke_entry_point_with_fake_source(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def fixture_factory(*, source_id: str) -> FakeConnector:
        return FakeConnector(RawItem(
            source_id=source_id, source_url="https://example.com/smoke", title="Local smoke fixture", fetched_at=NOW,
        ))

    monkeypatch.setattr(smoke, "available_connectors", lambda: {"hacker_news": fixture_factory})
    assert smoke.main(["hacker_news"]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert [json.loads(line) for line in captured.out.splitlines()] == [
        {"connector": "hacker_news", "health": "AVAILABLE", "new_items": 1,
         "duplicates": 0, "rejected": 0, "replay_duplicates": 1},
        {"stored_items": 1, "clusters": 0},
    ]
