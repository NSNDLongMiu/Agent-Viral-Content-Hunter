import asyncio
import json
from datetime import UTC, datetime
from itertools import islice

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import MetricSnapshot, RawItem

from ._base import FetchBatch, PublicConnector, public_link
from .http import HttpConnectorError

API_BASE = "https://hacker-news.firebaseio.com/v0/"
TOP_STORIES_URL = API_BASE + "topstories.json"
_MAX_PARALLEL_ITEMS = 4


class HackerNewsConnector(PublicConnector):
    id = "hacker_news"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY, ConnectorCapability.CROSS_MARKET)

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        body = await self._get(TOP_STORIES_URL, limits)
        try:
            top = json.loads(body)
        except (ValueError, RecursionError):
            raise ConnectorError("Hacker News returned invalid top stories JSON.") from None
        if not isinstance(top, list):
            raise ConnectorError("Hacker News returned an invalid top stories list.")

        ids: dict[int, None] = {}
        for story_id in top:
            if type(story_id) is int and story_id > 0:
                ids.setdefault(story_id, None)
            else:
                batch.dropped_items += 1

        pending = iter(ids)
        while len(batch.items) < limits.max_items:
            size = min(_MAX_PARALLEL_ITEMS, limits.max_items - len(batch.items))
            next_ids = tuple(islice(pending, size))
            if not next_ids:
                break
            bodies = await asyncio.gather(
                *(self._get_story(story_id, limits) for story_id in next_ids),
                return_exceptions=True,
            )
            for story_id, body in zip(next_ids, bodies, strict=True):
                if isinstance(body, BaseException):
                    raise body
                batch.add(lambda: self._parse_story(story_id, body))

    async def _get_story(self, story_id: int, limits: FetchLimits) -> bytes:
        try:
            return await self._get(f"{API_BASE}item/{story_id}.json", limits)
        except HttpConnectorError as error:
            if error.not_found:
                return b"null"
            raise

    def _parse_story(self, story_id: int, body: bytes) -> RawItem | None:
        try:
            story = json.loads(body)
        except RecursionError:
            raise ValueError from None
        if not isinstance(story, dict):
            raise ValueError
        if story.get("deleted") is True or story.get("dead") is True:
            return None
        if not isinstance(story.get("type"), str):
            raise ValueError
        if story["type"] != "story":
            return None
        if type(story.get("id")) is not int or story["id"] != story_id:
            raise ValueError
        title = story.get("title")
        if not isinstance(title, str):
            raise ValueError

        timestamp = story.get("time")
        if timestamp is not None and type(timestamp) is not int:
            raise ValueError
        published_at = datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else None

        comments = story.get("descendants")
        if comments is not None and type(comments) is not int:
            raise ValueError
        metrics = MetricSnapshot(comments=comments) if comments is not None else None
        score = story.get("score")
        article_url = public_link(story.get("url"))
        fetched_at = self._now()
        return RawItem(
            source_id=self._source_id,
            source_url=f"https://news.ycombinator.com/item?id={story_id}",
            external_id=str(story_id), title=title, creator=story.get("by"),
            published_at=published_at, fetched_at=fetched_at, metrics=metrics,
            metrics_snapshot_at=fetched_at if metrics else None,
            metadata={
                **({"hn_score": score} if type(score) is int else {}),
                **({"article_url": article_url} if article_url else {}),
            },
        )
