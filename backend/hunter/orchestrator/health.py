"""Publish the adapters' last observed health to the monitor."""

from collections.abc import Iterable

from hunter.interfaces import AIHealth, AIWorker
from hunter.services.monitor import MonitorService


def report_health(monitor_service: MonitorService, adapter: AIWorker) -> AIHealth:
    health = adapter.health()
    monitor_service.record_ai_health(health)
    return health


def report_adapters_health(
    monitor_service: MonitorService, adapters: Iterable[AIWorker],
) -> list[AIHealth]:
    return [report_health(monitor_service, adapter) for adapter in adapters]
