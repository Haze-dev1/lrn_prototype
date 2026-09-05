# syntax=docker/dockerfile:1

# Dependencies are installed in a separate stage so application edits do not invalidate the
# dependency layer on rebuild.
FROM python:3.13-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1001 lrn \
    && useradd --system --uid 1001 --gid lrn --create-home lrn

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
COPY --chown=lrn:lrn . .

# The application runs unprivileged so a compromised process cannot write to the image or
# escalate inside the container.
USER lrn

EXPOSE 8000
CMD ["uvicorn", "core.apis.api:app", "--host", "0.0.0.0", "--port", "8000"]
