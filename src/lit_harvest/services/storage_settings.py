"""Inspect and change where this instance stores its data."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from lit_harvest.config import AppConfig
from lit_harvest.settings import SettingsStore
from lit_harvest.storage.database import Database


class StorageChangeError(RuntimeError):
    """Raised when a requested storage directory cannot be used."""


@dataclass(slots=True)
class StoragePaths:
    root: str
    papers: str
    database: str
    default_root: str
    is_default: bool
    exists: bool
    writable: bool
    paper_directories: int

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "papers": self.papers,
            "database": self.database,
            "default_root": self.default_root,
            "is_default": self.is_default,
            "exists": self.exists,
            "writable": self.writable,
            "paper_directories": self.paper_directories,
        }


@dataclass(slots=True)
class ValidationResult:
    path: str
    ok: bool
    message: str
    exists: bool
    writable: bool
    empty: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ok": self.ok,
            "message": self.message,
            "exists": self.exists,
            "writable": self.writable,
            "empty": self.empty,
        }


def _writable(directory: Path) -> bool:
    probe = directory / ".lit-harvest-write-test"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


class StorageSettingsService:
    """Owns the storage-directory contract for one instance."""

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database
        self.settings = SettingsStore(config.config_path)

    def describe(self) -> StoragePaths:
        root = self.config.storage.root
        default_root = Path("./data")
        if self.config.config_path is not None:
            default_root = self.config.config_path.parent / "data"
        db_path = self.config.database_path
        papers = root / "papers"
        count = len([item for item in papers.iterdir() if item.is_dir()]) if papers.exists() else 0
        return StoragePaths(
            root=str(root),
            papers=str(papers),
            database=str(db_path) if db_path else self.config.database.url,
            default_root=str(default_root.resolve()),
            is_default=root.resolve() == default_root.resolve(),
            exists=root.exists(),
            writable=_writable(root) if root.exists() else _writable(root.parent),
            paper_directories=count,
        )

    def validate(self, raw_path: str) -> ValidationResult:
        if not raw_path.strip():
            raise StorageChangeError("Please provide a directory path.")
        expanded = Path(raw_path).expanduser()
        if expanded.exists() and expanded.is_file():
            return ValidationResult(
                path=str(expanded),
                ok=False,
                message="That path points to a file, not a directory.",
                exists=True,
                writable=False,
                empty=False,
            )
        parent = expanded.parent if not expanded.exists() else expanded
        writable = _writable(parent)
        exists = expanded.exists()
        empty = not exists or not any(expanded.iterdir())
        if not writable:
            return ValidationResult(
                path=str(expanded),
                ok=False,
                message="This location is not writable. Check permissions or pick another folder.",
                exists=exists,
                writable=False,
                empty=empty,
            )
        return ValidationResult(
            path=str(expanded.resolve()),
            ok=True,
            message="Directory can be used for storage.",
            exists=exists,
            writable=True,
            empty=empty,
        )

    def change(
        self, raw_path: str, *, migrate: bool = True, force: bool = False
    ) -> dict[str, object]:
        """Point this instance at a new storage directory.

        The new location becomes authoritative after a restart. When `migrate`
        is set, existing papers and database rows are copied over (the original
        is left untouched as a safety net).
        """
        target = Path(raw_path).expanduser()
        validation = self.validate(raw_path)
        if not validation.ok:
            raise StorageChangeError(validation.message)

        current_root = self.config.storage.root
        target = target.resolve()
        if target == current_root.resolve():
            raise StorageChangeError("That is already the active storage directory.")

        if target.exists() and any(target.iterdir()) and not force:
            raise StorageChangeError(
                "The target directory is not empty. Enable 'overwrite' to use it anyway."
            )

        copied_papers = 0
        if migrate:
            copied_papers = self._migrate(current_root, target)

        target_db = target / "lit_harvest.db"
        self.settings.update(
            storage_root=str(target),
            database_url=f"sqlite:///{target_db}",
        )
        return {
            "storage_root": str(target),
            "database": f"sqlite:///{target_db}",
            "migrated_papers": copied_papers,
            "restart_required": True,
            "message": (
                "Storage directory updated. Restart the dashboard or CLI for the change "
                "to take effect."
            ),
        }

    def reset_to_default(self, *, migrate: bool = True) -> dict[str, object]:
        default_root = Path(self.describe().default_root)
        self.settings.update(storage_root=None, database_url=None)
        return {
            "storage_root": str(default_root),
            "restart_required": True,
            "message": "Reverted to the default ./data directory. Restart to apply.",
        }

    def _migrate(self, source: Path, target: Path) -> int:
        """Copy papers and the database into the new directory."""
        target.mkdir(parents=True, exist_ok=True)
        copied = 0

        source_papers = source / "papers"
        target_papers = target / "papers"
        if source_papers.exists():
            for item in source_papers.iterdir():
                destination = target_papers / item.name
                if destination.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, destination)
                    copied += 1
                else:
                    shutil.copy2(item, destination)

        source_db = self.config.database_path
        target_db = target / "lit_harvest.db"
        if source_db and source_db.exists():
            self._copy_sqlite(source_db, target_db)
            if source_papers.exists():
                self._rewrite_paths(target_db, source, target)
        return copied

    @staticmethod
    def _copy_sqlite(source: Path, target: Path) -> None:
        """Copy a live SQLite database safely using the online backup API."""
        target.parent.mkdir(parents=True, exist_ok=True)
        source_connection = sqlite3.connect(str(source))
        try:
            target_connection = sqlite3.connect(str(target))
            try:
                source_connection.backup(target_connection)
                target_connection.commit()
            finally:
                target_connection.close()
        finally:
            source_connection.close()

    @staticmethod
    def _rewrite_paths(database_path: Path, old_root: Path, new_root: Path) -> None:
        """Repoint absolute file paths recorded in the copied database."""
        connection = sqlite3.connect(str(database_path))
        try:
            cursor = connection.cursor()
            for table, column in (
                ("downloads", "raw_path"),
                ("papers", "extra_json"),
                ("provider_events", "metadata_json"),
            ):
                cursor.execute(
                    f"SELECT id, {column} FROM {table} WHERE {column} LIKE ?", (f"%{old_root}%",)
                )
                for row_id, value in cursor.fetchall():
                    if not isinstance(value, str):
                        continue
                    updated = value.replace(str(old_root), str(new_root))
                    cursor.execute(
                        f"UPDATE {table} SET {column} = ? WHERE id = ?",  # noqa: S608 - fixed identifiers
                        (updated, row_id),
                    )
            connection.commit()
        finally:
            connection.close()
