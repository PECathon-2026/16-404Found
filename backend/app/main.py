from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .api.routes.main import build_router
from .bootstrap import build_container
from .common.ids import new_id
from .config import Settings


def create_app(settings: Settings | None = None, checkpointer=None) -> FastAPI:  # type: ignore[no-untyped-def]
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        if checkpointer is not None:
            app.state.c = build_container(settings, checkpointer)
            app.include_router(build_router(app.state.c))
            yield
            return
        conn = await aiosqlite.connect(settings.data_dir / "checkpoints.db")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        app.state.c = build_container(settings, saver)
        app.include_router(build_router(app.state.c))
        try:
            yield
        finally:
            await conn.close()
            app.state.c.deps.db.close()

    app = FastAPI(title="DevPilot", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-Id") or new_id("req")
        resp = await call_next(request)
        resp.headers["X-Request-Id"] = rid
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        return JSONResponse({"error": {"code": "INTERNAL", "message": f"{type(exc).__name__}"}}, status_code=500)

    from fastapi import HTTPException

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail), "details": {}}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    return app


app = create_app()
