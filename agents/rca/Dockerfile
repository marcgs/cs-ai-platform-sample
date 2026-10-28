# RCA agent image for Foundry hosted agents. Build from the repository root:
#   docker build -f agents/rca/Dockerfile -t rca-agent .
# azd builds it remotely in the registry (ACR Tasks, classic builder: no BuildKit features).
# Third-party packages are installed from requirements.lock.txt, exported from the local
# uv.lock by the prepackage hook (pinned with hashes, no index URLs), so the image runs the
# versions that were tested locally.
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.14-slim

ENV PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /bin/uv

WORKDIR /src
COPY . .

RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python --require-hashes \
        -r agents/rca/requirements.lock.txt \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        packages/cs-platform agents/rca \
    # Fail the build, not the hosted session, on missing modules.
    && /app/.venv/bin/python -c "import mcp, tenacity, rca_agent.main"

WORKDIR /app
EXPOSE 8088
CMD ["/app/.venv/bin/python", "-m", "rca_agent.main"]
