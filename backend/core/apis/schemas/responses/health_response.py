"""Response schemas for health and readiness endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class DependencyHealth(BaseModel):
    """Health state of a single backing service."""

    name: str = Field(description="Dependency name, for example 'postgres' or 'redis'.")
    healthy: bool = Field(description="Whether the dependency responded successfully.")


class HealthResponse(BaseModel):
    """Aggregate service health payload.

    Deliberately carries no version, hostname, or configuration detail: the endpoint is
    unauthenticated and must not become a reconnaissance surface.
    """

    status: Literal["healthy", "degraded"] = Field(
        description="'healthy' when every dependency responded, otherwise 'degraded'."
    )
    service: str = Field(description="Name of the reporting service.")
    dependencies: list[DependencyHealth] = Field(description="Per-dependency health results.")


class LivenessResponse(BaseModel):
    """Liveness payload indicating the process is running and able to serve requests."""

    status: Literal["alive"] = Field(description="Always 'alive' when the process responds.")
