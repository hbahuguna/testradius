# TestRadius Factory Cell
#
# Hard constraints (E1-S1 / ADR-001 / ADR-002):
#   - Python 3.12 + Node 20 + Chromium only (no Firefox/WebKit)
#   - non-root uid 10001, no Docker socket, no UI/static assets
#   - the container is run with a read-only rootfs + cap_drop ALL (compose/helm)
FROM python:3.12-slim-bookworm

ARG NODE_VERSION=20.18.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Node 20 is needed for the Playwright runner stage the cell drives.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils tini \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY cell ./cell
RUN uv sync --frozen --no-dev \
    && /app/.venv/bin/playwright install --with-deps chromium \
    && rm -rf /root/.cache /var/lib/apt/lists/*

RUN groupadd --gid 10001 cell \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin cell \
    && mkdir -p /workspace /home/cell/.cache \
    && chown -R cell:cell /app /workspace /home/cell /ms-playwright

USER 10001
ENV PATH="/app/.venv/bin:${PATH}" \
    HOME=/home/cell

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "cell.main:app", "--host", "0.0.0.0", "--port", "8000"]
