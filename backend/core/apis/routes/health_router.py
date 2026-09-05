"""Health and readiness endpoints.

These routes are unauthenticated by design so container orchestration can reach them, and
therefore return no environment or version detail.
"""

from fastapi import APIRouter, HTTPException, Response, status

from core import logger
from core.apis.schemas.responses.health_response import HealthResponse, LivenessResponse
from core.controllers.health_controller import HealthController

health_router = APIRouter()
logging = logger(__name__)


@health_router.get("/health", status_code=status.HTTP_200_OK, response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """
    Report that the API process is alive.

    Performs no dependency I/O, so a slow database cannot cause the process to be restarted by a
    liveness probe.

    Returns:
        LivenessResponse: Static liveness payload.
    """
    return LivenessResponse(status="alive")


@health_router.get("/health/ready", response_model=HealthResponse)
async def readiness(response: Response) -> HealthResponse:
    """
    Report readiness of the API and its backing services.

    Returns HTTP 503 with a 'degraded' body when any dependency is unreachable, so load balancers
    stop routing traffic while the payload still names the failing dependency.

    Args:
        response: FastAPI response used to set a 503 status when degraded.

    Returns:
        HealthResponse: Aggregate readiness payload.

    Raises:
        HTTPException 500: Unexpected failure while collecting readiness.
    """
    try:
        logging.info("Calling GET /health/ready endpoint")
        result = await HealthController().get_readiness()
        if result["status"] == "degraded":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in GET /health/ready endpoint: {httperror}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /health/ready endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        ) from error
