"""Filesystem-safe document storage with atomic writes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DOI_PREFIX = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/|doi\.org/)", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    normalized = _DOI_PREFIX.sub("", value.strip())
    normalized = normalized.rstrip(".,;)]}")
    return normalized.lower()


def filesystem_safe_doi(doi: str) -> str:
    normalized = normalize_doi(doi)
    safe = _UNSAFE.sub("_", normalized).strip("._")
    if not safe:
        raise ValueError(f"DOI cannot be converted to a safe path: {doi!r}")
    return safe


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class DocumentStorage:
    """Owns the raw/normalized/state layout for a paper."""

    def __init__(self, root: Path):
        self.root = root

    def paper_dir(self, doi: str) -> Path:
        return self.root / "papers" / filesystem_safe_doi(doi)

    def raw_dir(self, doi: str) -> Path:
        return self.paper_dir(doi) / "raw"

    def normalized_dir(self, doi: str) -> Path:
        return self.paper_dir(doi) / "normalized"

    def state_path(self, doi: str) -> Path:
        return self.paper_dir(doi) / "state.json"

    def write_raw(self, doi: str, filename: str, content: bytes) -> Path:
        safe_name = _UNSAFE.sub("_", filename)
        path = self.raw_dir(doi) / safe_name
        atomic_write_bytes(path, content)
        return path

    def read_raw(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_normalized(self, doi: str, document: dict[str, Any]) -> Path:
        path = self.normalized_dir(doi) / "paper.json"
        atomic_write_json(path, document)
        return path

    def read_normalized(self, doi: str) -> dict[str, Any] | None:
        path = self.normalized_dir(doi) / "paper.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Normalized document must be an object: {path}")
        return payload

    def write_state(self, doi: str, state: dict[str, Any]) -> Path:
        path = self.state_path(doi)
        atomic_write_json(path, state)
        return path

    def read_state(self, doi: str) -> dict[str, Any]:
        path = self.state_path(doi)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Normalized document must be an object: {path}")
        return payload

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "papers").mkdir(exist_ok=True)

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self.ensure_layout()
            probe = self.root / ".write_probe"
            atomic_write_text(probe, "ok")
            probe.unlink()
        except OSError as exc:
            return False, str(exc)
        return True, str(self.root.resolve())
