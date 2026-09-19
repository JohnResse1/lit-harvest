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
from lit_harvest.utils.instance import is_loopback, local_identity

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


def _fail(title: str, detail: str, *, hint: str | None = None, code: int = 1) -> None:
    """Print an actionable message instead of a Python traceback."""
    console.print(f"[bold red]{title}[/bold red]")
    console.print(detail)
    if hint:
        console.print()
        console.print(f"[bold]What to do:[/bold] {hint}")
    raise typer.Exit(code=code)


def _explain(exc: Exception) -> None:
    """Map internal exceptions to plain-language guidance for end users."""
    from lit_harvest.credentials.manager import CredentialUnavailableError
    from lit_harvest.providers.base import (
        AuthenticationError,
        EntitlementError,
        NotFoundError,
        ProviderError,
    )

    if isinstance(exc, CredentialUnavailableError):
        _fail(
            "No Elsevier API key is configured yet.",
            "This tool talks to Elsevier, so it must have your own API key before it can work.\n"
            "Nothing was downloaded and no data was changed.",
            hint=(
                "Run:  lit-harvest auth set elsevier university_primary\n"
                "Then: lit-harvest doctor --network\n"
                "See the Quick Start in README.md if you are unsure how to get a key."
            ),
        )
    if isinstance(exc, AuthenticationError):
        _fail(
            "Elsevier rejected your API key.",
            "The stored key is invalid, expired, or not enabled for this API.",
            hint=(
                "Store the key again:  lit-harvest auth set elsevier university_primary\n"
                "Check the key in the Elsevier Developer Portal."
            ),
        )
    if isinstance(exc, EntitlementError):
        _fail(
            "Your account is not entitled to this content.",
            "The API key works, but your institution or account cannot access this article.",
            hint="This is an access-rights limit, not a bug. Try another DOI you are entitled to.",
        )
    if isinstance(exc, NotFoundError):
        _fail(
            "Elsevier could not find this DOI.",
            "The article may not exist, may be withdrawn, or may not be in ScienceDirect.",
            hint="Double-check the DOI string.",
        )
    if isinstance(exc, ProviderError):
        _fail(
            "The publisher request failed.",
            str(exc),
            hint="Retry later, or run: lit-harvest doctor --network",
        )
    if isinstance(exc, FileNotFoundError):
        _fail("File not found.", str(exc), hint="Check the path and try again.")
    if isinstance(exc, ValueError):
        _fail("That input was not valid.", str(exc), hint="Fix the value and try again.")


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


policy_app = typer.Typer(help="Inspect and adjust usage pacing for shared subscriptions.")
app.add_typer(policy_app, name="policy")

storage_app = typer.Typer(help="Choose where papers and the database are stored.")
app.add_typer(storage_app, name="storage")

security_app = typer.Typer(help="Prevent accidental API-key publication.")
app.add_typer(security_app, name="security")


@policy_app.command("show")
def policy_show(
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Show pacing rules and how much of today's allowance is used."""
    container = _container(config)
    table = Table(title="Usage policy")
    table.add_column("Provider")
    table.add_column("Service")
    table.add_column("Used today")
    table.add_column("Daily cap")
    table.add_column("Min interval")
    service_map = [
        ("article_retrieval", "Full text"),
        ("article_pdf", "PDF"),
        ("scopus_search", "Search"),
        ("works_search", "Search"),
    ]
    for provider in container.config.providers.names():
        policy = container.policy.policy_for(provider)
        registered = container.providers.get(provider)
        # Only show services this provider actually offers.
        for service, label in service_map:
            if service == "scopus_search" and not getattr(registered, "supports_fulltext", False):
                continue
            if service == "works_search" and getattr(registered, "supports_fulltext", False):
                continue
            if service in {"article_retrieval", "article_pdf"} and not getattr(
                registered, "supports_fulltext", False
            ):
                continue
            limit = policy.daily_limit(service)
            used = container.policy.usage_today(provider, service)
            interval = policy.min_interval(service)
            table.add_row(
                provider,
                label,
                str(used),
                "unlimited" if limit is None else str(limit),
                f"{interval:g}s",
            )
    console.print(table)
    console.print(
        "[dim]These caps protect shared institutional access. Raise them only with "
        "written authorization from your library or publisher.[/dim]"
    )


@storage_app.command("show")
def storage_show(
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Show the active storage directory."""
    paths = _container(config).storage_settings.describe()
    table = Table(title="Storage")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Root", paths.root)
    table.add_row("Papers", paths.papers)
    table.add_row("Database", paths.database)
    table.add_row("Default", paths.default_root)
    table.add_row("Using default", "yes" if paths.is_default else "no")
    table.add_row("Writable", "yes" if paths.writable else "no")
    table.add_row("Paper folders", str(paths.paper_directories))
    console.print(table)


@storage_app.command("set")
def storage_set(
    path: Annotated[str, typer.Argument(help="Directory to store papers and the database.")],
    migrate: Annotated[
        bool,
        typer.Option("--migrate/--no-migrate", help="Copy existing data to the new directory."),
    ] = True,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Allow a non-empty target directory.")
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Point this instance at a new storage directory."""
    service = _container(config).storage_settings
    try:
        result = service.change(path, migrate=migrate, force=overwrite)
    except Exception as exc:  # noqa: BLE001 - translated to guidance
        _explain(exc)
        return
    _print_json(result)
    console.print("[yellow]Restart lit-harvest for the change to take effect.[/yellow]")


@storage_app.command("reset")
def storage_reset(
    migrate: Annotated[bool, typer.Option("--migrate/--no-migrate")] = True,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Go back to the default ./data directory."""
    _print_json(_container(config).storage_settings.reset_to_default(migrate=migrate))
    console.print("[yellow]Restart lit-harvest for the change to take effect.[/yellow]")


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
def demo(
    reset: Annotated[
        bool, typer.Option("--reset", help="Delete demo papers first, then regenerate.")
    ] = False,
    clear: Annotated[bool, typer.Option("--clear", help="Delete the demo data and exit.")] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Create sample data so you can try the tool without any API key."""
    from lit_harvest.demo.generator import clear_demo_data, generate_demo_data

    container = _container(config)
    if clear or reset:
        removed = clear_demo_data(container)
        console.print(f"Removed {removed} demo paper(s).")
        if clear and not reset:
            return
    result = generate_demo_data(container)
    table = Table(title="Demo data ready")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("New papers", str(result.created_papers))
    table.add_row("Already present", str(result.skipped_papers))
    table.add_row("Successful jobs", str(result.created_jobs))
    table.add_row("Data directory", result.data_dir)
    table.add_row("Database", result.database)
    console.print(table)
    console.print()
    console.print("[bold]Try it now:[/bold]")
    console.print("  lit-harvest ui          # open the dashboard")
    console.print("  lit-harvest jobs        # list jobs")
    console.print("  lit-harvest export demo.csv")
    console.print()
    console.print(
        "[yellow]Note:[/yellow] these are offline samples. Real downloads still require "
        "your own Elsevier API key (lit-harvest auth set)."
    )


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
    download_session: Annotated[
        str | None,
        typer.Option(
            "--download-session",
            help="Download every candidate of an earlier session id, then exit.",
        ),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Discovery provider: elsevier (Scopus) or openalex (key-free).",
        ),
    ] = None,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Search Scopus and preview the results (nothing is downloaded yet)."""
    if download_session:
        container = _container(config)
        try:
            session = container.acquisition.search_sessions.get(download_session)
            container.acquisition.search_sessions.update_selection(
                download_session, [item.candidate_id for item in session.candidates]
            )
            download_result = container.acquisition.fetch_selected(download_session)
        except Exception as exc:  # noqa: BLE001
            _explain(exc)
            return
        _print_json(download_result)
        return
    container = _container(config)
    try:
        result = container.acquisition.search(
            query,
            max_results=max_results,
            start_year=start_year,
            end_year=end_year,
            export=export,
            provider_name=provider,
        )
    except Exception as exc:  # noqa: BLE001 - translated into user guidance
        _explain(exc)
        return
    review = (
        container.acquisition.search_sessions.get(result.session_id) if result.session_id else None
    )
    table = Table(title=f"Search results for: {result.query}")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Journal")
    table.add_column("Year")
    table.add_column("DOI")
    table.add_column("Open Access")
    if review:
        for index, candidate in enumerate(review.candidates, start=1):
            table.add_row(
                str(index),
                (candidate.title or "(untitled)")[:60],
                (candidate.journal or "-")[:28],
                str(candidate.year or "-"),
                candidate.doi or "-",
                "yes" if candidate.open_access else "-",
            )
    console.print(table)
    console.print()
    console.print(
        f"Found {result.discovered} candidate(s); {result.total_results or result.discovered} "
        "matched in total."
    )
    console.print(
        "[yellow]Nothing has been downloaded yet.[/yellow] Choose what to download in the "
        "dashboard (Papers page), or select everything with:"
    )
    if result.session_id:
        console.print(f"  lit-harvest search --download-session {result.session_id}")
    if export:
        console.print(f"Exported the registry to {export}")


@app.command("fetch-session")
def fetch_session(
    session_id: Annotated[str, typer.Argument(help="Session id printed by `lit-harvest search`.")],
    pdf: Annotated[bool, typer.Option("--pdf/--no-pdf")] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Download every candidate from a previewed search session."""
    container = _container(config)
    try:
        session = container.acquisition.search_sessions.get(session_id)
        container.acquisition.search_sessions.update_selection(
            session_id, [item.candidate_id for item in session.candidates]
        )
        result = container.acquisition.fetch_selected(session_id, download_pdf=pdf)
    except Exception as exc:  # noqa: BLE001 - translated into guidance
        _explain(exc)
        return
    _print_json(result)


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
    try:
        if path.exists() and path.is_file():
            imported = container.acquisition.import_dois(path, doi_column=doi_column)
        else:
            imported = None
    except Exception as exc:  # noqa: BLE001 - translated into user guidance
        _explain(exc)
        return
    if imported is not None:
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
    try:
        fetched = container.acquisition.fetch_now(source)
    except Exception as exc:  # noqa: BLE001 - translated into user guidance
        _explain(exc)
        return
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
            console.print(
                "[yellow]XML saved successfully, but the PDF could not be "
                f"downloaded: {exc}[/yellow]"
            )
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
    try:
        _print_json(_container(config).acquisition.parse_pending(limit=limit, force=force))
    except Exception as exc:  # noqa: BLE001 - translated into user guidance
        _explain(exc)


@app.command()
def enrich(
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    all_papers: Annotated[
        bool, typer.Option("--all", help="Refresh metadata even when a title exists.")
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Fill missing titles, authors, and abstracts from OpenAlex (no key needed)."""
    container = _container(config)
    try:
        result = container.acquisition.enrich_metadata(limit=limit, only_incomplete=not all_papers)
    except Exception as exc:  # noqa: BLE001 - translated into guidance
        _explain(exc)
        return
    _print_json({k: v for k, v in result.items() if k != "results"})
    console.print(
        f"Enriched {result['enriched']} paper(s); skipped {result['skipped']}; "
        f"failed {result['failed']}."
    )


@app.command()
def cache(
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Show how much full text is cached locally."""
    summary = _container(config).cache.summary()
    table = Table(title="Local full-text cache")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Papers", str(summary["papers"]))
    table.add_row("Raw cached", str(summary["raw_cached"]))
    table.add_row("Raw missing", str(summary["raw_missing"]))
    table.add_row("Normalized available", str(summary["normalized_available"]))
    table.add_row("Disk used", f"{summary['cached_megabytes']} MB")
    console.print(table)
    if summary["raw_missing"]:
        console.print(
            "\n[dim]Missing raw files can be restored with `lit-harvest rebuild --missing`.[/dim]"
        )


@app.command()
def cleanup(
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
    drop_normalized: Annotated[
        bool,
        typer.Option(
            "--drop-normalized", help="Also delete normalized JSON, keeping only metadata."
        ),
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Delete cached raw full text while keeping metadata and results.

    Publisher agreements usually require removing the original full text when a
    project ends. Derived data may be retained.
    """
    container = _container(config)
    summary = container.cache.summary()
    if summary["raw_cached"] == 0:
        console.print("Nothing to clean: no raw full text is cached.")
        return
    console.print(
        f"About to delete raw full text for [bold]{summary['raw_cached']}[/bold] paper(s) "
        f"({summary['cached_megabytes']} MB)."
    )
    console.print(
        "Metadata and normalized documents are kept"
        + ("" if not drop_normalized else " (except normalized JSON)")
        + "."
    )
    if not yes:
        confirmed = typer.confirm("Continue?")
        if not confirmed:
            console.print("Cancelled.")
            return
    result = container.cache.cleanup_raw(keep_normalized=not drop_normalized)
    _print_json(result.to_dict())


@app.command()
def rebuild(
    missing: Annotated[
        bool, typer.Option("--missing", help="Only rebuild papers whose raw cache is gone.")
    ] = True,
    pdf: Annotated[bool, typer.Option("--pdf/--no-pdf", help="Also restore PDFs.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Re-fetch raw full text for papers whose cache was deleted."""
    container = _container(config)
    targets = container.cache.missing_raw(limit=limit)
    if not targets:
        console.print("Nothing to rebuild: every paper with a DOI still has its raw file.")
        return
    console.print(
        f"Will re-download full text for [bold]{len(targets)}[/bold] paper(s) (up to {limit})."
    )
    interval = container.policy.policy_for("elsevier").min_interval("article_retrieval")
    console.print(
        f"Pacing policy: {interval:g}s between requests. Ctrl+C is safe; progress is saved."
    )
    if not yes:
        confirmed = typer.confirm("Continue?")
        if not confirmed:
            console.print("Cancelled.")
            return

    def progress(index: int, total: int, entry: dict[str, Any]) -> None:
        console.print(f"  [{index}/{total}] {entry.get('doi')} -> {entry.get('status')}")

    try:
        result = container.acquisition.rebuild_missing(
            limit=limit, download_pdf=pdf, on_progress=progress
        )
    except Exception as exc:  # noqa: BLE001 - translated into guidance
        _explain(exc)
        return
    _print_json({k: v for k, v in result.items() if k != "results"})
    console.print(f"Summary: {result['succeeded']} restored, {result['failed']} failed.")


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
def worker(
    poll_interval: Annotated[float, typer.Option("--poll-interval", min=0.1)] = 2.0,
    max_jobs: Annotated[int, typer.Option("--max-jobs", min=1)] = 25,
    once: Annotated[
        bool, typer.Option("--once", help="Run one batch and exit instead of looping.")
    ] = False,
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run queued jobs in the background (or in one batch with --once)."""
    container = _container(config)
    container.worker.poll_interval_seconds = poll_interval
    container.worker.max_jobs_per_tick = max_jobs
    if once:
        _print_json(container.worker.state.last_result or {})
        container.worker.run_once(max_jobs=max_jobs)
        _print_json(container.worker.state.last_result or {})
        return
    console.print("Worker started. Press Ctrl+C to stop.")
    try:
        container.worker.run_forever()
    except KeyboardInterrupt:
        console.print("Worker stopped.")


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
    if not is_loopback(selected_host) and not loaded.server.allow_non_loopback:
        console.print(
            "[red]Refusing to bind to "
            f"{selected_host}:[/red] this dashboard has no authentication and would be "
            "readable by anyone who can reach the port.\n"
            "Set `server.allow_non_loopback: true` in config.yaml only if you have added "
            "your own authentication or a trusted reverse proxy."
        )
        raise typer.Exit(code=1)
    identity = local_identity(loaded.storage.root.parent)
    console.print(
        f"[bold]Local instance[/bold] user={identity['user']} host={identity['hostname']}"
    )
    console.print(f"Instance ID: {identity['instance_id'][:12]}")
    console.print("All papers, quotas, and secrets live only on this machine.")
    console.print(f"Dashboard: http://{selected_host}:{selected_port}")
    uvicorn.run(create_app(loaded), host=selected_host, port=selected_port)


if __name__ == "__main__":
    app()
