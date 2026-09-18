"""Secret storage backends for provider credentials.

The default backend is a permission-restricted file inside the project at
``.lit-harvest/secrets.json``. An operating-system keyring (macOS Keychain)
remains available for users who explicitly choose it.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from lit_harvest.storage.files import atomic_write_json

DEFAULT_KEYRING_PREFIX = "lit-harvest"


def default_secret_ref(provider: str, name: str) -> str:
    """Return the project-local secret reference used by `auth set`."""
    return f"file:{provider}:{name}"


def parse_secret_ref(ref: str) -> tuple[str, str, str]:
    scheme, separator, remainder = ref.partition(":")
    if not separator or not remainder:
        raise ValueError(
            f"Invalid secret reference {ref!r}. "
            "Use file:provider:name, keychain:service:account, or env:NAME."
        )
    if scheme == "env":
        return scheme, remainder, ""
    if scheme == "file":
        return scheme, remainder, ""
    if scheme != "keychain":
        raise ValueError(f"Unsupported secret reference scheme: {scheme}")
    service, separator, account = remainder.partition(":")
    if not separator or not service or not account:
        raise ValueError(f"Invalid keychain reference {ref!r}. Expected keychain:service:account.")
    return scheme, service, account


@dataclass(slots=True)
class SecretLocation:
    backend: str
    available: bool
    detail: str


class SecretStore:
    """Resolve/store secrets without ever placing plaintext in SQLite or config."""

    def __init__(self, *, project_root: Path | None = None, home: Path | None = None):
        configured_home = os.getenv("LIT_HARVEST_HOME")
        if configured_home:
            selected_home = Path(configured_home).expanduser()
        elif home is not None:
            selected_home = home
        else:
            selected_home = (project_root or Path.cwd()) / ".lit-harvest"
        self.home = selected_home
        self.file_path = self.home / "secrets.json"
        backend = os.getenv("LIT_HARVEST_SECRET_BACKEND", "").lower()
        self.force_file_backend = backend != "keychain"

    def exists(self, ref: str) -> bool:
        try:
            return self.get(ref) is not None
        except (KeyringError, OSError, ValueError):
            return False

    def get(self, ref: str) -> str | None:
        scheme, first, second = parse_secret_ref(ref)
        if scheme == "env":
            value = os.getenv(first)
            return value or None
        if scheme == "file":
            return self._read_file().get(ref) or self._read_file().get(first)
        value = self._read_keyring(first, second)
        if value is not None:
            return value
        return self._read_file().get(ref)

    def set(self, ref: str, secret: str) -> SecretLocation:
        scheme, first, second = parse_secret_ref(ref)
        if scheme == "env":
            raise ValueError("Environment-variable references cannot be written by this command")
        if scheme == "file":
            self._write_file_entry(ref, secret)
            return SecretLocation("project-file", True, str(self.file_path))
        if not self.force_file_backend and self._keyring_available():
            try:
                self._write_keyring(first, second, secret)
                return SecretLocation("keychain", True, f"{first}/{second}")
            except KeyringError as exc:
                self._write_file_entry(ref, secret)
                return SecretLocation("file-fallback", True, f"{self.file_path} ({exc})")
        self._write_file_entry(ref, secret)
        return SecretLocation(
            "project-file",
            True,
            str(self.file_path),
        )

    def delete(self, ref: str) -> bool:
        scheme, first, second = parse_secret_ref(ref)
        if scheme == "env":
            return False
        if scheme == "file":
            return self._delete_file_entry(ref)
        removed = False
        if not self.force_file_backend and self._keyring_available():
            try:
                self._delete_keyring(first, second)
                removed = True
            except PasswordDeleteError:
                pass
            except KeyringError:
                pass
        removed = self._delete_file_entry(ref) or removed
        return removed

    def backend_status(self) -> SecretLocation:
        if self.force_file_backend:
            return SecretLocation("project-file", True, str(self.file_path))
        if self._keyring_available():
            try:
                name = keyring.get_keyring().__class__.__name__
            except Exception as exc:  # noqa: BLE001 - backend diagnostics only
                return SecretLocation("file-fallback", True, f"{self.file_path} ({exc})")
            return SecretLocation("keychain", True, name)
        return SecretLocation("project-file", True, str(self.file_path))

    def _keyring_available(self) -> bool:
        return not self.force_file_backend

    @staticmethod
    def _read_keyring(service: str, account: str) -> str | None:
        try:
            return keyring.get_password(service, account)
        except KeyringError:
            return None

    @staticmethod
    def _write_keyring(service: str, account: str, secret: str) -> None:
        keyring.set_password(service, account, secret)

    @staticmethod
    def _delete_keyring(service: str, account: str) -> None:
        keyring.delete_password(service, account)

    def _ensure_file_permissions(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.home.chmod(stat.S_IRWXU)

    def _read_file(self) -> dict[str, str]:
        if not self.file_path.exists():
            return {}
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def _write_file_entry(self, key: str, secret: str) -> None:
        self._ensure_file_permissions()
        payload = self._read_file()
        payload[key] = secret
        atomic_write_json(self.file_path, payload)
        with contextlib.suppress(OSError):
            self.file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _delete_file_entry(self, key: str) -> bool:
        payload = self._read_file()
        if key not in payload:
            return False
        del payload[key]
        if payload:
            atomic_write_json(self.file_path, payload)
            with contextlib.suppress(OSError):
                self.file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        else:
            with contextlib.suppress(FileNotFoundError):
                self.file_path.unlink()
        return True
