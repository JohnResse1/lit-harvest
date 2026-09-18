"""Persistent background worker that executes queued jobs."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from lit_harvest.scheduler.scheduler import Scheduler, SchedulerRunResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerState:
    running: bool = False
    ticks: int = 0
    last_result: dict[str, Any] | None = None


class Worker:
    """Runs the scheduler loop until asked to stop.

    The worker is deliberately a thin loop around `Scheduler.run()` so the CLI,
    the local API, and tests all exercise exactly the same job execution path.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        poll_interval_seconds: float = 2.0,
        max_jobs_per_tick: int = 25,
    ) -> None:
        self.scheduler = scheduler
        self.poll_interval_seconds = max(poll_interval_seconds, 0.1)
        self.max_jobs_per_tick = max(max_jobs_per_tick, 1)
        self.state = WorkerState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._idle_ticks = 0

    def run_once(self, *, max_jobs: int | None = None) -> SchedulerRunResult:
        result = self.scheduler.run(max_jobs=max_jobs or self.max_jobs_per_tick)
        self.state.ticks += 1
        self.state.last_result = {
            "attempted": result.attempted,
            "succeeded": result.succeeded,
            "retried": result.retried,
            "waiting_for_quota": result.waiting_for_quota,
            "failed": result.failed,
            "blocked": result.blocked,
            "stopped_reason": result.stopped_reason,
        }
        if result.attempted:
            logger.info(
                "worker_tick attempted=%s succeeded=%s retried=%s waiting=%s failed=%s",
                result.attempted,
                result.succeeded,
                result.retried,
                result.waiting_for_quota,
                result.failed,
            )
        return result

    def run_forever(self, *, stop_event: threading.Event | None = None) -> None:
        event = stop_event or self._stop_event
        self.state.running = True
        try:
            while not event.is_set():
                if self.scheduler.queue.paused:
                    self._sleep(event)
                    continue
                result = self.run_once()
                if result.attempted == 0:
                    self._idle_ticks += 1
                else:
                    self._idle_ticks = 0
                if result.attempted == 0 or result.waiting_for_quota:
                    self._sleep(event)
        finally:
            self.state.running = False

    def _sleep(self, event: threading.Event) -> None:
        # Back off gently while idle, but stay responsive to resume/stop.
        delay = min(self.poll_interval_seconds * (1 + self._idle_ticks // 5), 15.0)
        event.wait(delay)

    def start(self, *, thread_name: str = "lit-harvest-worker") -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run_forever,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
