"""Durable source changes and dashboard preferences, with transactional undo."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from hunter.db import Database
from hunter.models import ConnectorHealth, RawItem, Source, SourceInput
from hunter.models.common import Model, NonEmpty, UtcDatetime, new_id, utc_iso, utcnow
from hunter.state import Conflict, NotFound


class SettingKey(StrEnum):
    P1_THRESHOLD = "p1_threshold"
    SCAN_INTERVALS = "scan_intervals_minutes"
    PRIORITY_TOPICS = "priority_topics"
    EXCLUDED_TOPICS = "excluded_topics"
    TELEGRAM_ENABLED = "telegram_enabled"


class DashboardSettings(Model):
    p1_threshold: int = Field(default=85, ge=0, le=100, strict=True)
    scan_intervals_minutes: dict[NonEmpty, Annotated[int, Field(gt=0, strict=True)]] = Field(
        default_factory=dict
    )
    priority_topics: list[NonEmpty] = Field(default_factory=list)
    excluded_topics: list[NonEmpty] = Field(default_factory=list)
    telegram_enabled: bool = Field(default=False, strict=True)


class AuditRecord(Model):
    id: int
    entity: Literal["source", "setting"]
    entity_key: NonEmpty
    action: Literal["create", "update", "adjust", "undo"]
    actor: Literal["admin", "automation"]
    reason: NonEmpty
    before: JsonValue
    after: JsonValue
    undoes_id: int | None
    created_at: UtcDatetime


_SOURCE_FIELDS = """id, connector_id, name, url, platform, enabled, blocked,
                    priority, reliability, activity, content_value, created_at, updated_at"""


def _json(value: JsonValue) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False)


def _audit_model(row: sqlite3.Row) -> AuditRecord:
    data = dict(row)
    for field in ("before", "after"):
        value = data.pop(f"{field}_json")
        data[field] = json.loads(value) if value is not None else None
    return AuditRecord.model_validate(data)


def _record(
    connection: sqlite3.Connection, *, entity: str, key: str, action: str, actor: str,
    reason: str, before: JsonValue, after: JsonValue, now: str, undoes_id: int | None = None,
) -> AuditRecord:
    reason = TypeAdapter(NonEmpty).validate_python(reason)
    return _audit_model(connection.execute(
        """INSERT INTO audit_log (
            entity, entity_key, action, actor, reason, before_json, after_json, undoes_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
        (entity, key, action, actor, reason, _json(before), _json(after), undoes_id, now),
    ).fetchone())


def _get_source(connection: sqlite3.Connection, source_id: str) -> Source | None:
    row = connection.execute(
        f"SELECT {_SOURCE_FIELDS} FROM sources WHERE id = ? AND removed_at IS NULL", (source_id,)
    ).fetchone()
    return Source.model_validate(dict(row)) if row else None


def _write_source(connection: sqlite3.Connection, source: Source) -> None:
    try:
        connection.execute(
            f"""INSERT INTO sources ({_SOURCE_FIELDS})
                VALUES (:id, :connector_id, :name, :url, :platform, :enabled, :blocked,
                        :priority, :reliability, :activity, :content_value, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET connector_id = excluded.connector_id,
                    name = excluded.name, url = excluded.url, platform = excluded.platform,
                    enabled = excluded.enabled, blocked = excluded.blocked, priority = excluded.priority,
                    reliability = excluded.reliability, activity = excluded.activity,
                    content_value = excluded.content_value, removed_at = NULL,
                    created_at = excluded.created_at, updated_at = excluded.updated_at""",
            {
                **source.model_dump(mode="json"),
                "created_at": utc_iso(source.created_at),
                "updated_at": utc_iso(source.updated_at),
            },
        )
    except sqlite3.IntegrityError:
        raise Conflict("This connector already has an active source with that URL") from None


def _get_setting(connection: sqlite3.Connection, key: str) -> JsonValue:
    row = connection.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else None


def _write_setting(connection: sqlite3.Connection, key: str, value: JsonValue, now: str) -> None:
    if value is None:
        connection.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        connection.execute(
            """INSERT INTO settings (key, value_json, created_at, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
            (key, _json(value), now, now),
        )


class OperationsService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.clock = clock

    def list_sources(self, *, limit: int = 50, offset: int = 0) -> list[Source]:
        with self.database.connection() as connection:
            return [Source.model_validate(dict(row)) for row in connection.execute(
                f"""SELECT {_SOURCE_FIELDS} FROM sources WHERE removed_at IS NULL
                    ORDER BY priority DESC, name, id LIMIT ? OFFSET ?""", (limit, offset)
            )]

    def get_source(self, source_id: str) -> Source:
        with self.database.connection() as connection:
            source = _get_source(connection, source_id)
            if source is None:
                raise NotFound("Source not found")
            return source

    def save_source(
        self, data: SourceInput, *, reason: str, source_id: str | None = None,
        actor: Literal["admin", "automation"] = "admin",
    ) -> Source:
        with self.database.transaction() as connection:
            now = utc_iso(self.clock())
            previous = _get_source(connection, source_id) if source_id is not None else None
            if source_id is not None and previous is None:
                raise NotFound("Source not found")
            source = Source(
                **data.model_dump(), id=source_id or new_id(), updated_at=now,
                created_at=previous.created_at if previous else now,
            )
            _write_source(connection, source)
            action = "adjust" if actor == "automation" else ("update" if previous else "create")
            _record(
                connection, entity="source", key=source.id, action=action, actor=actor,
                reason=reason, before=previous.model_dump(mode="json") if previous else None,
                after=source.model_dump(mode="json"), now=now,
            )
            return source

    def remove_source(self, source_id: str, *, reason: str) -> AuditRecord:
        with self.database.transaction() as connection:
            previous = _get_source(connection, source_id)
            if previous is None:
                raise NotFound("Source not found")
            now = utc_iso(self.clock())
            connection.execute("UPDATE sources SET removed_at = ? WHERE id = ?", (now, source_id))
            return _record(
                connection, entity="source", key=source_id, action="update", actor="admin",
                reason=reason, before=previous.model_dump(mode="json"), after=None, now=now,
            )

    def store_raw_item(self, item: RawItem) -> str:
        """Persist an observation; T2 owns fingerprinting and collection policy."""
        item_id = new_id()
        with self.database.transaction() as connection:
            if _get_source(connection, item.source_id) is None:
                raise NotFound("Source not found")
            connection.execute(
                """INSERT INTO raw_items (
                    id, source_id, source_url, external_id, title, creator, published_at, fetched_at,
                    metrics_snapshot_at, metrics_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id, item.source_id, str(item.source_url), item.external_id, item.title, item.creator,
                    utc_iso(item.published_at) if item.published_at else None, utc_iso(item.fetched_at),
                    utc_iso(item.metrics_snapshot_at) if item.metrics_snapshot_at else None,
                    item.metrics.model_dump_json() if item.metrics else None,
                    _json(item.metadata), utc_iso(self.clock()),
                ),
            )
        return item_id

    def record_connector_health(self, health: ConnectorHealth) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO connector_status (connector_id, status, checked_at, last_success_at, last_error)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(connector_id) DO UPDATE SET status = excluded.status,
                       checked_at = excluded.checked_at, last_error = excluded.last_error,
                       last_success_at = COALESCE(excluded.last_success_at, connector_status.last_success_at)
                   WHERE excluded.checked_at >= connector_status.checked_at""",
                (
                    health.connector_id, health.status, utc_iso(health.checked_at),
                    utc_iso(health.last_success_at) if health.last_success_at else None, health.last_error,
                ),
            )

    def connector_health(self) -> list[ConnectorHealth]:
        with self.database.connection() as connection:
            return [ConnectorHealth.model_validate(dict(row)) for row in connection.execute(
                "SELECT * FROM connector_status ORDER BY connector_id"
            )]

    def preferences(self) -> DashboardSettings:
        with self.database.connection() as connection:
            data = {row["key"]: json.loads(row["value_json"]) for row in connection.execute(
                "SELECT key, value_json FROM settings"
            )}
            return DashboardSettings.model_validate(data)

    def set_preference(
        self, key: SettingKey, value: JsonValue, *, reason: str,
        actor: Literal["admin", "automation"] = "admin",
    ) -> AuditRecord:
        key = SettingKey(key)
        try:
            value = DashboardSettings.model_validate({key: value}).model_dump(mode="json")[key]
        except ValidationError:
            raise Conflict("Invalid value for this preference") from None
        if actor == "automation" and key not in (SettingKey.SCAN_INTERVALS, SettingKey.PRIORITY_TOPICS):
            raise Conflict("Automation may only adjust scan intervals and priority topics")
        with self.database.transaction() as connection:
            now = utc_iso(self.clock())
            before = _get_setting(connection, key)
            _write_setting(connection, key, value, now)
            action = "adjust" if actor == "automation" else ("create" if before is None else "update")
            return _record(
                connection, entity="setting", key=key, action=action, actor=actor,
                reason=reason, before=before, after=value, now=now,
            )

    def audit(self, *, limit: int = 50, offset: int = 0) -> list[AuditRecord]:
        with self.database.connection() as connection:
            return [_audit_model(row) for row in connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            )]

    def undo(self, record_id: int, *, reason: str) -> AuditRecord:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM audit_log WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                raise NotFound("Audit record not found")
            done = connection.execute("SELECT * FROM audit_log WHERE undoes_id = ?", (record_id,)).fetchone()
            if done is not None:
                return _audit_model(done)
            record = _audit_model(row)
            now = utc_iso(self.clock())
            if record.entity == "source":
                current = _get_source(connection, record.entity_key)
                if (current.model_dump(mode="json") if current else None) != record.after:
                    raise Conflict("The source has changed since this audit record")
                if record.before is None:
                    connection.execute("UPDATE sources SET removed_at = ? WHERE id = ?", (now, record.entity_key))
                else:
                    _write_source(connection, Source.model_validate(record.before))
            else:
                if _get_setting(connection, record.entity_key) != record.after:
                    raise Conflict("The setting has changed since this audit record")
                _write_setting(connection, record.entity_key, record.before, now)
            return _record(
                connection, entity=record.entity, key=record.entity_key, action="undo", actor="admin",
                reason=reason, before=record.after, after=record.before, now=now, undoes_id=record.id,
            )
