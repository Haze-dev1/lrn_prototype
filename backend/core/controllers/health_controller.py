"""Health check orchestration."""

from commons.redis_client import check_redis_connection
from core import logger
from core.config.settings import settings
from core.database.database import check_database_connection

logging = logger(__name__)


class HealthController:
    """Aggregates readiness of the backing services the API depends on."""

    async def get_readiness(self) -> dict:
        """
        Check every backing service and summarise overall readiness.

        Reports 'degraded' rather than raising when a dependency is down, so orchestrators can
        distinguish a running-but-unready process from a crashed one.

        Returns:
            dict: Readiness payload with per-dependency results.
        """
        logging.info("Executing HealthController.get_readiness")
        dependencies = [
            {"name": "postgres", "healthy": await check_database_connection()},
            {"name": "redis", "healthy": await check_redis_connection()},
        ]

        unhealthy = [item["name"] for item in dependencies if not item["healthy"]]
        if unhealthy:
            logging.warning(f"Readiness degraded, unhealthy dependencies: {unhealthy}")

        return {
            "status": "degraded" if unhealthy else "healthy",
            "service": settings.APP_NAME,
            "dependencies": dependencies,
        }
