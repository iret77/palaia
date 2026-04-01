"""Tests for palaia prune — selective entry cleanup by agent + tags (#146)."""

import json

from palaia.store import Store


def _make_store(tmp_path, config_extra=None):
    """Create a minimal store for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {"agent": "test"}
    if config_extra:
        config.update(config_extra)
    (root / "config.json").write_text(json.dumps(config))
    return Store(root)


class TestPrune:
    def test_prune_deletes_matching(self, tmp_path):
        """Entries matching agent + tags are deleted."""
        store = _make_store(tmp_path)
        id1 = store.write("Auto note 1", agent="worker", tags=["auto-capture"])
        id2 = store.write("Auto note 2", agent="worker", tags=["auto-capture"])
        id3 = store.write("Manual note", agent="worker", tags=["manual"])

        result = store.prune(agent="worker", tags=["auto-capture"])
        assert result["pruned"] == 2
        assert result["dry_run"] is False

        # Verify files deleted
        assert not (store.root / "hot" / f"{id1}.md").exists()
        assert not (store.root / "hot" / f"{id2}.md").exists()
        # Unmatched entry survives
        assert (store.root / "hot" / f"{id3}.md").exists()

    def test_prune_requires_all_tags(self, tmp_path):
        """Entry must have ALL specified tags to be pruned."""
        store = _make_store(tmp_path)
        id1 = store.write("Session note", agent="worker", tags=["auto-capture", "session-summary"])
        id2 = store.write("Auto note", agent="worker", tags=["auto-capture"])

        result = store.prune(agent="worker", tags=["auto-capture", "session-summary"])
        assert result["pruned"] == 1
        assert result["entries"][0]["full_id"] == id1
        # Entry with only auto-capture survives
        assert (store.root / "hot" / f"{id2}.md").exists()

    def test_prune_filters_by_agent(self, tmp_path):
        """Only entries from the specified agent are pruned."""
        store = _make_store(tmp_path)
        id1 = store.write("Worker note", agent="worker", tags=["auto-capture"])
        id2 = store.write("Other note", agent="orchestrator", tags=["auto-capture"])

        result = store.prune(agent="worker", tags=["auto-capture"])
        assert result["pruned"] == 1
        # Other agent's entry survives
        assert (store.root / "hot" / f"{id2}.md").exists()

    def test_prune_protect_type(self, tmp_path):
        """Entries with protected types are preserved."""
        store = _make_store(tmp_path)
        id_proc = store.write("1. Step one\n2. Step two", agent="worker",
                              entry_type="process", tags=["auto-capture"])
        id_task = store.write("Do the thing", agent="worker",
                              entry_type="task", tags=["auto-capture"])
        id_mem = store.write("Some note", agent="worker",
                             entry_type="memory", tags=["auto-capture"])

        result = store.prune(
            agent="worker", tags=["auto-capture"],
            protect_types=["process", "task"],
        )
        assert result["pruned"] == 1
        assert result["entries"][0]["type"] == "memory"
        # Protected types survive
        assert (store.root / "hot" / f"{id_proc}.md").exists()
        assert (store.root / "hot" / f"{id_task}.md").exists()
        assert not (store.root / "hot" / f"{id_mem}.md").exists()

    def test_prune_dry_run(self, tmp_path):
        """Dry-run returns candidates without deleting."""
        store = _make_store(tmp_path)
        id1 = store.write("Auto note", agent="worker", tags=["auto-capture"])

        result = store.prune(agent="worker", tags=["auto-capture"], dry_run=True)
        assert result["dry_run"] is True
        assert result["pruned"] == 1
        # File still exists
        assert (store.root / "hot" / f"{id1}.md").exists()

    def test_prune_no_matches(self, tmp_path):
        """No matches returns pruned=0."""
        store = _make_store(tmp_path)
        store.write("Unrelated note", agent="other", tags=["manual"])

        result = store.prune(agent="worker", tags=["auto-capture"])
        assert result["pruned"] == 0
        assert result["entries"] == []

    def test_prune_across_tiers(self, tmp_path):
        """Prune finds entries across hot/warm/cold tiers."""
        store = _make_store(tmp_path)
        # Write entry directly to warm tier
        id_hot = store.write("Hot note", agent="worker", tags=["auto-capture"])
        # Manually place one in warm
        hot_path = store.root / "hot" / f"{id_hot}.md"
        warm_path = store.root / "warm" / f"{id_hot}.md"
        warm_path.write_text(hot_path.read_text())
        hot_path.unlink()

        id_hot2 = store.write("Hot note 2", agent="worker", tags=["auto-capture"])

        result = store.prune(agent="worker", tags=["auto-capture"])
        assert result["pruned"] == 2
        tiers = {e["tier"] for e in result["entries"]}
        assert "warm" in tiers
        assert "hot" in tiers

    def test_prune_invalidates_embedding_cache(self, tmp_path):
        """Pruned entries are removed from embedding cache."""
        store = _make_store(tmp_path)
        id1 = store.write("Cached note", agent="worker", tags=["auto-capture"])
        # Simulate cached embedding
        store.embedding_cache.set_cached(id1, [0.1, 0.2, 0.3])
        assert store.embedding_cache.get_cached(id1) is not None

        store.prune(agent="worker", tags=["auto-capture"])
        assert store.embedding_cache.get_cached(id1) is None
