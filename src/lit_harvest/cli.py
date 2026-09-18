"""Typer CLI wired exclusively through the shared service layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from lit_harvest import __version__
from lit_harvest.config import load_config
from lit_harvest.credentials.store import SecretStore, default_secret_ref
from lit_harvest.models import JobStatus
from lit_harvest.security import scan_repository
from lit_harvest.services.container import ServiceContainer

app = typer.Typer(
    name="lit-harvest",
    help="Local-first literature discovery, acquisition, and normalization.",
    no_args_is_help=True,
)
console = Console()
auth_app = typer.Typer(help="Manage provider credentials without exporting secrets.")
app.add_typer(auth_app, name="auth")


def _container(config_path: str | None) -> ServiceContainer:
    return ServiceContainer(load_config(config_path))


def _print_json(payload: Any) -> None:
    console.print_json(json.dumps(payload, default=str))


@app.callback()
def main() -> None:
    """Local-first literature discovery, acquisition, and normalization."""


@app.command()
def version() -> None:
    """Show the installed version."""
    console.print(__version__)


@auth_app.command("set")
def auth_set(
    provider: Annotated[
        str, typer.Argument(help="Provider name, for example elsevier.")
    ] = "elsevier",
    name: Annotated[
        str, typer.Argument(help="Credential label from config.yaml.")
    ] = "university_primary",
    secret_ref: Annotated[
        str | None,
        typer.Option(
            "--secret-ref",
            help=(
                "Override the destination, e.g. file:elsevier:primary or keychain:service:account."
            ),
        ),
    ] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Store a credential secret in the project's private secret file."""
    import getpass

    loaded = load_config(config)
    project_root = loaded.config_path.parent if loaded.config_path else Path.cwd()
    store = SecretStore(project_root=project_root)
    selected_ref = secret_ref or default_secret_ref(provider, name)
    # Validate that the reference is well-formed before prompting.
    try:
        store.get(selected_ref)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    secret = getpass.getpass(f"API key for {provider}/{name}: ")
    if not secret.strip():
        raise typer.BadParameter("Secret cannot be empty")
    location = store.set(selected_ref, secret.strip())
    configured = any(
        item.name == name and item.resolved_secret_ref == selected_ref
        for item in loaded.providers.elsevier.credentials
    )
    hint = "" if configured else "\nAdd this secret_ref to config.yaml for the credential entry."
    console.print(
        f"Stored [bold]{provider}/{name}[/bold] in {location.backend}: {location.detail}{hint}"
    )


@auth_app.command("list")
def auth_list(
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """List configured credentials and whether their secrets are available."""
    loaded = load_config(config)
    project_root = loaded.config_path.parent if loaded.config_path else Path.cwd()
    container = ServiceContainer(loaded)
    table = Table(title="Configured credentials")
    table.add_column("Provider")
    table.add_column("Name")
    table.add_column("Secret ref")
    table.add_column("Available")
    table.add_column("Backend")
    store = SecretStore(project_root=project_root)
    seen: set[tuple[str, str]] = set()
    for item in container.database.list_credentials():
        key = (item["provider"], item["name"])
        if key in seen:
            continue
        seen.add(key)
        try:
            available = store.exists(item["secret_ref"])
        except ValueError:
            available = False
        table.add_row(
            item["provider"],
            item["name"],
            item["secret_ref"],
            "yes" if available else "no",
            store.backend_status().backend,
        )
    console.print(table)


@auth_app.command("remove")
def auth_remove(
    provider: Annotated[str, typer.Argument()] = "elsevier",
    name: Annotated[str, typer.Argument()] = "university_primary",
    secret_ref: Annotated[str | None, typer.Option("--secret-ref")] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Remove a stored secret."""
    loaded = load_config(config)
    project_root = loaded.config_path.parent if loaded.config_path else Path.cwd()
    selected_ref = secret_ref or default_secret_ref(provider, name)
    if SecretStore(project_root=project_root).delete(selected_ref):
        console.print(f"Removed {provider}/{name}")
    else:
        console.print(f"No stored secret found for {provider}/{name}")


@auth_app.command("test")
def auth_test(
    provider: Annotated[str, typer.Argument()] = "elsevier",
    name: Annotated[str, typer.Argument()] = "university_primary",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Reachability-test the selected credential without printing it."""
    result = _container(config).doctor(network=True)
    matching = [item for item in result["credentials"] if item["name"] == name]
    if not matching:
        raise typer.BadParameter(f"Credential not found in config: {provider}/{name}")
    credential = matching[0]
    if not credential["detected"]:
        console.print("Credential secret is not available")
        raise typer.Exit(code=1)
    for item in result["providers"]:
        console.print(f"{item['service']}: {item['status']} — {item['message']}")
    if not result["ok"]:
        raise typer.Exit(code=1)


security_app = typer.Typer(help="Prevent accidental API-key publication.")
app.add_typer(security_app, name="security")


@security_app.command("scan")
def security_scan(
    root: Annotated[str, typer.Argument(help="Repository root to scan.")] = ".",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Scan tracked files for leaked keys and protected files."""
    report = scan_repository(root)
    if json_output:
        _print_json(report.to_dict())
    else:
        table = Table(title="Credential leak scan")
        table.add_column("Status")
        table.add_column("File")
        table.add_column("Line")
        table.add_column("Finding")
        if report.ok:
            table.add_row("OK", "-", "-", f"Scanned {report.scanned_files} files")
        for tracked_path in report.tracked_secret_files:
            table.add_row("TRACKED SECRET", tracked_path, "-", "Protected path is tracked by Git")
        for finding in report.findings:
            table.add_row("LEAK?", finding.path, str(finding.line or "-"), finding.message)
        console.print(table)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def doctor(
    config: Annotated[str | None, typer.Option("--config", help="Path to config.yaml.")] = None,
    network: Annotated[
        bool, typer.Option("--network", help="Perform live provider reachability checks.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """Check credentials, providers, quotas, SQLite, and storage."""
    result = _container(config).doctor(network=network)
    if json_output:
        _print_json(result)
        if not result["ok"]:
            raise typer.Exit(code=1)
        return
    table = Table(title="Literature Harvester diagnostics")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    table.add_row(
        "SQLite",
        "OK" if result["database"]["ok"] else "FAIL",
        str(result["database"]["message"]),
    )
    table.add_row(
        "Storage",
        "OK" if result["storage"]["ok"] else "FAIL",
        str(result["storage"]["message"]),
    )
    credentials = result["credentials"]
    detected = sum(1 for item in credentials if item["detected"])
    table.add_row(
        "Elsevier credential",
        "OK" if detected else "MISSING",
        f"{detected} credential(s) detected",
    )
    for item in result["providers"]:
        table.add_row(
            f"{item['provider']} / {item['service']}",
            str(item["status"]),
            str(item["message"]),
        )
    for quota in result["quotas"]:
        remaining = quota.get("remaining")
        limit = quota.get("limit")
        table.add_row(
            f"Quota / {quota['service']}",
            str(quota["status"]),
            (
                f"{remaining if remaining is not None else '?'} / "
                f"{limit if limit is not None else '?'}"
            ),
        )
    console.print(table)
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command()
def search(
    query: Annotated[str, typer.Option("--query", "-q", help="Scopus query expression.")],
    max_results: Annotated[
        int, typer.Option("--max-results", min=1, help="Maximum papers to discover.")
    ] = 100,
    start_year: Annotated[int | None, typer.Option("--start-year")] = None,
    end_year: Annotated[int | None, typer.Option("--end-year")] = None,
    export: Annotated[
        str | None, typer.Option("--export", help="Optional CSV/JSON/JSONL export path.")
    ] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Discover papers with Scopus Search STANDARD and store them locally."""
    result = _container(config).acquisition.search(
        query,
        max_results=max_results,
        start_year=start_year,
        end_year=end_year,
        export=export,
    )
    _print_json(
        {
            "query": result.query,
            "discovered": result.discovered,
            "stored": result.stored,
            "pages": result.pages,
            "total_results": result.total_results,
            "raw_paths": result.raw_paths,
        }
    )


@app.command()
def fetch(
    source: Annotated[str, typer.Argument(help="DOI or path to .csv/.tsv/.txt/.json/.jsonl.")],
    doi_column: Annotated[
        str, typer.Option("--doi-column", help="DOI column for CSV/TSV/JSON input.")
    ] = "doi",
    pdf: Annotated[
        bool | None,
        typer.Option("--pdf/--no-pdf", help="Also download the publisher PDF when entitled."),
    ] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Queue and retrieve full text for one DOI or a DOI list."""
    container = _container(config)
    path = Path(source)
    if path.exists() and path.is_file():
        imported = container.acquisition.import_dois(path, doi_column=doi_column)
        _print_json(
            {
                "queued": imported.queued,
                "duplicates": imported.duplicates,
                "invalid": imported.invalid,
            }
        )
        run = container.scheduler.run(max_jobs=imported.queued or 0)
        _print_json(run)
        return
    fetched = container.acquisition.fetch_now(source)
    payload: dict[str, Any] = {
        "paper_id": fetched.paper_id,
        "doi": fetched.doi,
        "raw_path": fetched.raw_path,
        "normalized_path": fetched.normalized_path,
        "reused": fetched.reused,
    }
    if container.acquisition.pdf_enabled(pdf):
        try:
            payload["pdf"] = container.acquisition.fetch_pdf(fetched.paper_id)
        except Exception as exc:  # noqa: BLE001 - XML success must remain usable
            payload["pdf_error"] = {"code": getattr(exc, "code", "pdf_failed"), "message": str(exc)}
    _print_json(payload)


@app.command()
def parse(
    limit: Annotated[int, typer.Option("--limit", min=1)] = 1000,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-normalize papers that already have normalized output."),
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Normalize downloaded raw documents that are not yet parsed."""
    _print_json(_container(config).acquisition.parse_pending(limit=limit, force=force))


@app.command()
def export(
    path: Annotated[str, typer.Argument(help="Destination .csv, .json, or .jsonl path.")],
    format: Annotated[str | None, typer.Option("--format")] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Export the local paper registry."""
    target = _container(config).papers.export(path, format=format)
    console.print(str(target))


@app.command()
def jobs(
    status: Annotated[str | None, typer.Option("--status")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """List jobs."""
    selected = JobStatus(status) if status else None
    rows = _container(config).database.list_jobs(limit=limit, status=selected)
    _print_json([row.model_dump(mode="json") for row in rows])


@app.command()
def quota(config: Annotated[str | None, typer.Option("--config")] = None) -> None:
    """Show persisted provider/service/credential quota state."""
    rows = _container(config).database.list_quotas()
    _print_json([row.model_dump(mode="json") for row in rows])


@app.command()
def pause(
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Pause the local queue."""
    _container(config).maintenance.pause(reason)
    console.print("Queue paused")


@app.command()
def resume(config: Annotated[str | None, typer.Option("--config")] = None) -> None:
    """Resume the local queue."""
    _container(config).maintenance.resume()
    console.print("Queue resumed")


@app.command()
def retry(
    job_id: Annotated[str | None, typer.Option("--job-id")] = None,
    transient: Annotated[
        bool, typer.Option("--transient", help="Retry all transient failures.")
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Retry one job or all transient failures."""
    maintenance = _container(config).maintenance
    if transient:
        _print_json(maintenance.retry_transient())
    elif job_id:
        _print_json(maintenance.retry_job(job_id))
    else:
        raise typer.BadParameter("Provide --job-id or --transient")


@app.command()
def ui(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Launch the local FastAPI dashboard."""
    import uvicorn

    from lit_harvest.api.app import create_app

    loaded = load_config(config)
    selected_host = host or loaded.server.host
    selected_port = port or loaded.server.port
    if selected_host not in {"127.0.0.1", "localhost", "::1"}:
        console.print(
            "[yellow]Warning: binding outside localhost exposes the UI without "
            "authentication.[/yellow]"
        )
    uvicorn.run(create_app(loaded), host=selected_host, port=selected_port)


if __name__ == "__main__":
    app()
