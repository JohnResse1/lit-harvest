"""Queue control state that can be paused and resumed safely."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class QueueControl:
    paused: bool = False
    reason: str | None = None

    def pause(self, reason: str | None = None) -> None:
        self.paused = True
        self.reason = reason

    def resume(self) -> None:
        self.paused = False
        self.reason = None
