"""Local instance identity and loopback safety checks."""

from __future__ import annotations

import getpass
import socket
import uuid
from pathlib import Path

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_loopback(host: str) -> bool:
    """True only for addresses reachable exclusively from this machine.

    `0.0.0.0` and `::` deliberately return False: they bind every interface and
    would expose the unauthenticated dashboard to the local network.
    """
    normalized = host.strip().lower()
    if normalized in LOOPBACK_HOSTS:
        return True
    return normalized.startswith("127.")


def instance_id(project_root: Path) -> str:
    """Stable per-machine instance identifier, stored outside Git tracking."""
    state_dir = project_root / ".lit-harvest"
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = state_dir / "instance_id"
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = uuid.uuid4().hex
    marker.write_text(value + "\n", encoding="utf-8")
    return value


def local_identity(project_root: Path) -> dict[str, str]:
    return {
        "instance_id": instance_id(project_root),
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "project": str(project_root),
    }
