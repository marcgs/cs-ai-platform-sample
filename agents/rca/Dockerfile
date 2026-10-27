# syntax=docker/dockerfile:1.10
# RCA agent image for Foundry hosted agents. Build from the repository root:
#   docker build -f agents/rca/Dockerfile -t rca-agent .
# To resolve packages through a mirror, pass it as a secret (it isn't stored in the image):
#   docker build --secret id=uv_index,env=UV_DEFAULT_INDEX -f agents/rca/Dockerfile -t rca-agent .
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.14-slim

ENV PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=uv /uv /bin/uv

WORKDIR /src
COPY . .

# Resolve and install only the agent and its dependencies; workspace packages become wheels.
RUN --mount=type=secret,id=uv_index,env=UV_DEFAULT_INDEX \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --package rca-agent --no-editable

WORKDIR /app
EXPOSE 8088
CMD ["/app/.venv/bin/python", "-m", "rca_agent.main"]
