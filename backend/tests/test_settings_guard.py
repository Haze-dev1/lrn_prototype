"""Tests for the deployed-environment configuration guard.

``min_length`` on ``JWT_SECRET`` proves a value was supplied, not that it was chosen. The
placeholder in ``.env.example`` is long enough to satisfy it, so an operator who copies that file
and deploys would sign every access token with a key published in this repository. These tests
pin the one behaviour that makes that unshippable: the process refuses to start.
"""

import pytest
from pydantic import ValidationError

from core.config.settings import Settings

PLACEHOLDER_SECRET = "replace-with-a-32-byte-random-value-generated-per-environment"
REAL_SECRET = "K7f2p9QsdLm4Xv8ZrTnB1yHgWc6EjA3UoIe5NqYkRt0PwMsVbFxCzD"
DATABASE_URL = "postgresql+psycopg://lrn:s3cret@db:5432/lrn"
PLACEHOLDER_DATABASE_URL = "postgresql+psycopg://lrn:change-me-in-every-environment@db:5432/lrn"
REDIS_URL = "redis://redis:6379/0"


def build(**overrides: object) -> Settings:
    """
    Construct settings directly, ignoring any ``.env`` on disk.

    Args:
        **overrides: Values to override on the default valid configuration.

    Returns:
        Settings: The constructed settings.
    """
    values: dict[str, object] = {
        "ENVIRONMENT": "production",
        "JWT_SECRET": REAL_SECRET,
        "DATABASE_URL": DATABASE_URL,
        "REDIS_URL": REDIS_URL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestPlaceholderCredentials:
    """A deployed environment may not run on a credential published in this repository."""

    @pytest.mark.parametrize("environment", ["production", "staging"])
    def test_a_deployed_environment_refuses_the_published_secret(self, environment: str) -> None:
        """Refusing to boot is the only failure mode an operator cannot skip past."""
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            build(ENVIRONMENT=environment, JWT_SECRET=PLACEHOLDER_SECRET)

    def test_a_deployed_environment_refuses_the_published_database_password(self) -> None:
        """The database password ships in the same example file and matters just as much."""
        with pytest.raises(ValidationError, match="DATABASE_URL"):
            build(DATABASE_URL=PLACEHOLDER_DATABASE_URL)

    @pytest.mark.parametrize("environment", ["development", "test"])
    def test_local_environments_are_unaffected(self, environment: str) -> None:
        """A fixed local secret is convenient and worthless to an attacker with no deployment."""
        assert build(ENVIRONMENT=environment, JWT_SECRET=PLACEHOLDER_SECRET).JWT_SECRET

    def test_a_real_secret_boots_in_production(self) -> None:
        """The guard rejects the published value, not every value."""
        assert build().JWT_SECRET == REAL_SECRET
