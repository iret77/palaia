"""Memory store with tier routing (ADR-004)."""

from __future__ import annotations

import os
from pathlib import Path

from palaia.config import load_config
from palaia.decay import classify_tier, days_since, decay_score
from palaia.entry import content_hash, create_entry, parse_entry, serialize_entry, update_access
from palaia.index import EmbeddingCache
from palaia.lock import PalaiaLock
from palaia.scope import can_access, normalize_scope
from palaia.wal import WAL, WALEntry

TIERS = ("hot", "warm", "cold")


class Store:
    """Memory store with WAL, locking, and tier management."""

    def __init__(self, palaia_root: Path):
        self.root = palaia_root
        self.config = load_config(palaia_root)
        self.wal = WAL(palaia_root)
        self.lock = PalaiaLock(palaia_root, self.config["lock_timeout_seconds"])
        self.embedding_cache = EmbeddingCache(palaia_root)

        # Ensure tier directories
        for tier in TIERS:
            (self.root / tier).mkdir(parents=True, exist_ok=True)

    def recover(self) -> int:
        """Run WAL recovery on startup."""
        return self.wal.recover(self)

    def write(
        self,
        body: str,
        scope: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        title: str | None = None,
        project: str | None = None,
    ) -> str:
        """Write a new memory entry. Returns the entry ID.

        Scope cascade:
        1. Explicit --scope argument wins always
        2. Project default_scope if entry is in a project
        3. Global default_scope from config
        4. Hardcoded fallback: 'team'
        """
        if not body or not body.strip():
            raise ValueError("Cannot write empty content. Provide a non-empty text body.")

        # Scope cascade
        if scope is not None:
            # Explicit scope always wins
            scope = normalize_scope(scope)
        elif project:
            # Auto-create project if it doesn't exist, then use its default scope
            from palaia.project import ProjectManager

            pm = ProjectManager(self.root)
            proj = pm.ensure(project, default_scope=self.config["default_scope"])
            scope = normalize_scope(proj.default_scope)
        else:
            scope = normalize_scope(None, self.config["default_scope"])

        # Dedup check
        h = content_hash(body)
        existing = self._find_by_hash(h)
        if existing:
            return existing  # Already stored, return existing ID

        entry_text = create_entry(body, scope, agent, tags, title, project)
        meta, _ = parse_entry(entry_text)
        entry_id = meta["id"]
        filename = f"{entry_id}.md"
        target = f"hot/{filename}"

        with self.lock:
            # WAL: log intent with payload for recovery
            wal_entry = WALEntry(
                operation="write",
                target=target,
                payload_hash=h,
                payload=entry_text,
            )
            self.wal.log(wal_entry)

            # Write the actual file
            self.write_raw(target, entry_text)

            # Commit WAL
            self.wal.commit(wal_entry)

        # Invalidate any stale embedding cache for this entry
        self.embedding_cache.invalidate(entry_id)

        return entry_id

    def write_raw(self, target: str, content: str) -> None:
        """Write content to a target path (relative to palaia root). Used by WAL recovery."""
        path = self.root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(path)

    def delete_raw(self, target: str) -> None:
        """Delete a target path (relative to palaia root)."""
        path = self.root / target
        if path.exists():
            path.unlink()

    def read(
        self, entry_id: str, agent: str | None = None, projects: list[str] | None = None
    ) -> tuple[dict, str] | None:
        """Read a memory entry by ID. Updates access metadata."""
        path = self._find_entry(entry_id)
        if path is None:
            return None

        text = path.read_text(encoding="utf-8")
        meta, body = parse_entry(text)

        # Scope check
        if not can_access(meta.get("scope", "team"), agent, meta.get("agent"), projects):
            return None

        # Update access
        meta = update_access(meta)
        new_text = serialize_entry(meta, body)

        with self.lock:
            self.write_raw(str(path.relative_to(self.root)), new_text)

        return meta, body

    def list_entries(
        self, tier: str = "hot", agent: str | None = None, projects: list[str] | None = None
    ) -> list[tuple[dict, str]]:
        """List all entries in a tier."""
        tier_dir = self.root / tier
        if not tier_dir.exists():
            return []

        results = []
        for p in sorted(tier_dir.glob("*.md")):
            try:
                text = p.read_text(encoding="utf-8")
                meta, body = parse_entry(text)
                if can_access(meta.get("scope", "team"), agent, meta.get("agent"), projects):
                    results.append((meta, body))
            except (OSError, UnicodeDecodeError):
                continue
        return results

    def all_entries(
        self, include_cold: bool = False, agent: str | None = None, projects: list[str] | None = None
    ) -> list[tuple[dict, str, str]]:
        """Get all entries across tiers. Returns (meta, body, tier)."""
        tiers = ["hot", "warm"] + (["cold"] if include_cold else [])
        results = []
        for tier in tiers:
            for meta, body in self.list_entries(tier, agent, projects):
                results.append((meta, body, tier))
        return results

    def gc(self) -> dict:
        """Garbage collect: rotate tiers based on decay scores."""
        moves = {"hot_to_warm": 0, "warm_to_cold": 0, "cold_to_warm": 0, "warm_to_hot": 0}
        config = self.config

        with self.lock:
            for tier in TIERS:
                tier_dir = self.root / tier
                if not tier_dir.exists():
                    continue
                for p in tier_dir.glob("*.md"):
                    try:
                        text = p.read_text(encoding="utf-8")
                        meta, body = parse_entry(text)
                    except (OSError, UnicodeDecodeError):
                        continue

                    accessed = meta.get("accessed", meta.get("created", ""))
                    if not accessed:
                        continue

                    d = days_since(accessed)
                    ac = meta.get("access_count", 1)
                    score = decay_score(d, ac, config["decay_lambda"])
                    meta["decay_score"] = score

                    new_tier = classify_tier(
                        d,
                        score,
                        config["hot_threshold_days"],
                        config["warm_threshold_days"],
                        config["hot_min_score"],
                        config["warm_min_score"],
                    )

                    # Update the score in file
                    new_text = serialize_entry(meta, body)

                    if new_tier != tier:
                        new_target = f"{new_tier}/{p.name}"
                        # WAL: log the move with payload for crash recovery
                        wal_entry = WALEntry(
                            operation="write",
                            target=new_target,
                            payload_hash=meta.get("content_hash", ""),
                            payload=new_text,
                        )
                        self.wal.log(wal_entry)
                        self.write_raw(new_target, new_text)
                        p.unlink()
                        self.wal.commit(wal_entry)
                        key = f"{tier}_to_{new_tier}"
                        moves[key] = moves.get(key, 0) + 1
                    else:
                        with open(p, "w") as f:
                            f.write(new_text)

        # WAL cleanup
        wal_cleaned = self.wal.cleanup(config["wal_retention_days"])
        moves["wal_cleaned"] = wal_cleaned

        # Embedding cache cleanup: remove entries for deleted IDs
        valid_ids = set()
        for tier in TIERS:
            tier_dir = self.root / tier
            if tier_dir.exists():
                for p in tier_dir.glob("*.md"):
                    valid_ids.add(p.stem)
        stale = self.embedding_cache.cleanup(valid_ids)
        if stale:
            moves["embeddings_cleaned"] = stale

        return moves

    def status(self) -> dict:
        """Get system status info."""
        counts = {}
        for tier in TIERS:
            tier_dir = self.root / tier
            if tier_dir.exists():
                counts[tier] = len(list(tier_dir.glob("*.md")))
            else:
                counts[tier] = 0

        wal_dir = self.root / "wal"
        pending = len(self.wal.get_pending()) if wal_dir.exists() else 0

        return {
            "palaia_root": str(self.root),
            "entries": counts,
            "total": sum(counts.values()),
            "wal_pending": pending,
            "config": self.config,
        }

    def _find_entry(self, entry_id: str) -> Path | None:
        """Find an entry file across tiers."""
        filename = f"{entry_id}.md"
        for tier in TIERS:
            path = self.root / tier / filename
            if path.exists():
                return path
        return None

    def _find_by_hash(self, h: str) -> str | None:
        """Find entry ID by content hash (dedup)."""
        for tier in TIERS:
            tier_dir = self.root / tier
            if not tier_dir.exists():
                continue
            for p in tier_dir.glob("*.md"):
                try:
                    text = p.read_text(encoding="utf-8")
                    meta, _ = parse_entry(text)
                    if meta.get("content_hash") == h:
                        return meta.get("id")
                except (OSError, UnicodeDecodeError):
                    continue
        return None
