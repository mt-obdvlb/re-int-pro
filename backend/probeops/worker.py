import asyncio
import contextlib
import signal

from opentelemetry import trace

from .agent import diagnose
from .config import settings
from .engine import diagnose_snapshot
from .models import DomainError
from .storage import Store, uid
from .telemetry import Telemetry, log, remote_context


async def execute(store: Store, owner: str, delay: float) -> bool:
    claimed = store.claim(owner)
    if claimed is None:
        return False
    run, parent = claimed

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(5)
            if not store.heartbeat(run["run_id"], owner):
                log("worker_lease_lost", error_code="LEASE_LOST")
                task.cancel()
                return

    with store.telemetry.span(
        "diagnosis.run",
        parent=remote_context(run["trace_id"], parent),
        run_id=run["run_id"],
        strategy_id=run["strategy_id"],
        dataset_version=run["dataset_version"],
        config_hash=run["config_hash"],
    ):
        workflow = diagnose if run["model"] == "FakeLLM-v1" else diagnose_snapshot
        task = asyncio.create_task(workflow(store, run, owner, delay))
        pulse = asyncio.create_task(heartbeat())

        async def cancel_watch() -> None:
            while not task.done():
                await asyncio.sleep(0.1)
                if store.get(run["run_id"])["status"] == "cancel_requested":
                    task.cancel()
                    return

        watcher = asyncio.create_task(cancel_watch())
        try:
            await asyncio.wait_for(task, timeout=run["limits"]["max_wall_seconds"])
            log("run_finished", outcome=store.get(run["run_id"])["status"])
        except TimeoutError:
            store.advance(
                run["run_id"],
                owner,
                "run_finished",
                "达到总运行时间上限。",
                updates={"status": "completed", "stop_reason": "deadline"},
            )
        except (Exception, asyncio.CancelledError) as exc:
            # Never format provider exceptions; only type and controlled reason.
            log(
                "worker_failed",
                error_code=exc.code if isinstance(exc, DomainError) else type(exc).__name__,
                outcome="error",
            )
            trace.get_current_span().set_status(trace.StatusCode.ERROR)
            try:
                store.advance(
                    run["run_id"],
                    owner,
                    "run_finished",
                    "worker 执行中断。",
                    updates={"status": "failed", "stop_reason": "dependency_error"},
                )
            except DomainError:
                log("worker_lease_lost", error_code="LEASE_LOST")
            if (
                isinstance(exc, asyncio.CancelledError)
                and store.get(run["run_id"])["status"] != "cancelled"
            ):
                raise
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
    return True


async def serve() -> None:
    config = settings()
    telemetry = Telemetry(
        config.probeops_telemetry_dir, "worker", config.log_level, config.otlp_endpoint
    )
    store = Store(config.probeops_db_path, telemetry, config)
    owner = uid("worker")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log("worker_started")
    try:
        while not stop.is_set():
            try:
                recovered = store.recover()
                if recovered:
                    log("worker_recovered", outcome="worker_lost")
                if not await execute(store, owner, config.fake_delay_seconds):
                    await asyncio.sleep(0.4)
            except Exception as exc:
                log("worker_loop_error", error_code=type(exc).__name__)
                await asyncio.sleep(1)
    finally:
        log("worker_stopped")
        telemetry.close()


if __name__ == "__main__":
    asyncio.run(serve())
