"""Application configuration loaded from environment variables.

Settings are read once at import time and cached, so configuration errors surface at process
start rather than on the first request that needs a missing value.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Substrings that appear only in the example values shipped in `.env.example`. A deployed
# environment carrying any of them is running on a credential that is public in this repository.
_PLACEHOLDER_MARKERS = ("replace-with", "change-me", "changeme")


class Settings(BaseSettings):
    """Environment-driven application settings.

    Every value has an explicit environment variable name; secrets have no default so a
    misconfigured deployment fails loudly instead of running with a placeholder credential.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    # --- Runtime -------------------------------------------------------------------
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"
    APP_NAME: str = "LRN API"
    API_V1_PREFIX: str = "/v1"

    # --- Datastores ----------------------------------------------------------------
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5
    DATABASE_POOL_TIMEOUT: int = 30
    REDIS_URL: RedisDsn

    # --- Web / CORS ----------------------------------------------------------------
    PUBLIC_WEB_URL: str = "http://localhost:8080"
    CORS_ORIGINS: list[str] = Field(default_factory=list)

    # --- Auth ----------------------------------------------------------------------
    JWT_SECRET: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    ACCESS_COOKIE_NAME: str = "lrn_access"
    REFRESH_COOKIE_NAME: str = "lrn_refresh"
    # Left unset outside production so cookies work over plain HTTP locally; a Secure cookie is
    # silently dropped by the browser on an http:// origin, which looks like a broken login.
    COOKIE_SECURE: bool | None = None
    COOKIE_DOMAIN: str | None = None

    # Google sign-in. Only the client ID is needed: the browser obtains the ID token and the
    # server verifies its signature against Google's public keys, so no client secret is held.
    GOOGLE_CLIENT_ID: str | None = None

    # --- Rate limiting -------------------------------------------------------------
    # Two buckets, because the users are university students who overwhelmingly share campus NAT
    # addresses. A single tight per-IP limit would lock out an entire university the moment a few
    # people mistyped a password. The per-IP limit is therefore generous and only stops crude
    # floods, while the tight limit is per account — which is what actually blocks password
    # guessing, and which no amount of IP rotation can evade.
    LOGIN_RATE_LIMIT_PER_IP: int = 60
    LOGIN_RATE_LIMIT_PER_ACCOUNT: int = 8
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900
    REGISTER_RATE_LIMIT_PER_IP: int = 20
    REGISTER_RATE_LIMIT_WINDOW_SECONDS: int = 3600

    # --- AI grading ----------------------------------------------------------------
    GRADING_PROVIDER: Literal["groq", "openrouter", "fake"] = "fake"
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Model identifiers are provider-scoped, so this has to change with GRADING_PROVIDER. The
    # default names a Groq model because Groq is what a configured deployment uses; a router
    # deployment overrides both together.
    GRADING_MODEL: str = "openai/gpt-oss-120b"
    GRADING_TIMEOUT_SECONDS: float = 45.0
    GRADING_MAX_RETRIES: int = 2
    # How long an attempt must sit unresolved before the retry sweep claims it. Must exceed the
    # grading timeout, or the sweep would pick up an attempt the request that created it is still
    # grading, and one answer would be graded twice at double the cost.
    GRADING_RETRY_AFTER_SECONDS: int = 120
    # Total grading calls one answer is worth before it is abandoned as FAILED. Bounds the spend
    # on an answer that fails repeatedly, which is usually a content or configuration problem
    # rather than a transient one.
    GRADING_MAX_LIFETIME_RETRIES: int = 5

    # --- Billing -------------------------------------------------------------------
    # Stripe is the only payment provider. Nothing here has a default: a placeholder key would
    # let a deployment start believing it can take money, and discover otherwise at checkout.
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_PRO_MONTHLY: str | None = None
    STRIPE_PRICE_SEASON_PASS: str | None = None
    # How long a Season Pass grants access for. A recruiting season, not a subscription: the
    # window is fixed at purchase so the student knows exactly what they bought.
    SEASON_PASS_DAYS: int = 120

    # --- Email ---------------------------------------------------------------------
    # 'log' writes the message to the application log and sends nothing, so a fresh clone works
    # and no test can post to a real inbox. Unlike payments, a fake here is safe: sending nothing
    # grants nothing.
    EMAIL_PROVIDER: Literal["resend", "log"] = "log"
    RESEND_API_KEY: str | None = None
    RESEND_BASE_URL: str = "https://api.resend.com"
    EMAIL_FROM: str = "LRN <no-reply@lrn.local>"
    EMAIL_REPLY_TO: str | None = None
    EMAIL_TIMEOUT_SECONDS: float = 15.0
    # Minimum gap between weak-area nudges for one student. The job runs weekly, but the gap is
    # enforced per recipient so a re-run, a backfill, or a second replica cannot double-send.
    NUDGE_MIN_INTERVAL_DAYS: int = 7
    # A student with no graded evidence has nothing to be nudged about; a nudge that says
    # "practise your weakest area" to someone who has no measured areas is spam.
    NUDGE_MIN_GRADED_ATTEMPTS: int = 3

    # --- Analytics -----------------------------------------------------------------
    # 'log' records events locally and makes no network call. Analytics must never be able to
    # fail a request, so every provider is fire-and-forget.
    ANALYTICS_PROVIDER: Literal["posthog", "log", "none"] = "log"
    POSTHOG_API_KEY: str | None = None
    POSTHOG_HOST: str = "https://eu.i.posthog.com"
    ANALYTICS_TIMEOUT_SECONDS: float = 5.0

    # --- Free tier -----------------------------------------------------------------
    # The free tier exists to prove the product works, not to be a usable product. One
    # diagnostic, a few practice sets, and a daily cap on paid grading calls. Every limit is
    # enforced server-side; the interface only mirrors what the API already decided.
    FREE_PRACTICE_SESSIONS: int = 3
    FREE_DAILY_GRADED_ATTEMPTS: int = 15

    @model_validator(mode="after")
    def _reject_published_placeholders(self) -> "Settings":
        """
        Refuse to start a deployed environment on a credential published in this repository.

        ``min_length`` on ``JWT_SECRET`` catches an empty value but not a copied one, and the
        placeholder in ``.env.example`` is deliberately long enough to be a plausible secret. An
        operator who copies that file and deploys would be signing every access token with a key
        anyone who has read the repository already knows, which is total authentication bypass
        for that deployment. Refusing to boot is the only failure mode that cannot be missed —
        a warning in a log nobody reads is how this ships.

        Development and test are exempt: a fixed local secret is convenient and worthless to an
        attacker who has no deployment to attack.

        Returns:
            Settings: The validated settings, unchanged.

        Raises:
            ValueError: A deployed environment is configured with a published placeholder.
        """
        if self.ENVIRONMENT not in ("production", "staging"):
            return self

        offenders = [
            name
            for name, value in (
                ("JWT_SECRET", self.JWT_SECRET),
                ("DATABASE_URL", str(self.DATABASE_URL)),
            )
            if any(marker in value.lower() for marker in _PLACEHOLDER_MARKERS)
        ]
        if offenders:
            raise ValueError(
                f"{', '.join(offenders)} still carries the placeholder value published in "
                f".env.example. Generate a real value per environment "
                f"(`openssl rand -base64 48`) before deploying to {self.ENVIRONMENT}."
            )
        return self

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """
        Accept a comma-separated CORS origin list from the environment.

        Environment variables are strings, so a comma-separated form is normalised into the list
        the application expects while leaving an already-parsed list untouched.

        Args:
            value: Raw environment value, either a comma-separated string or a list.

        Returns:
            object: A list of origin strings, or the original value when not a string.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def cookie_secure(self) -> bool:
        """
        Report whether auth cookies should carry the Secure attribute.

        Defaults to on in production and off elsewhere, because a Secure cookie is dropped by the
        browser over plain HTTP and would present as a login that silently never persists.

        Returns:
            bool: True when cookies must be sent over HTTPS only.
        """
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.is_production

    @property
    def google_enabled(self) -> bool:
        """
        Report whether Google sign-in is configured.

        Lets the API answer "this sign-in method is not available" deliberately rather than
        failing deep inside token verification with a confusing error.

        Returns:
            bool: True when a Google client ID is configured.
        """
        return bool(self.GOOGLE_CLIENT_ID)

    @property
    def email_enabled(self) -> bool:
        """
        Report whether email can actually be delivered to a real inbox.

        False for the log provider, which is the default. Callers use it to decide whether to
        promise a student an email — telling someone "check your inbox" when the deployment sends
        nothing is worse than saying nothing at all.

        Returns:
            bool: True when a sending provider is configured.
        """
        return self.EMAIL_PROVIDER == "resend" and bool(self.RESEND_API_KEY)

    @property
    def billing_enabled(self) -> bool:
        """
        Report whether payments can actually be taken.

        Checkout needs a secret key and at least one configured price. Asking this up front lets
        the API answer "billing is not configured" deliberately instead of surfacing a Stripe
        error to a student who was trying to pay.

        Returns:
            bool: True when Stripe is configured well enough to sell something.
        """
        return bool(self.STRIPE_SECRET_KEY) and bool(
            self.STRIPE_PRICE_PRO_MONTHLY or self.STRIPE_PRICE_SEASON_PASS
        )

    @property
    def webhook_verification_enabled(self) -> bool:
        """
        Report whether Stripe webhook signatures can be verified.

        Separate from ``billing_enabled`` because the webhook endpoint must refuse every request
        when no signing secret is configured. An unverified payment event is not a payment event,
        and processing one would write an entitlement from an anonymous POST.

        Returns:
            bool: True when a webhook signing secret is configured.
        """
        return bool(self.STRIPE_WEBHOOK_SECRET)

    @property
    def is_production(self) -> bool:
        """
        Report whether the process is running with production configuration.

        Used to gate development-only affordances such as interactive API documentation.

        Returns:
            bool: True when ENVIRONMENT is ``production``.
        """
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached application settings instance.

    Cached so environment parsing and validation happen exactly once per process.

    Returns:
        Settings: Validated application settings.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
