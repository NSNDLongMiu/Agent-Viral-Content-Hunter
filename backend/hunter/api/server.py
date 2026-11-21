"""Single loopback server for the mounted API and the built dashboard."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

from hunter.config import Settings
from hunter.runtime.service import Runtime

from .app import create_app
from .dependencies import Services

_ASSET_TYPES = frozenset({
    ".avif", ".css", ".gif", ".ico", ".jpeg", ".jpg", ".js", ".mjs", ".png", ".svg", ".webp", ".woff", ".woff2",
})


class RuntimeService(Protocol):
    def lifespan(self) -> AbstractAsyncContextManager[None]: ...


def _static_file(root: Path, relative: Path) -> Path | None:
    try:
        candidate = (root / relative).resolve(strict=True)
        # Reject aliases outside the build tree, including Windows junctions.
        if candidate.relative_to(root) == relative and candidate.is_file():
            return candidate
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def create_server_app(
    settings: Settings | None = None, *, runtime_factory: Callable[[Services], RuntimeService] = Runtime,
) -> FastAPI:
    api = create_app(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Mounted applications do not receive lifespan events from Starlette.
        async with api.router.lifespan_context(api):
            services: Services = api.state.services
            if services.settings.runtime.enabled:
                async with runtime_factory(services).lifespan():
                    yield
            else:
                yield

    server = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    server.mount("/api", api)

    @server.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard(path: str) -> Response:
        parts = path.split("/")
        if parts[0] in {"api", "health"} or any(
            part.startswith(".") or any(character in part for character in "\\:\x00") for part in parts
        ):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        root = api.state.services.settings.runtime.dashboard_dir.resolve()
        index = _static_file(root, Path("index.html"))
        if index is None:
            return JSONResponse(
                {"detail": "Dashboard build not found. Build dashboard/dist or set runtime.dashboard_dir."},
                status_code=503,
            )
        if parts[0] == "assets":
            relative = Path(*parts)
            asset = _static_file(root, relative) if relative.suffix.lower() in _ASSET_TYPES else None
            if asset is None:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(asset)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return server


app = create_server_app()
