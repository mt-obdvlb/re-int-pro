"""Run the three local services; Ctrl+C stops only processes started by this command."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    processes: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    commands = [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "probeops.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ],
        [sys.executable, "-m", "probeops.worker"],
        ["pnpm", "--dir", "frontend", "dev"],
    ]
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=ROOT, start_new_session=True))
        print("ProbeOps: http://127.0.0.1:5173 | Ctrl+C 停止三个服务", flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                print("一个服务已退出，停止本次启动的其他服务。", file=sys.stderr)
                return 1
            time.sleep(0.3)
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
