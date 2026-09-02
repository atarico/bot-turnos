# syntax=docker/dockerfile:1

# Build and runtime are split so the final image carries the virtualenv and the
# source, and nothing else: no uv, no compiler, no lockfile, no build cache.

FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, on their own layer. They change far less often than the
# code, so editing bot.py does not reinstall FastAPI.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.14-slim AS runtime

# Never root. A webhook is a public entry point, and this process has no reason
# to be able to write anywhere outside its own virtualenv.
RUN useradd --create-home --uid 10001 bot
WORKDIR /app

COPY --from=builder --chown=bot:bot /app/.venv /app/.venv
COPY --from=builder --chown=bot:bot /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER bot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health')"

# The platform picks the port: Railway, Render and Cloud Run all inject PORT.
# Shell form on purpose, because that variable has to be expanded at start.
CMD ["sh", "-c", "uvicorn bot.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
