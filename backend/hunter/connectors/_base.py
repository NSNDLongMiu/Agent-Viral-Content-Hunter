import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address
from typing import ClassVar
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree as ET

from pydantic import TypeAdapter, ValidationError

from hunter.interfaces import ConnectorCapability, ConnectorError, FetchLimits
from hunter.models import ConnectorHealth, ConnectorState, RawItem
from hunter.models.common import PublicUrl, as_utc, utcnow

from .http import Transport, get_body, urllib_transport

_PUBLIC_URL = TypeAdapter(PublicUrl)
_CREDENTIAL_PARAMS = {
    "access_token", "api_key", "auth", "authorization", "id_token", "password", "refresh_token", "token",
}


def public_link(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = str(_PUBLIC_URL.validate_python(value))
    except ValidationError:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        address = ip_address(host)
    except ValueError:
        if "." not in host.rstrip(".") or host.rstrip(".").endswith((".localhost", ".local")):
            return None
    else:
        if not address.is_global:
            return None
    if any(key.lower() in _CREDENTIAL_PARAMS for form in (parts.query, parts.fragment) for key, _ in parse_qsl(form)):
        return None
    return url


class _FeedTree(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ConnectorError("XML feed contained a document type declaration.")


def parse_feed(body: bytes) -> ET.Element:
    try:
        return ET.fromstring(body, parser=ET.XMLParser(target=_FeedTree()))
    except (ET.ParseError, LookupError, ValueError):
        raise ConnectorError("Public endpoint returned invalid XML.") from None


@dataclass
class FetchBatch:
    since: datetime | None
    items: list[RawItem] = field(default_factory=list)
    dropped_items: int = 0
    _seen_ids: set[str] = field(default_factory=set, init=False)

    def add(self, parse: Callable[[], RawItem | None]) -> None:
        try:
            item = parse()
        except (ValueError, OverflowError, OSError):
            self.dropped_items += 1
            return
        if item is not None and (
            self.since is None or item.published_at is None or item.published_at >= self.since
        ):
            if item.external_id is not None:
                if item.external_id in self._seen_ids:
                    return
                self._seen_ids.add(item.external_id)
            self.items.append(item)


class PublicConnector:
    id: ClassVar[str]
    capabilities: ClassVar[tuple[ConnectorCapability, ...]]

    def __init__(
        self, *, source_id: str | None = None, transport: Transport = urllib_transport,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._source_id = self.id if source_id is None else source_id.strip()
        if not self._source_id:
            raise ValueError("Source ID must be nonempty.")
        self._transport = transport
        self._clock = clock
        self._fetch_lock = asyncio.Lock()
        self._dropped_items = 0
        self._health = ConnectorHealth(
            connector_id=self.id, status=ConnectorState.UNAVAILABLE, checked_at=self._now(),
            last_error="No successful fetch yet.",
        )

    @property
    def dropped_items(self) -> int:
        """Malformed records dropped during the most recent completed fetch."""
        return self._dropped_items

    def health(self) -> ConnectorHealth:
        return self._health.model_copy()

    def _now(self) -> datetime:
        return as_utc(self._clock())

    async def _get(self, url: str, limits: FetchLimits) -> bytes:
        return await asyncio.to_thread(get_body, url, limits.timeout_seconds, self._transport)

    async def fetch(self, since: datetime | None, limits: FetchLimits) -> list[RawItem]:
        batch = FetchBatch(as_utc(since) if since is not None else None)
        async with self._fetch_lock:
            last_success = self._health.last_success_at
            try:
                await self._collect(batch, limits)
            except ConnectorError as error:
                status = ConnectorState.DEGRADED if last_success else ConnectorState.UNAVAILABLE
                self._record_health(batch, status, last_success, str(error))
                raise

            if batch.dropped_items and not batch.items:
                self._record_health(batch, ConnectorState.DEGRADED, last_success, "No usable items after validation.")
            else:
                self._record_health(batch, ConnectorState.AVAILABLE, self._now(), None)
            return batch.items

    def _record_health(
        self, batch: FetchBatch, status: ConnectorState, last_success: datetime | None,
        error: str | None,
    ) -> None:
        self._dropped_items = batch.dropped_items
        self._health = ConnectorHealth(
            connector_id=self.id, status=status, checked_at=self._now(),
            last_success_at=last_success, last_error=error,
        )

    async def _collect(self, batch: FetchBatch, limits: FetchLimits) -> None:
        raise NotImplementedError
