"""Bounded local telemetry. User payloads and exception messages are never exported."""

import json
import logging
import logging.config
import logging.handlers
import queue
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Link, SpanContext, Status, StatusCode

context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)
FIELDS = (
    "request_id",
    "run_id",
    "strategy_id",
    "step",
    "duration_ms",
    "outcome",
    "error_code",
    "attempt",
)


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def span_id() -> str:
    return f"{trace.get_current_span().get_span_context().span_id:016x}"


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # No getMessage(), exc_text, locals, request bodies or arbitrary extras.
        value = getattr(record, "safe_fields", {})
        return json.dumps(
            {"time_utc": now(), "level": record.levelname, "logger": record.name, **value},
            ensure_ascii=False,
        )


class SafeQueueHandler(logging.handlers.QueueHandler):
    dropped_logs = 0

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        span = trace.get_current_span().get_span_context()
        fields = {name: (context.get() or {}).get(name) for name in FIELDS}
        # Event names are code-owned identifiers. Unknown library logs become a safe signal.
        event = str(getattr(record, "event_name", "library_event"))
        fields.update(
            event_name=event if re.fullmatch(r"[a-z_.]{1,80}", event) else "event",
            trace_id=f"{span.trace_id:032x}" if span.is_valid else None,
            span_id=f"{span.span_id:016x}" if span.is_valid else None,
        )
        clean = logging.LogRecord(record.name, record.levelno, "", 0, "", (), None)
        clean.safe_fields = fields  # type: ignore[attr-defined]
        return clean

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_logs += 1
            if record.levelno >= logging.ERROR:
                import sys

                sys.stderr.write('{"event_name":"logging_queue_full","level":"ERROR"}\n')


class ExportFileHandler(logging.handlers.RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # Unlike application logging, exporters must report failed writes to the SDK.
        raise OSError("Local trace export failed") from None


class LocalSpanExporter(SpanExporter):
    def __init__(self, path: Path):
        self.handler = ExportFileHandler(path, maxBytes=10_000_000, backupCount=5)
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.failed_exports = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            for span in spans:
                ctx = span.get_span_context()
                assert ctx is not None
                data = {
                    "name": span.name,
                    "trace_id": f"{ctx.trace_id:032x}",
                    "span_id": f"{ctx.span_id:016x}",
                    "parent_span_id": f"{span.parent.span_id:016x}" if span.parent else None,
                    "start_time": span.start_time,
                    "end_time": span.end_time,
                    "status": span.status.status_code.name,
                    "attributes": dict(span.attributes or {}),
                    "links": [
                        {
                            "trace_id": f"{link.context.trace_id:032x}",
                            "span_id": f"{link.context.span_id:016x}",
                        }
                        for link in span.links
                    ],
                }
                self.handler.emit(logging.LogRecord("spans", 20, "", 0, json.dumps(data), (), None))
            return SpanExportResult.SUCCESS
        except Exception:
            self.failed_exports += 1
            logging.getLogger(__name__).error("", extra={"event_name": "telemetry_degraded"})
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self.handler.close()


class Telemetry:
    def __init__(self, directory: Path, role: str, level: str = "INFO"):
        directory.mkdir(parents=True, exist_ok=True)
        self.provider = TracerProvider(
            resource=Resource.create({"service.name": f"probeops-{role}"})
        )
        self.exporter = LocalSpanExporter(directory / f"{role}-spans.jsonl")
        self.provider.add_span_processor(
            BatchSpanProcessor(
                self.exporter,
                max_queue_size=2048,
                max_export_batch_size=128,
                schedule_delay_millis=200,
            )
        )
        self.tracer = self.provider.get_tracer("probeops")
        self.queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=2048)
        self.handler = SafeQueueHandler(self.queue)
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "handlers": {},
                "root": {"level": level, "handlers": []},
            }
        )
        logging.getLogger().addHandler(self.handler)
        file = logging.handlers.RotatingFileHandler(
            directory / f"{role}.jsonl", maxBytes=10_000_000, backupCount=5
        )
        stdout = logging.StreamHandler()
        for handler in (file, stdout):
            handler.setFormatter(SafeFormatter())
        self.sinks = (file, stdout)
        self.listener = logging.handlers.QueueListener(self.queue, *self.sinks)
        self.listener.start()

    @contextmanager
    def span(
        self, name: str, *, parent: Any = None, links: list[Link] | None = None, **attributes: Any
    ) -> Iterator[trace.Span]:
        start = time.monotonic()
        token = context.set(
            {
                **(context.get() or {}),
                **{key: value for key, value in attributes.items() if key in FIELDS},
            }
        )
        with self.tracer.start_as_current_span(
            name,
            context=parent,
            links=links,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException as exc:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                log("operation_failed", error_code=type(exc).__name__, outcome="error")
                raise
            finally:
                log("operation_finished", duration_ms=round((time.monotonic() - start) * 1000, 2))
                context.reset(token)

    def close(self) -> None:
        self.provider.force_flush(timeout_millis=5000)
        self.provider.shutdown()
        logging.getLogger().removeHandler(self.handler)
        # Drain before inserting QueueListener's sentinel, even after a burst.
        self.queue.join()
        self.listener.stop()
        for handler in self.sinks:
            handler.close()


def log(event: str, **fields: Any) -> None:
    token = context.set({**(context.get() or {}), **fields})
    try:
        logging.getLogger("probeops").info("", extra={"event_name": event})
    finally:
        context.reset(token)


def remote_context(trace_id: str, parent_span_id: str) -> Any:
    span = trace.NonRecordingSpan(
        SpanContext(
            trace_id=int(trace_id, 16),
            span_id=int(parent_span_id, 16),
            is_remote=True,
            trace_flags=trace.TraceFlags(1),
        )
    )
    return trace.set_span_in_context(span)
