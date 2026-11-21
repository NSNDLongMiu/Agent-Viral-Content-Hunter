"""FastAPI entry point. Startup opens the local database and recovers pending work."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hunter.config import PaidAPIForbidden, Settings, load_settings
from hunter.db import Database
from hunter.interfaces import Notifier
from hunter.queue import PersistentQueue
from hunter.services.brief_store import BriefStore
from hunter.services.feedback import FeedbackService
from hunter.services.handoffs import HandoffService
from hunter.services.inbox import InboxService
from hunter.services.monitor import MonitorService
from hunter.services.operations import OperationsService
from hunter.services.retention import RetentionService
from hunter.services.review import ReviewService
from hunter.state import Conflict, IntegrationUnavailable, InvalidTransition, NotFound

from . import auth, routes
from .dependencies import Services

async def _domain_error(request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, NotFound):
        status = 404
    elif isinstance(error, IntegrationUnavailable):
        status = 503
    else:
        status = 409
    return JSONResponse({"detail": str(error)}, status_code=status)


async def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    # Pydantic errors can include raw credentials, extra keys and input fragments.
    return JSONResponse(
        {"detail": [
            {"loc": list(item["loc"][:1]), "msg": "Invalid request value", "type": item["type"]}
            for item in error.errors()
        ]},
        status_code=422,
    )


def create_app(settings: Settings | None = None, *, notifier: Notifier | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        effective = settings if settings is not None else load_settings()
        database = Database(effective.database_path)
        database.migrate()
        queue = PersistentQueue(database, effective.queue)
        queue.reclaim_expired()
        RetentionService(database, effective.retention).purge()
        application.state.auth = auth.AuthService(effective.auth)
        application.state.services = Services(
            settings=effective, database=database, queue=queue, briefs=BriefStore(database),
            inbox=InboxService(database), review=ReviewService(database),
            handoffs=HandoffService(database, budget=effective.budget), feedback=FeedbackService(database),
            operations=OperationsService(database), monitor=MonitorService(database), notifier=notifier,
        )
        yield

    application = FastAPI(
        title="Viral Content Hunter API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    for error in (NotFound, Conflict, InvalidTransition, IntegrationUnavailable, PaidAPIForbidden):
        application.add_exception_handler(error, _domain_error)
    application.add_exception_handler(RequestValidationError, _validation_error)
    for router in (
        routes.health, auth.router, routes.briefs, routes.review, routes.jobs, routes.sources,
        routes.handoffs, routes.feedback, routes.settings, routes.monitor,
    ):
        application.include_router(router)
    return application


app = create_app()
