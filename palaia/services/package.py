"""Package service — knowledge package export/import business logic."""

from __future__ import annotations

from pathlib import Path

from palaia.packages import PackageManager
from palaia.store import Store


def package_export(
    root: Path,
    *,
    project: str,
    output_path: str | None = None,
    include_types: list[str] | None = None,
) -> dict:
    """Export a project as a knowledge package. Returns result dict."""
    store = Store(root)
    store.recover()
    pm_pkg = PackageManager(store)
    return pm_pkg.export_package(
        project=project,
        output_path=output_path,
        include_types=include_types,
    )


def package_import(
    root: Path,
    *,
    file: str,
    target_project: str | None = None,
    merge_strategy: str = "skip",
    agent: str | None = None,
) -> dict:
    """Import a knowledge package. Returns result dict."""
    store = Store(root)
    store.recover()
    pm_pkg = PackageManager(store)
    return pm_pkg.import_package(
        input_path=file,
        target_project=target_project,
        merge_strategy=merge_strategy,
        agent=agent,
    )


def package_info(root: Path, *, file: str) -> dict:
    """Show package metadata. Returns info dict or raises."""
    store = Store(root)
    pm_pkg = PackageManager(store)
    return pm_pkg.package_info(file)


def sync_export(
    *,
    remote: str | None = None,
    branch: str | None = None,
    output_dir: str | None = None,
    agent: str | None = None,
) -> dict:
    """Export public entries (sync). Returns result dict."""
    from palaia.sync import export_entries

    return export_entries(
        remote=remote,
        branch=branch,
        output_dir=output_dir,
        agent=agent,
    )


def sync_import(
    *,
    source: str,
    dry_run: bool = False,
) -> dict:
    """Import entries from export (sync). Returns result dict."""
    from palaia.sync import import_entries

    return import_entries(
        source=source,
        dry_run=dry_run,
    )
