import asyncio
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.exceptions import HTTPException

from . import __version__
from .config import ROOT, Settings, settings
from .models import INCIDENT, STRATEGY, CancelRun, CreateRun, DomainError
from .storage import Store, uid
from .telemetry import Telemetry, context, log, span_id

IdPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
PageLimit = Annotated[int, Query(ge=1, le=100)]
AfterSeq = Annotated[int, Query(ge=0)]


def create_app(config: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = config or settings()
        telemetry = Telemetry(cfg.probeops_telemetry_dir, "api", cfg.log_level)
        app.state.telemetry = telemetry
        app.state.store = Store(cfg.probeops_db_path, telemetry)

        async def recover() -> None:
            while True:
                await asyncio.sleep(2)
                try:
                    count = await asyncio.to_thread(app.state.store.recover)
                    if count:
                        log("worker_recovered", outcome="worker_lost")
                except sqlite3.Error:
                    log("recovery_failed", error_code="STORAGE_UNAVAILABLE")

        recovery = asyncio.create_task(recover())
        yield
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery
        telemetry.close()

    app = FastAPI(
        title="ProbeOps", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    # The reviewed Git Spec is authoritative; drift is checked in contract tests.
    app.openapi = lambda: json.loads((ROOT / "docs/api/openapi.json").read_text())  # type: ignore[method-assign]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    def error(
        request: Request, status: int, code: str, message: str, retryable: bool = False
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "code": code,
                "message": message,
                "request_id": request.state.request_id,
                "retryable": retryable,
            },
            headers={"X-Request-ID": request.state.request_id},
        )

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uid("req")
        token = context.set({"request_id": request.state.request_id})
        # Static path templates only; unknown paths must not leak attacker-controlled segments.
        route = "unmatched"
        for candidate in app.routes:
            pattern = getattr(candidate, "path_regex", None)
            if pattern and pattern.fullmatch(request.url.path):
                route = getattr(candidate, "path", "unmatched")
                break
        try:
            parent = TraceContextTextMapPropagator().extract(
                {"traceparent": request.headers.get("traceparent", "")}
            )
            method = (
                request.method if request.method in {"GET", "POST", "OPTIONS", "HEAD"} else "OTHER"
            )
            with app.state.telemetry.span(
                f"HTTP {method} {route}", parent=parent, route=route
            ) as span:
                try:
                    response = await call_next(request)
                except Exception as exc:
                    log("request_failed", error_code=type(exc).__name__)
                    response = error(request, 500, "INTERNAL_ERROR", "服务内部错误。")
                span.set_attribute("http.response.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(trace.StatusCode.ERROR)
                response.headers["X-Request-ID"] = request.state.request_id
                return response
        finally:
            context.reset(token)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(request, 422, "VALIDATION_ERROR", "请求参数无效，请检查必填字段和取值范围。")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error(request, exc.status_code, "HTTP_ERROR", "请求路径或方法不可用。")

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        log("storage_unavailable", error_code=type(exc).__name__)
        return error(request, 503, "STORAGE_UNAVAILABLE", "本地存储暂时不可用。", True)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/incidents")
    def incidents() -> dict[str, Any]:
        return {"items": [INCIDENT]}

    @app.get("/api/v1/incidents/{incident_id}")
    def incident(incident_id: IdPath) -> dict[str, Any]:
        if incident_id != INCIDENT["incident_id"]:
            raise DomainError(404, "INCIDENT_NOT_FOUND", "任务不存在。")
        return INCIDENT

    @app.get("/api/v1/strategies")
    def strategies() -> dict[str, Any]:
        return {"items": [STRATEGY]}

    @app.post("/api/v1/runs", status_code=202)
    def create_run(
        body: CreateRun,
        request: Request,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=64)],
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[\x21-\x7e]{8,64}", idempotency_key):
            raise DomainError(422, "INVALID_IDEMPOTENCY_KEY", "幂等键应为可见 ASCII 字符。")
        current = trace.get_current_span().get_span_context()
        with app.state.telemetry.span(
            "run.accept", parent=Context(), links=[Link(current)]
        ) as span:
            trace_id = f"{span.get_span_context().trace_id:032x}"
            return app.state.store.create(body, idempotency_key, trace_id, span_id())  # type: ignore[no-any-return]

    @app.get("/api/v1/runs")
    def runs(
        cursor: Annotated[str, Query(max_length=200)] = "", limit: PageLimit = 20
    ) -> dict[str, Any]:
        return app.state.store.list(cursor, limit)  # type: ignore[no-any-return]

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: IdPath) -> dict[str, Any]:
        return app.state.store.get(run_id)  # type: ignore[no-any-return]

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    def cancel(run_id: IdPath, body: CancelRun) -> dict[str, Any]:
        # Deliberately omit user reason from telemetry and exported evidence.
        return app.state.store.cancel(run_id)  # type: ignore[no-any-return]

    @app.get("/api/v1/runs/{run_id}/events")
    def events(run_id: IdPath, after_seq: AfterSeq = 0, limit: PageLimit = 50) -> dict[str, Any]:
        return app.state.store.page("events", run_id, after_seq, limit)  # type: ignore[no-any-return]

    @app.get("/api/v1/runs/{run_id}/evidence")
    def evidence(run_id: IdPath, after_seq: AfterSeq = 0, limit: PageLimit = 50) -> dict[str, Any]:
        return app.state.store.page("evidence", run_id, after_seq, limit)  # type: ignore[no-any-return]

    @app.get("/api/v1/runs/{run_id}/report")
    def report(run_id: IdPath) -> dict[str, Any]:
        return app.state.store.report(run_id)  # type: ignore[no-any-return]

    @app.get("/api/v1/budget")
    def budget() -> dict[str, Any]:
        return {
            "currency": "CNY",
            "cap_micro_cny": 500000000,
            "admission_cap_micro_cny": 450000000,
            "settled_micro_cny": 0,
            "reserved_micro_cny": 0,
            "uncertain_micro_cny": 0,
            "available_micro_cny": 450000000,
        }

    return app


app = create_app()
