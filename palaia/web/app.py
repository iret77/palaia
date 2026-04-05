"""FastAPI application factory for the palaia WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(palaia_root: Path | None = None) -> "FastAPI":
    """Create and configure the FastAPI application.

    Args:
        palaia_root: Path to .palaia directory. Auto-detected if None.

    Raises:
        RuntimeError: if palaia is not initialized.
    """
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from palaia import __version__
    from palaia.config import find_palaia_root

    root = palaia_root or find_palaia_root()
    if root is None:
        raise RuntimeError("palaia not initialized. Run: palaia init")

    app = FastAPI(
        title="palaia Memory Explorer",
        description="Local memory browser for palaia",
        version=__version__,
        docs_url=None,  # no public docs page
        redoc_url=None,
    )
    app.state.palaia_root = root

    # Routes
    from palaia.web.routes.entries import router as entries_router
    from palaia.web.routes.search import router as search_router
    from palaia.web.routes.status import router as status_router

    app.include_router(status_router, prefix="/api")
    app.include_router(entries_router, prefix="/api")
    app.include_router(search_router, prefix="/api")

    # Static assets
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
