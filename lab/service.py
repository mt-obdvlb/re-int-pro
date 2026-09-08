"""Isolated workload API and task process; never imported by the diagnostic Agent."""

import json
import sys
import time
import uuid
from contextlib import asynccontextmanager
from threading import Lock

import redis
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

CACHE = redis.Redis(host="127.0.0.1", port=16379, decode_responses=True)
DSN = "postgresql://probeops:local-lab-only@127.0.0.1:15432/probeops_lab"
PREFIX = "probeops-lab:"
lock = Lock()
metrics = {
    "checkout-api": {"latency_ms": []},
    "database": {"pool_wait_ms": []},
    "cache": {"latency_ms": []},
    "task-worker": {"queue_depth": []},
}
logs = {s: [] for s in metrics}
traces = []


def control():
    return json.loads(CACHE.get(PREFIX + "control") or "{}")


@asynccontextmanager
async def lifespan(app):
    app.state.pool = ConnectionPool(DSN, min_size=2, max_size=2, timeout=2)
    app.state.pool.wait()
    yield
    app.state.pool.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/healthz")
def health():
    CACHE.ping()
    with app.state.pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/checkout")
def checkout():
    cfg = control()
    start = time.perf_counter()
    spans = []
    cstart = time.perf_counter()
    time.sleep(cfg.get("cache_delay", 0))
    CACHE.get(PREFIX + "product")
    cache_ms = (time.perf_counter() - cstart) * 1000
    pstart = time.perf_counter()
    with app.state.pool.connection() as conn:
        wait_ms = (time.perf_counter() - pstart) * 1000
        # Real SQL holds scarce pool connections; other requests actually wait.
        conn.execute("SELECT pg_sleep(%s)", (cfg.get("query_delay", 0.002),))
    db_ms = (time.perf_counter() - pstart) * 1000
    CACHE.rpush(PREFIX + "jobs", str(time.time()))
    depth = CACHE.llen(PREFIX + "jobs")
    # Checkout admission waits briefly when the asynchronous queue is over capacity.
    if depth > 5:
        time.sleep(0.16)
    timeout = cfg.get("request_timeout_ms", 1000)
    invalid = timeout < 100
    duration = (time.perf_counter() - start) * 1000
    trace_id = uuid.uuid4().hex
    spans.extend(
        [
            {"service": "cache", "duration_ms": round(cache_ms, 3)},
            {"service": "database", "duration_ms": round(db_ms, 3)},
            {"service": "task-worker", "duration_ms": 160 if depth > 5 else 0},
        ]
    )
    with lock:
        for service, key, value in [
            ("checkout-api", "latency_ms", duration),
            ("database", "pool_wait_ms", wait_ms),
            ("cache", "latency_ms", cache_ms),
            ("task-worker", "queue_depth", depth),
        ]:
            metrics[service][key].append(round(value, 3))
            metrics[service][key] = metrics[service][key][-120:]
        for condition, service, event in [
            (wait_ms > 80, "database", "pool_wait"),
            (depth > 5, "task-worker", "job_delayed"),
            (cache_ms > 80, "cache", "cache_slow"),
            (invalid, "checkout-api", "config_rejected"),
        ]:
            if condition:
                logs[service].append({"event_type": event, "trace_id": trace_id})
                logs[service] = logs[service][-50:]
        traces.append({"trace_id": trace_id, "duration_ms": round(duration, 3), "spans": spans})
        traces[:] = traces[-50:]
    return {"accepted": not invalid, "trace_id": trace_id}


@app.get("/observations")
def observations():
    with lock:
        # Explicit whitelist; control/labels/injection parameters never leave this endpoint.
        return {
            "metrics": metrics,
            "logs": logs,
            "traces": traces,
            "config": {
                "checkout-api": {"request_timeout_ms": control().get("request_timeout_ms", 1000)}
            },
        }


def worker():
    with ConnectionPool(DSN, min_size=1, max_size=1) as pool:
        while True:
            item = CACHE.blpop(PREFIX + "jobs", timeout=1)
            if item:
                time.sleep(control().get("worker_delay", 0.002))
                with pool.connection() as conn:
                    conn.execute("SELECT 1")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8011, access_log=False, log_level="warning")
