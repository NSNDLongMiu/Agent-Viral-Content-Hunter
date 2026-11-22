import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import MetricSnapshot, RawItem

from ._base import FetchBatch, PublicConnector, public_link
from .http import HttpConnectorError

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
SEARCH_QUERIES = (
    "AI short film",
    "AI generated film",
    "AI video generation",
    "text-to-video",
    "microdrama",
    "micro drama",
    "short drama",
    "AI animation",
    "AI actors",
)


class HackerNewsSearchConnector(PublicConnector):
    id = "hn_search"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY, ConnectorCapability.CROSS_MARKET)

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        cutoff = int((self._now() - timedelta(days=7)).timestamp())
        succeeded = False
        last_error: ConnectorError | None = None
        for query in SEARCH_QUERIES:
            params = urlencode({
                "query": query, "tags": "story", "numericFilters": f"created_at_i>{cutoff},points>=2", "hitsPerPage": 20,
            })
            try:
                body = await self._get(f"{SEARCH_URL}?{params}", limits)
                hits = self._parse_response(body)
            except ConnectorError as error:
                last_error = error
                batch.dropped_items += 1
                if isinstance(error, HttpConnectorError) and (
                    error.status == 429 or error.retry_after_seconds is not None or error.rate_limit_reached
                ):
                    break
                continue

            succeeded = True
            for hit in hits:
                batch.add(lambda: self._parse_hit(query, hit))
                if len(batch.items) == limits.max_items:
                    return

        if not succeeded and last_error is not None:
            raise last_error

    @staticmethod
    def _parse_response(body: bytes) -> list[object]:
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            raise ConnectorError("Hacker News search returned invalid JSON.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            raise ConnectorError("Hacker News search returned an invalid hits list.")
        return payload["hits"]

    def _parse_hit(self, query: str, hit: object) -> RawItem:
        if not isinstance(hit, dict):
            raise ValueError
        story_id = hit.get("objectID")
        title = hit.get("title")
        if not isinstance(story_id, str) or not story_id.isascii() or not story_id.isdecimal():
            raise ValueError
        if not isinstance(title, str) or not title.strip():
            raise ValueError

        timestamp = hit.get("created_at_i")
        if timestamp is not None and type(timestamp) is not int:
            raise ValueError
        published_at = datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else None
        comments = hit.get("num_comments")
        if comments is not None and type(comments) is not int:
            raise ValueError
        metrics = MetricSnapshot(comments=comments) if comments is not None else None
        score = hit.get("points")
        article_url = public_link(hit.get("url"))
        fetched_at = self._now()
        return RawItem(
            source_id=self._source_id,
            source_url=f"https://news.ycombinator.com/item?id={story_id}",
            external_id=story_id, title=title, creator=hit.get("author"),
            published_at=published_at, fetched_at=fetched_at, metrics=metrics,
            metrics_snapshot_at=fetched_at if metrics is not None else None,
            metadata={
                "matched_query": query,
                **({"hn_score": score} if type(score) is int else {}),
                **({"article_url": article_url} if article_url else {}),
            },
        )
