"""Tests for the health and readiness endpoints."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_liveness_reports_alive(client: AsyncClient) -> None:
    """Liveness returns 200 without touching any backing service."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@patch("core.controllers.health_controller.check_redis_connection", new_callable=AsyncMock)
@patch("core.controllers.health_controller.check_database_connection", new_callable=AsyncMock)
async def test_readiness_healthy_when_all_dependencies_up(
    mock_database: AsyncMock, mock_redis: AsyncMock, client: AsyncClient
) -> None:
    """Readiness returns 200 and 'healthy' when every dependency responds."""
    mock_database.return_value = True
    mock_redis.return_value = True

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert {item["name"] for item in payload["dependencies"]} == {"postgres", "redis"}
    assert all(item["healthy"] for item in payload["dependencies"])


@patch("core.controllers.health_controller.check_redis_connection", new_callable=AsyncMock)
@patch("core.controllers.health_controller.check_database_connection", new_callable=AsyncMock)
async def test_readiness_degrades_with_503_when_database_down(
    mock_database: AsyncMock, mock_redis: AsyncMock, client: AsyncClient
) -> None:
    """A failing dependency yields 503 while still naming which dependency is unhealthy."""
    mock_database.return_value = False
    mock_redis.return_value = True

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    unhealthy = [item["name"] for item in payload["dependencies"] if not item["healthy"]]
    assert unhealthy == ["postgres"]


async def test_health_response_exposes_no_environment_detail(client: AsyncClient) -> None:
    """The unauthenticated health payload must not leak version or configuration detail."""
    response = await client.get("/health")

    assert set(response.json().keys()) == {"status"}
