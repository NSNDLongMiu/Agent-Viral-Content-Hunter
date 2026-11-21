"""Group related observations using URLs, title similarity and Trends queries."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from hunter.db import Database
from hunter.models import RawItem
from hunter.models.common import new_id, utc_iso, utcnow

from .contracts import ClusterPort
from .normalize import _words, canonical_url, title_tokens
from .service import _load_item, _raw_item


def _phrase(text: str) -> str:
    return " ".join(_words(text, split_han=True))


@dataclass(frozen=True)
class _MatchKeys:
    urls: set[str]
    tokens: set[str]
    phrases: list[str]
    query: str

    @classmethod
    def from_item(cls, item: RawItem, connector_id: str) -> "_MatchKeys":
        urls = set()
        for value in (str(item.source_url), item.metadata.get("canonical_url"), item.metadata.get("article_url")):
            if isinstance(value, str):
                try:
                    urls.add(canonical_url(value))
                except ValueError:
                    continue  # Optional metadata and observations stored before ingest may have local links.

        title = item.title or ""
        title_phrase = _phrase(title)
        entities = item.metadata.get("entities")
        labels = list(entities) if isinstance(entities, list) else [entities]
        labels.append(item.metadata.get("entity"))
        return cls(
            urls=urls, tokens=set(title_tokens(title)),
            phrases=[title_phrase, *(_phrase(label) for label in labels if isinstance(label, str))],
            query=title_phrase if connector_id == "google_trends_vn" else "",
        )

    def matches(self, other: "_MatchKeys") -> bool:
        if self.urls & other.urls:
            return True
        if len(self.tokens) >= 3 and len(other.tokens) >= 3:
            # Jaccard >= 3/5, including the exact boundary.
            if 5 * len(self.tokens & other.tokens) >= 3 * len(self.tokens | other.tokens):
                return True
        return self._query_in(other.phrases) or other._query_in(self.phrases)

    def _query_in(self, phrases: list[str]) -> bool:
        return bool(self.query) and any(f" {self.query} " in f" {phrase} " for phrase in phrases)


def _signals(item: RawItem) -> list[str]:
    metrics = item.metrics.model_dump(exclude_none=True) if item.metrics is not None else {}
    for name in ("hn_score", "rank"):
        value = item.metadata.get(name)
        if type(value) is int:
            metrics[name] = value
    traffic = item.metadata.get("search_traffic_label")
    if isinstance(traffic, str) and traffic.strip():
        metrics["search_traffic_label"] = traffic
    return [f"{name}={value} ({item.source_id})" for name, value in metrics.items()]


class ClusterService(ClusterPort):
    def __init__(
        self, database: Database, *, window: timedelta = timedelta(hours=72),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if window < timedelta():
            raise ValueError("The cluster window cannot be negative")
        self.database = database
        self.window = window
        self.clock = clock

    def assign(self, raw_item_id: str) -> str | None:
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT cluster_id FROM trend_cluster_members WHERE raw_item_id = ? ORDER BY cluster_id LIMIT 1",
                (raw_item_id,),
            ).fetchone()
            if existing is not None:
                return existing["cluster_id"]

            item = _load_item(connection, raw_item_id)
            connector_id = connection.execute(
                "SELECT connector_id FROM sources WHERE id = ?", (item.source_id,),
            ).fetchone()["connector_id"]
            keys = _MatchKeys.from_item(item, connector_id)
            candidates = connection.execute(
                """SELECT raw_items.*, sources.connector_id, members.cluster_id
                   FROM raw_items JOIN sources ON sources.id = raw_items.source_id
                   LEFT JOIN trend_cluster_members AS members ON members.raw_item_id = raw_items.id
                   WHERE raw_items.id <> ? AND raw_items.fetched_at BETWEEN ? AND ?
                   ORDER BY raw_items.fetched_at DESC, raw_items.id, members.cluster_id""",
                (raw_item_id, utc_iso(item.fetched_at - self.window), utc_iso(item.fetched_at + self.window)),
            )
            matches = [row for row in candidates if keys.matches(_MatchKeys.from_item(
                _raw_item(row), row["connector_id"],
            ))]
            if not matches:
                return None

            # Prefer the cluster of the newest matching member. Leave existing clusters intact.
            cluster_id = next((row["cluster_id"] for row in matches if row["cluster_id"] is not None), None)
            now = utc_iso(self.clock())
            if cluster_id is None:
                cluster_id = new_id()
                topic = item.title or next((row["title"] for row in matches if row["title"]), str(item.source_url))
                connection.execute(
                    """INSERT INTO trend_clusters (id, topic, detected_at, trend_status, created_at)
                       VALUES (?, ?, ?, 'emerging', ?)""", (cluster_id, topic, now, now),
                )

            new_members = [raw_item_id, *(row["id"] for row in matches if row["cluster_id"] is None)]
            connection.executemany(
                """INSERT INTO trend_cluster_members (cluster_id, raw_item_id, trusted, created_at)
                   SELECT ?, raw_items.id, CASE WHEN sources.reliability >= 70 THEN 1 ELSE 0 END, ?
                   FROM raw_items JOIN sources ON sources.id = raw_items.source_id
                   WHERE raw_items.id = ?""",
                ((cluster_id, now, item_id) for item_id in new_members),
            )
            members = [_raw_item(row) for row in connection.execute(
                """SELECT raw_items.* FROM trend_cluster_members AS members
                   JOIN raw_items ON raw_items.id = members.raw_item_id WHERE members.cluster_id = ?
                   ORDER BY raw_items.fetched_at DESC, raw_items.id""", (cluster_id,),
            )]
            signals = list(dict.fromkeys(signal for member in members for signal in _signals(member)))
            status = "rising" if len({member.source_id for member in members}) >= 2 else "emerging"
            connection.execute(
                "UPDATE trend_clusters SET viral_signals_json = ?, trend_status = ? WHERE id = ?",
                (json.dumps(signals, ensure_ascii=False, separators=(",", ":")), status, cluster_id),
            )
            return cluster_id

    def related_items(self, raw_item_id: str, *, limit: int = 10) -> list[RawItem]:
        with self.database.transaction(write=False) as connection:
            item = _load_item(connection, raw_item_id)
            rows = connection.execute(
                """SELECT raw_items.* FROM trend_cluster_members AS members
                   JOIN raw_items ON raw_items.id = members.raw_item_id
                   WHERE members.cluster_id = (
                       SELECT cluster_id FROM trend_cluster_members WHERE raw_item_id = ? ORDER BY cluster_id LIMIT 1
                   ) AND members.raw_item_id <> ?
                   ORDER BY raw_items.fetched_at DESC, raw_items.id LIMIT ?""",
                (raw_item_id, raw_item_id, max(0, limit - 1)),
            )
            return [item, *(_raw_item(row) for row in rows)]
