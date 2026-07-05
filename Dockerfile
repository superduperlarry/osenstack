# One image, many roles — the entrypoint selects api | mcp | worker.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
RUN useradd --create-home enos
COPY --from=builder --chown=enos:enos /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
USER enos
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]
