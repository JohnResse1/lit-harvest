"""Secret leakage detection for open-source publication and CI."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Elsevier API key assignment",
        re.compile(
            r"(?i)(?:X-ELS-APIKey|api[_-]?key|secret)[\"'\s:=]+"
            r"([0-9a-f]{32})\b"
        ),
    ),
    (
        "OpenAI-style key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "data",
    ".lit-harvest",
    "work",
    "outputs",
}
SKIP_SUFFIXES = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
}
PROTECTED_PATHS = {
    ".lit-harvest",
    "config.yaml",
    ".env",
    "secrets.json",
}


@dataclass(slots=True)
class SecurityFinding:
    path: str
    line: int | None
    kind: str
    message: str
    severity: str = "high"


@dataclass(slots=True)
class SecurityReport:
    findings: list[SecurityFinding] = field(default_factory=list)
    scanned_files: int = 0
    tracked_secret_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings and not self.tracked_secret_files

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "scanned_files": self.scanned_files,
            "tracked_secret_files": self.tracked_secret_files,
            "findings": [
                {
                    "path": item.path,
                    "line": item.line,
                    "kind": item.kind,
                    "message": item.message,
                    "severity": item.severity,
                }
                for item in self.findings
            ],
        }


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _tracked_files(root: Path) -> list[Path] | None:
    output = _git(root, "ls-files")
    if output is None:
        return None
    return [root / line for line in output.splitlines() if line.strip()]


def _visible_untracked_files(root: Path) -> list[Path] | None:
    output = _git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if output is None:
        return None
    return [root / line for line in output.splitlines() if line.strip()]


def _is_protected(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in PROTECTED_PATHS:
        return True
    if relative.name in PROTECTED_PATHS:
        return True
    return relative.suffix in {".pem", ".key", ".p12", ".pfx"}


def _iter_candidate_files(root: Path, tracked: list[Path] | None) -> list[Path]:
    if tracked is not None and tracked:
        return tracked
    visible = _visible_untracked_files(root)
    if visible is not None:
        return visible
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        candidates.append(path)
    return candidates


def scan_repository(root: str | Path = ".") -> SecurityReport:
    root_path = Path(root).expanduser().resolve()
    report = SecurityReport()
    tracked = _tracked_files(root_path)

    if tracked is not None:
        for path in tracked:
            try:
                relative = path.relative_to(root_path)
            except ValueError:
                continue
            if _is_protected(relative):
                report.tracked_secret_files.append(str(relative))

    for path in _iter_candidate_files(root_path, tracked):
        try:
            relative = path.relative_to(root_path)
        except ValueError:
            relative = path
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        report.scanned_files += 1
        for line_number, line in enumerate(content.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                if not pattern.search(line):
                    continue
                # Ignore obvious placeholders and documentation examples.
                lowered = line.lower()
                if any(
                    marker in lowered
                    for marker in (
                        "example",
                        "placeholder",
                        "replace-with",
                        "your-own",
                        "your_own",
                        "redacted",
                        "not-real",
                        "xxx",
                    )
                ):
                    continue
                if (
                    relative.parts
                    and relative.parts[0] == "tests"
                    and "test_security_scan" in relative.name
                ):
                    continue
                report.findings.append(
                    SecurityFinding(
                        path=str(relative),
                        line=line_number,
                        kind=kind,
                        message=f"Possible {kind} detected",
                    )
                )
    return report
