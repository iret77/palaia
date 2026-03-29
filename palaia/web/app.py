"""FastAPI application factory for Palaia WebUI."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def create_app(palaia_root: Path | None = None) -> "FastAPI":  # noqa: F821
    """Create and configure the FastAPI application.

    Args:
        palaia_root: Path to .palaia directory. Auto-detected if None.
    """
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from palaia.config import find_palaia_root

    root = palaia_root or find_palaia_root()
    if root is None:
        raise RuntimeError(
            "Palaia not initialized. Run: palaia init"
        )

    app = FastAPI(
        title="Palaia Memory Explorer",
        description="Local memory browser for Palaia",
        version="0.1.0",
    )

    # Store root in app state for route access
    app.state.palaia_root = root

    # Register API routes
    from palaia.web.routes.entries import router as entries_router
    from palaia.web.routes.search import router as search_router
    from palaia.web.routes.status import router as status_router

    app.include_router(status_router, prefix="/api")
    app.include_router(entries_router, prefix="/api")
    app.include_router(search_router, prefix="/api")

    # Serve static files (HTML/JS/CSS)
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    logger.info("Palaia WebUI ready (root: %s)", root)
    return app
