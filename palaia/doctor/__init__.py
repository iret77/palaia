"""palaia doctor — diagnose local instance and detect legacy memory systems."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from palaia.doctor.checks import (
    LOOP_ARTIFACT_PATTERNS,
    _check_agent_identity,
    _check_binary_path,
    _check_capture_health,
    _check_capture_level,
    _check_capture_model,
    _check_default_agent_alias,
    _check_deprecated_config,
    _check_embedding_chain,
    _check_embedding_model_integrity,
    _check_entry_classes,
    _check_heartbeat_legacy,
    _check_index_staleness,
    _check_legacy_memory_files,
    _check_loop_artifacts,
    _check_mcp_server,
    _check_multi_agent_static,
    _check_native_vector_search,
    _check_openclaw_plugin,
    _check_palaia_init,
    _check_plugin_defaults_upgrade,
    _check_plugin_version_match,
    _check_projects_usage,
    _check_smart_memory_skill,
    _check_stale_unassigned_tasks,
    _check_storage_backend,
    _check_store_version,
    _check_unread_memos,
    _check_version_available,
    _check_wal_health,
    _is_loop_artifact,
)
from palaia.doctor.fixes import (
    _build_best_chain,
    _pip_install_cmd,
    _try_pip_install,
    apply_fixes,
)
from palaia.doctor.report import format_doctor_report


def run_doctor(palaia_root: Path | None = None) -> list[dict[str, Any]]:
    """Run all doctor checks. Returns list of check results."""
    results = [
        _check_palaia_init(palaia_root),
        _check_agent_identity(palaia_root),
        _check_multi_agent_static(palaia_root),
        _check_binary_path(palaia_root),
        _check_plugin_version_match(),
        _check_store_version(palaia_root),
        _check_version_available(palaia_root),
        _check_embedding_chain(palaia_root),
        _check_embedding_model_integrity(palaia_root),
        _check_index_staleness(palaia_root),
        _check_entry_classes(palaia_root),
        _check_projects_usage(palaia_root),
        _check_deprecated_config(palaia_root),
        _check_default_agent_alias(palaia_root),
        _check_unread_memos(palaia_root),
        _check_capture_level(palaia_root),
        _check_capture_model(),
        _check_capture_health(palaia_root),
        _check_plugin_defaults_upgrade(palaia_root),
        _check_openclaw_plugin(),
        _check_smart_memory_skill(),
        _check_legacy_memory_files(),
        _check_heartbeat_legacy(),
        _check_wal_health(palaia_root),
        _check_loop_artifacts(palaia_root),
        _check_stale_unassigned_tasks(palaia_root),
        _check_storage_backend(palaia_root),
        _check_native_vector_search(palaia_root),
        _check_mcp_server(palaia_root),
    ]
    return results


__all__ = [
    # Public API
    "run_doctor",
    "apply_fixes",
    "format_doctor_report",
    # Check functions (used by tests)
    "_check_agent_identity",
    "_check_capture_health",
    "_check_capture_level",
    "_check_capture_model",
    "_check_default_agent_alias",
    "_check_deprecated_config",
    "_check_embedding_chain",
    "_check_embedding_model_integrity",
    "_check_entry_classes",
    "_check_heartbeat_legacy",

    "_check_index_staleness",
    "_check_legacy_memory_files",
    "_check_loop_artifacts",
    "_check_mcp_server",
    "_check_multi_agent_static",
    "_check_native_vector_search",
    "_check_openclaw_plugin",
    "_check_palaia_init",
    "_check_plugin_defaults_upgrade",
    "_check_plugin_version_match",
    "_check_projects_usage",
    "_check_smart_memory_skill",
    "_check_stale_unassigned_tasks",
    "_check_storage_backend",
    "_check_store_version",
    "_check_unread_memos",
    "_check_version_available",
    "_check_wal_health",
    # Fix helpers (used by tests)
    "_build_best_chain",
    "_pip_install_cmd",
    "_try_pip_install",
    # Internal (used by tests)
    "_is_loop_artifact",
    "LOOP_ARTIFACT_PATTERNS",
]
