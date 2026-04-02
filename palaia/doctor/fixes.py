"""Palaia doctor fixes — apply_fixes and helper functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _pip_install_cmd(provider_name: str) -> str | None:
    """Return the pip install command for a provider, or None if not pip-installable."""
    install_map = {
        "sentence-transformers": 'pip install "palaia[sentence-transformers]"',
        "fastembed": 'pip install "palaia[fastembed]"',
    }
    return install_map.get(provider_name)


def _try_pip_install(cmd: str) -> bool:
    """Try to run a pip install command. Returns True on success."""
    import subprocess
    import sys

    # Extract package spec from the command (e.g. 'pip install "palaia[st]"' -> 'palaia[st]')
    parts = cmd.split()
    if len(parts) < 3:
        return False
    # Use the current Python interpreter's pip to ensure correct environment
    pkg = parts[2].strip('"').strip("'")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _build_best_chain(detected: list[dict[str, Any]]) -> list[str]:
    """Build the best available embedding chain from detected providers.

    Prefers semantic providers. BM25-only is the last resort.
    Priority: openai > sentence-transformers > fastembed > ollama > bm25
    """
    chain: list[str] = []
    priority_order = ["openai", "sentence-transformers", "fastembed", "ollama"]
    detected_map = {p["name"]: p["available"] for p in detected}

    for name in priority_order:
        if detected_map.get(name, False):
            chain.append(name)

    chain.append("bm25")
    return chain


def apply_fixes(palaia_root: Path | None, results: list[dict[str, Any]]) -> list[str]:
    """Apply automatic fixes for fixable warnings. Returns list of actions taken."""
    actions: list[str] = []
    if palaia_root is None:
        return actions

    from palaia.config import load_config, save_config
    from palaia.embeddings import detect_providers

    config = load_config(palaia_root)
    ran_warmup = False

    # Fix: storage_backend "entries on disk but 0 in database" — rebuild index
    for r in results:
        if r.get("name") == "storage_backend" and r.get("status") == "error":
            msg = r.get("message", "")
            if "entries on disk but 0 in database" in msg:
                try:
                    from palaia.entry import parse_entry
                    from palaia.store import Store

                    store = Store(palaia_root)
                    count = store.metadata_index.rebuild(parse_entry)
                    if count > 0:
                        actions.append(f"Rebuilt metadata index from disk: {count} entries indexed")
                    else:
                        actions.append("No entries found on disk to rebuild")
                except Exception as e:
                    actions.append(f"Index rebuild failed: {e}")

    for r in results:
        if r.get("status") != "warn":
            continue

        # Fix: embedding chain has missing providers
        if r.get("name") == "embedding_chain" and r.get("fixable"):
            missing = r.get("details", {}).get("missing", [])
            old_chain = config.get("embedding_chain", [])

            # Guard: respect explicit user embedding config (#57)
            # If embedding_provider is explicitly set (not "auto") and the
            # provider is still available, do NOT touch the chain or provider.
            explicit_provider = config.get("embedding_provider", "auto")
            if explicit_provider and explicit_provider != "auto":
                detected_guard = detect_providers()
                detected_guard_map = {p["name"]: p["available"] for p in detected_guard}
                if detected_guard_map.get(explicit_provider, False):
                    # Explicit provider is still functional — preserve config.
                    # Only remove broken providers from chain, keep the rest.
                    new_chain = [p for p in old_chain if p == "bm25" or detected_guard_map.get(p, False)]
                    if not new_chain or new_chain == ["bm25"]:
                        # At minimum, keep the explicit provider + bm25
                        new_chain = [explicit_provider, "bm25"]
                    elif "bm25" not in new_chain:
                        new_chain.append("bm25")

                    if new_chain != old_chain:
                        config["embedding_chain"] = new_chain
                        save_config(palaia_root, config)
                        chain_str = " → ".join(new_chain)
                        actions.append(f"Cleaned chain (kept explicit provider {explicit_provider}): {chain_str}")
                    else:
                        actions.append(f"Explicit provider {explicit_provider} is available — config unchanged")
                    # Still need warmup if semantic providers present
                    if any(p != "bm25" for p in new_chain):
                        ran_warmup = True
                    continue

            installed_providers: list[str] = []

            # Step 1: Try to install missing providers via pip
            # Look up via palaia.doctor module to support monkeypatching in tests
            _doctor_mod = sys.modules.get("palaia.doctor", sys.modules[__name__])
            for provider_name in missing:
                install_cmd = getattr(_doctor_mod, "_pip_install_cmd")(provider_name)
                if install_cmd:
                    print(f"  Attempting: {install_cmd}")
                    success = getattr(_doctor_mod, "_try_pip_install")(install_cmd)
                    if success:
                        installed_providers.append(provider_name)
                        actions.append(f"Installed {provider_name}")
                        print(f"  Installed {provider_name} successfully.")
                    else:
                        print(f"  Could not install {provider_name}.")

            # Step 2: Re-detect providers after installation attempts
            detected = detect_providers()
            detected_map = {p["name"]: p["available"] for p in detected}

            # Step 3: Build new chain — keep available providers from old chain
            # preserving original order (user's preference)
            new_chain = [p for p in old_chain if p == "bm25" or detected_map.get(p, False)]

            # If chain is empty or only bm25, build best available chain
            # _build_best_chain() only as last resort when NO valid chain exists
            if not new_chain or new_chain == ["bm25"]:
                new_chain = _build_best_chain(detected)

            if "bm25" not in new_chain:
                new_chain.append("bm25")

            config["embedding_chain"] = new_chain
            save_config(palaia_root, config)

            chain_str = " → ".join(new_chain)
            if installed_providers:
                actions.append(f"Chain: {chain_str}")
            else:
                still_missing = [p for p in missing if not detected_map.get(p, False)]
                if still_missing:
                    actions.append(f"{', '.join(still_missing)} not available, chain updated to {chain_str}")
                else:
                    actions.append(f"Updated embedding chain: {chain_str}")

            # Step 4: Run warmup to download models
            if any(p != "bm25" for p in new_chain):
                ran_warmup = True

        # Fix: no chain configured → auto-detect and set
        if r.get("name") == "embedding_chain" and r.get("fixable") and not r.get("details", {}).get("missing"):
            # Guard: if explicit provider is set and available, build chain around it
            explicit_provider = config.get("embedding_provider", "auto")
            detected = detect_providers()
            detected_map = {p["name"]: p["available"] for p in detected}

            if explicit_provider and explicit_provider != "auto" and detected_map.get(explicit_provider, False):
                new_chain = [explicit_provider, "bm25"]
            else:
                new_chain = _build_best_chain(detected)

            config["embedding_chain"] = new_chain
            save_config(palaia_root, config)
            actions.append(f"Auto-configured chain: {' → '.join(new_chain)}")
            if any(p != "bm25" for p in new_chain):
                ran_warmup = True

    # Fix: stale embedding index
    for r in results:
        if r.get("name") == "index_staleness" and r.get("fixable") and r.get("status") == "warn":
            try:
                from palaia.embed_server import _warmup_missing
                from palaia.search import SearchEngine
                from palaia.store import Store

                store = Store(palaia_root)
                engine = SearchEngine(store)
                print("  Indexing missing entries...")
                stats = _warmup_missing(store, engine)
                new_count = stats.get("new", 0)
                if new_count > 0:
                    actions.append(f"Indexed {new_count} missing entries")
                else:
                    actions.append("Index is up to date")
            except Exception as e:
                actions.append(f"Index warmup failed: {e}")

    # Fix: corrupted fastembed cache
    for r in results:
        if r.get("name") == "embedding_model_integrity" and r.get("fixable") and r.get("status") == "warn":
            cache_dir = r.get("details", {}).get("cache_dir")
            if cache_dir:
                import shutil

                cache_path = Path(cache_dir)
                if cache_path.exists():
                    try:
                        shutil.rmtree(cache_path)
                        actions.append(f"Removed corrupted fastembed cache: {cache_dir}")
                        ran_warmup = True  # warmup will re-download
                    except OSError as e:
                        actions.append(f"Failed to remove corrupted cache: {e}")

    # Fix: upgrade v1.x plugin defaults to v2.0
    for r in results:
        if r.get("name") == "plugin_defaults_upgrade" and r.get("fixable") and r.get("status") == "warn":
            plugin_config = config.get("plugin_config", {})
            upgraded = []

            # Only upgrade values that match old v1.x defaults exactly
            if plugin_config.get("autoCapture") is False:
                plugin_config["autoCapture"] = True
                upgraded.append("autoCapture: false → true")
            if plugin_config.get("memoryInject") is False:
                plugin_config["memoryInject"] = True
                upgraded.append("memoryInject: false → true")
            if plugin_config.get("maxInjectedChars") == 4000:
                plugin_config["maxInjectedChars"] = 8000
                upgraded.append("maxInjectedChars: 4000 → 8000")
            if plugin_config.get("recallMode") == "list":
                plugin_config["recallMode"] = "query"
                upgraded.append("recallMode: list → query")
            if plugin_config.get("showMemorySources") is False:
                plugin_config["showMemorySources"] = True
                upgraded.append("showMemorySources: false → true")
            if plugin_config.get("showCaptureConfirm") is False:
                plugin_config["showCaptureConfirm"] = True
                upgraded.append("showCaptureConfirm: false → true")
            min_sig = plugin_config.get("captureMinSignificance")
            if isinstance(min_sig, (int, float)) and min_sig > 0.5:
                plugin_config["captureMinSignificance"] = 0.3
                upgraded.append(f"captureMinSignificance: {min_sig} → 0.3")

            if upgraded:
                config["plugin_config"] = plugin_config
                save_config(palaia_root, config)
                actions.append(f"Upgraded plugin defaults to v2.0: {', '.join(upgraded)}")

    # Run warmup + reindex after all fixes if we have semantic providers
    if ran_warmup:
        try:
            from palaia.embeddings import warmup_providers

            print("  Running warmup to pre-download models...")
            warmup_results = warmup_providers(config)
            for wr in warmup_results:
                status_label = "ok" if wr["status"] == "ready" else wr["status"]
                print(f"    [{status_label}] {wr['name']}: {wr['message']}")
            actions.append("Warmup complete")

            # Reindex entries to fill embedding cache
            try:
                from palaia.cli import _reindex_entries

                class _FakeArgs:
                    json = False

                print("  Building embedding index...")
                index_stats = _reindex_entries(palaia_root, config, _FakeArgs())
                if index_stats.get("new", 0) > 0:
                    actions.append(
                        f"Indexed {index_stats['indexed']} entries "
                        f"({index_stats['new']} new, {index_stats['cached']} cached)"
                    )
            except Exception as e:
                actions.append(f"Reindex failed: {e}")
        except Exception as e:
            actions.append(f"Warmup failed: {e}")

    # Fix: feedback-loop artifacts (#113) — backup + remove corrupted entries
    for r in results:
        if r.get("name") == "loop_artifacts" and r.get("fixable") and r.get("status") == "warn":
            artifact_ids = r.get("details", {}).get("artifact_ids", [])
            if not artifact_ids:
                continue

            from datetime import datetime, timezone

            from palaia.entry import parse_entry

            # Step 1: Back up corrupted entries to JSONL
            iso_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
            backup_path = palaia_root / f"gc-backup-{iso_date}.jsonl"

            backed_up = 0
            removed = 0

            try:
                with open(backup_path, "w", encoding="utf-8") as bf:
                    for entry_id in artifact_ids:
                        for tier in ("hot", "warm", "cold"):
                            entry_path = palaia_root / tier / f"{entry_id}.md"
                            if entry_path.exists():
                                try:
                                    text = entry_path.read_text(encoding="utf-8")
                                    meta, body = parse_entry(text)
                                    backup_record = {
                                        "id": entry_id,
                                        "tier": tier,
                                        "meta": meta,
                                        "body": body,
                                    }
                                    bf.write(json.dumps(backup_record, ensure_ascii=False) + "\n")
                                    backed_up += 1
                                except Exception as e:
                                    actions.append(f"Failed to back up {entry_id}: {e}")
                                break
            except Exception as e:
                actions.append(f"Failed to create backup file: {e}")
                continue  # Don't remove if backup failed

            # Step 2: Remove corrupted entries from store (only if backup succeeded)
            if backed_up > 0:
                for entry_id in artifact_ids:
                    for tier in ("hot", "warm", "cold"):
                        entry_path = palaia_root / tier / f"{entry_id}.md"
                        if entry_path.exists():
                            try:
                                entry_path.unlink()
                                removed += 1
                            except Exception as e:
                                actions.append(f"Failed to remove {entry_id}: {e}")
                            break

            if removed > 0:
                actions.append(
                    f"Removed {removed} feedback-loop artifact(s). "
                    f"Backup: {backup_path}"
                )

    return actions
