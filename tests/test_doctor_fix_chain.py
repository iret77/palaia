"""Tests for doctor --fix embedding chain auto-repair."""

from __future__ import annotations

import json

import pytest

from palaia.doctor import _build_best_chain, apply_fixes, run_doctor


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with a broken chain."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {
        "version": 1,
        "agent": "TestAgent",
        "embedding_chain": ["sentence-transformers", "bm25"],
        "default_scope": "team",
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_max_entries": 50,
        "hot_min_score": 0.5,
        "warm_min_score": 0.1,
        "wal_retention_days": 7,
        "lock_timeout_seconds": 5,
        "embedding_provider": "auto",
        "embedding_model": "",
        "store_version": "1.7.0",
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


class TestBuildBestChain:
    def test_prefers_semantic_over_bm25(self):
        detected = [
            {"name": "sentence-transformers", "available": True},
            {"name": "bm25", "available": True},
        ]
        chain = _build_best_chain(detected)
        assert chain == ["sentence-transformers", "bm25"]

    def test_fallback_to_bm25_only(self):
        detected = [
            {"name": "sentence-transformers", "available": False},
            {"name": "fastembed", "available": False},
            {"name": "ollama", "available": False},
            {"name": "openai", "available": False},
        ]
        chain = _build_best_chain(detected)
        assert chain == ["bm25"]

    def test_openai_plus_local(self):
        detected = [
            {"name": "openai", "available": True},
            {"name": "sentence-transformers", "available": True},
            {"name": "fastembed", "available": False},
        ]
        chain = _build_best_chain(detected)
        assert chain[0] == "openai"
        assert "sentence-transformers" in chain
        assert chain[-1] == "bm25"

    def test_fastembed_fallback(self):
        detected = [
            {"name": "sentence-transformers", "available": False},
            {"name": "fastembed", "available": True},
            {"name": "openai", "available": False},
        ]
        chain = _build_best_chain(detected)
        assert chain == ["fastembed", "bm25"]


class TestExplicitProviderGuard:
    """Tests for #57: doctor --fix should not override explicit user embedding config."""

    def test_explicit_provider_preserved_when_available(self, palaia_root, monkeypatch):
        """If embedding_provider is explicitly set and available, chain is NOT rebuilt."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_provider"] = "fastembed"
        config["embedding_chain"] = ["fastembed", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "fastembed", "available": True},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )

        # Simulate warning with openai missing from a chain that had it
        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "fastembed -> openai -> bm25 — MISSING: openai",
                "fixable": True,
                "details": {
                    "chain": ["fastembed", "openai", "bm25"],
                    "missing": ["openai"],
                },
            }
        ]

        apply_fixes(palaia_root, results)

        config = json.loads((palaia_root / "config.json").read_text())
        assert config["embedding_provider"] == "fastembed"
        chain = config["embedding_chain"]
        assert chain[0] == "fastembed"
        assert "openai" not in chain
        assert "bm25" in chain

    def test_explicit_provider_no_change_when_chain_healthy(self, palaia_root, monkeypatch):
        """If explicit provider is set and chain is fine, config stays untouched."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_provider"] = "fastembed"
        config["embedding_chain"] = ["fastembed", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "fastembed", "available": True},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )

        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "fastembed -> bm25 — MISSING: openai",
                "fixable": True,
                "details": {
                    "chain": ["fastembed", "bm25"],
                    "missing": ["openai"],
                },
            }
        ]

        actions = apply_fixes(palaia_root, results)

        config = json.loads((palaia_root / "config.json").read_text())
        assert config["embedding_chain"] == ["fastembed", "bm25"]
        assert any("unchanged" in a for a in actions)

    def test_explicit_provider_broken_falls_back(self, palaia_root, monkeypatch):
        """If explicit provider is set but NOT available, normal rebuild happens."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_provider"] = "fastembed"
        config["embedding_chain"] = ["fastembed", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "fastembed", "available": False},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )
        monkeypatch.setattr("palaia.doctor._try_pip_install", lambda cmd: False)
        monkeypatch.setattr(
            "palaia.embeddings.warmup_providers",
            lambda cfg: [{"name": "sentence-transformers", "status": "ready", "message": "ok"}],
        )

        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "fastembed -> bm25 — MISSING: fastembed",
                "fixable": True,
                "details": {
                    "chain": ["fastembed", "bm25"],
                    "missing": ["fastembed"],
                },
            }
        ]

        apply_fixes(palaia_root, results)

        config = json.loads((palaia_root / "config.json").read_text())
        chain = config["embedding_chain"]
        assert "sentence-transformers" in chain
        assert "bm25" in chain

    def test_auto_provider_allows_full_rebuild(self, palaia_root, monkeypatch):
        """With embedding_provider='auto', _build_best_chain() runs as before."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_provider"] = "auto"
        config["embedding_chain"] = ["fastembed", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "fastembed", "available": False},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )
        monkeypatch.setattr("palaia.doctor._try_pip_install", lambda cmd: False)
        monkeypatch.setattr(
            "palaia.embeddings.warmup_providers",
            lambda cfg: [{"name": "sentence-transformers", "status": "ready", "message": "ok"}],
        )

        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "fastembed -> bm25 — MISSING: fastembed",
                "fixable": True,
                "details": {
                    "chain": ["fastembed", "bm25"],
                    "missing": ["fastembed"],
                },
            }
        ]

        apply_fixes(palaia_root, results)

        config = json.loads((palaia_root / "config.json").read_text())
        chain = config["embedding_chain"]
        assert "sentence-transformers" in chain

    def test_no_chain_configured_respects_explicit_provider(self, palaia_root, monkeypatch):
        """When no chain is configured but provider is explicit, chain uses that provider."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_provider"] = "fastembed"
        if "embedding_chain" in config:
            del config["embedding_chain"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "fastembed", "available": True},
                {"name": "openai", "available": True},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )

        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "No chain configured (using auto-detect)",
                "fixable": True,
            }
        ]

        apply_fixes(palaia_root, results)

        config = json.loads((palaia_root / "config.json").read_text())
        chain = config["embedding_chain"]
        assert chain[0] == "fastembed"
        assert "bm25" in chain


class TestApplyFixesMissingProviders:
    def test_fix_rebuilds_chain_on_missing(self, palaia_root, monkeypatch):
        """When a provider is missing and can't be installed, chain is rebuilt."""
        # Mock detect_providers at source module (imported inside apply_fixes)
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": False},
                {"name": "fastembed", "available": True},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )
        # Mock _try_pip_install to always fail
        monkeypatch.setattr("palaia.doctor._try_pip_install", lambda cmd: False)
        # Mock warmup_providers
        monkeypatch.setattr(
            "palaia.embeddings.warmup_providers",
            lambda config: [{"name": "fastembed", "status": "ready", "message": "ok"}],
        )

        # Run doctor to get results with broken chain
        results = run_doctor(palaia_root)
        actions = apply_fixes(palaia_root, results)

        assert len(actions) > 0
        # Chain should be updated
        config = json.loads((palaia_root / "config.json").read_text())
        chain = config["embedding_chain"]
        assert "sentence-transformers" not in chain
        assert "fastembed" in chain
        assert "bm25" in chain

    def test_fix_installs_missing_provider(self, palaia_root, monkeypatch):
        """When pip install succeeds, chain keeps the provider."""
        call_count = {"installs": 0}

        def mock_install(cmd):
            call_count["installs"] += 1
            return True  # Simulate success

        monkeypatch.setattr("palaia.doctor._try_pip_install", mock_install)

        # After pip install succeeds, detect should find it available
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": True},
                {"name": "bm25", "available": True},
            ],
        )
        monkeypatch.setattr(
            "palaia.embeddings.warmup_providers",
            lambda config: [{"name": "sentence-transformers", "status": "ready", "message": "ok"}],
        )

        # Simulate broken chain result
        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "sentence-transformers → bm25 — MISSING: sentence-transformers",
                "fixable": True,
                "details": {
                    "chain": ["sentence-transformers", "bm25"],
                    "missing": ["sentence-transformers"],
                },
            }
        ]

        actions = apply_fixes(palaia_root, results)
        assert call_count["installs"] == 1
        assert any("Installed sentence-transformers" in a for a in actions)

        config = json.loads((palaia_root / "config.json").read_text())
        assert "sentence-transformers" in config["embedding_chain"]

    def test_fix_bm25_last_resort(self, palaia_root, monkeypatch):
        """BM25-only should be the absolute last fallback."""
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "sentence-transformers", "available": False},
                {"name": "fastembed", "available": False},
                {"name": "openai", "available": False},
                {"name": "ollama", "available": False},
                {"name": "bm25", "available": True},
            ],
        )
        monkeypatch.setattr("palaia.doctor._try_pip_install", lambda cmd: False)

        results = [
            {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": "sentence-transformers → bm25 — MISSING: sentence-transformers",
                "fixable": True,
                "details": {
                    "chain": ["sentence-transformers", "bm25"],
                    "missing": ["sentence-transformers"],
                },
            }
        ]

        apply_fixes(palaia_root, results)
        config = json.loads((palaia_root / "config.json").read_text())
        # Should end up with bm25 only as absolute last resort
        assert config["embedding_chain"] == ["bm25"]
