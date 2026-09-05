"""Runtime entrypoint for the LRN API.

Exposes the ASGI ``app`` for the container command and supports direct execution for local runs.
"""

import uvicorn

from core.apis.api import app
from core.config.settings import settings

__all__ = ["app"]


def main() -> None:
    """
    Start the API with Uvicorn using environment-driven configuration.

    Reload is enabled outside production so local edits apply without a container restart.
    """
    uvicorn.run(
        "core.apis.api:app",
        host="0.0.0.0",  # noqa: S104 — container-internal; exposure is controlled by Compose
        port=8000,
        reload=not settings.is_production,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
