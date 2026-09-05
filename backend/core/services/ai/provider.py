"""The grading provider boundary.

``GradingService`` depends on this interface and nothing below it. A provider's only job is to
send a prompt somewhere and return what came back, along with the accounting the audit trail
needs; it does not know what a rubric is, does not validate content, and does not decide whether
a failure is worth retrying beyond classifying it.

Keeping the boundary this narrow is what makes the provider replaceable. Swapping OpenRouter for
a direct vendor API, a self-hosted model, or a different router should touch exactly one file.
"""

from abc import ABC, abstractmethod
from typing import Any

from core import logger
from core.config.settings import settings
from core.services.ai.types import ProviderCall

logging = logger(__name__)


class GradingProvider(ABC):
    """Sends a grading prompt to a model and returns the raw response."""

    #: Stable identifier recorded on every grade event.
    name: str

    @abstractmethod
    async def complete(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> ProviderCall:
        """
        Send one grading prompt and return the model's raw response.

        Args:
            system_prompt: The grading instructions.
            user_prompt: The rubric and the fenced student answer.
            json_schema: Schema the response content must conform to.

        Returns:
            ProviderCall: Raw content plus usage, latency, and identity for the audit trail.

        Raises:
            GradingError: If the call could not be completed or returned no usable content.
        """

    @property
    def model(self) -> str:
        """
        Return the configured model identifier.

        Read from settings rather than hard-coded, so changing models is a deployment change and
        model names never appear in business logic.

        Returns:
            str: Model identifier.
        """
        return settings.GRADING_MODEL


def get_grading_provider() -> GradingProvider:
    """
    Build the grading provider named by configuration.

    Imports are local to the branch taken so a deployment configured for one provider does not
    import the other's client, and so the fake provider carries no cost of existing in production.

    Returns:
        GradingProvider: The configured provider.

    Raises:
        GradingError: If the configured provider is not usable, for example OpenRouter with no
            API key.
    """
    if settings.GRADING_PROVIDER == "openrouter":
        from core.services.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider()

    from core.services.ai.fake_provider import FakeGradingProvider

    logging.info("Using the deterministic fake grading provider")
    return FakeGradingProvider()
