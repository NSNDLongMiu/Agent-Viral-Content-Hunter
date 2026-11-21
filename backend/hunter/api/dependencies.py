from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request

from hunter.config import Settings
from hunter.db import Database
from hunter.interfaces import Notifier
from hunter.models.common import Model
from hunter.queue import PersistentQueue
from hunter.services.brief_store import BriefStore
from hunter.services.feedback import FeedbackService
from hunter.services.handoffs import HandoffService
from hunter.services.inbox import InboxService
from hunter.services.monitor import MonitorService
from hunter.services.operations import OperationsService
from hunter.services.review import ReviewService


@dataclass
class Services:
    settings: Settings
    database: Database
    queue: PersistentQueue
    briefs: BriefStore
    inbox: InboxService
    review: ReviewService
    handoffs: HandoffService
    feedback: FeedbackService
    operations: OperationsService
    monitor: MonitorService
    notifier: Notifier | None
    runtime_notifier: Callable[[], Notifier | None] | None = None


def get_services(request: Request) -> Services:
    return request.app.state.services


Backend = Annotated[Services, Depends(get_services)]


class Pagination(Model):
    limit: Annotated[int, Query(ge=1, le=200)] = 50
    offset: Annotated[int, Query(ge=0)] = 0


Page = Annotated[Pagination, Depends()]
