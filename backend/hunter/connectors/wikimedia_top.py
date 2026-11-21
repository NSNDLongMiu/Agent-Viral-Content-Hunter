import json
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import MetricSnapshot, RawItem

from ._base import FetchBatch, PublicConnector
from .http import HttpConnectorError

API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/"


class WikimediaTopConnector(PublicConnector):
    id = "wikimedia_top"
    capabilities = (ConnectorCapability.BROAD_DISCOVERY, ConnectorCapability.CROSS_MARKET)

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        today = self._now().date()
        for lag in (1, 2):
            day = today - timedelta(days=lag)
            articles = await self._daily_articles(day, limits)
            if articles:
                break
        else:
            raise ConnectorError("Wikimedia returned no pageview data for either day.")

        end_of_window = datetime.combine(day + timedelta(days=1), time.min, UTC)
        if batch.since is not None and batch.since >= end_of_window:
            return
        for article in articles:
            batch.add(lambda: self._parse_article(article, day))
            if len(batch.items) == limits.max_items:
                break

    async def _daily_articles(self, day: date, limits: FetchLimits) -> list[object]:
        try:
            body = await self._get(API_BASE + day.strftime("%Y/%m/%d"), limits)
        except HttpConnectorError as error:
            if error.not_found:
                return []
            raise
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            raise ConnectorError("Wikimedia returned invalid pageviews JSON.") from None
        charts = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(charts, list):
            if not charts:
                return []
            chart = charts[0]
            if isinstance(chart, dict) and isinstance(chart.get("articles"), list):
                return chart["articles"]
        raise ConnectorError("Wikimedia returned an invalid pageviews chart.")

    def _parse_article(self, entry: object, day: date) -> RawItem | None:
        if not isinstance(entry, dict):
            raise ValueError
        article = entry.get("article")
        if not isinstance(article, str) or not article.strip():
            raise ValueError
        if article in {"Main_Page", "-"} or article.startswith(("Special:", "Wikipedia:")):
            return None
        views = entry.get("views")
        rank = entry.get("rank")
        if type(views) is not int or type(rank) is not int or rank < 1:
            raise ValueError

        fetched_at = self._now()
        article_path = quote(article.replace(" ", "_"), safe="/:()")
        return RawItem(
            source_id=self._source_id, source_url=f"https://en.wikipedia.org/wiki/{article_path}",
            external_id=article, title=article.replace("_", " "), fetched_at=fetched_at,
            metrics=MetricSnapshot(views=views), metrics_snapshot_at=fetched_at,
            metadata={"pageviews_date": day.isoformat(), "rank": rank},
        )
