# Build stage for dependencies
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install --no-cache-dir poetry

# Copy shared package and install it
COPY packages/shared /build/packages/shared
RUN pip install --no-cache-dir /build/packages/shared

# Copy core service and install it
COPY services/core/pyproject.toml /build/services/core/
COPY services/core /build/services/core
WORKDIR /build/services/core
ARG INSTALL_ML=false
RUN rm -rf /build/services/core/.venv && poetry config virtualenvs.create false && poetry install --no-interaction --no-ansi --only main

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for TypeScript language servers (from Debian repos)
RUN apt-get update -qq && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Install pnpm for workspace-based test repositories (Node 20 → pnpm 9)
RUN npm install -g pnpm@9

# Install Playwright + Chromium for e2e test execution
RUN npm install -g @playwright/test@1.52.0 && \
    npx playwright install chromium && \
    npx playwright install-deps chromium 2>/dev/null || true

# Install Chromium browser dependencies for Playwright e2e tests
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

# Install Python and TypeScript language servers
RUN npm install -g typescript-language-server pyright

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Conditionally install ML packages at runtime stage
ARG INSTALL_ML=false
RUN if [ "$INSTALL_ML" = "true" ]; then \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir sentence-transformers rank-bm25; \
    fi

# Copy app code
COPY services/core/testsquad_core /app/testsquad_core
COPY services/core/alembic.ini /app/alembic.ini
COPY services/core/alembic /app/alembic

# Create cache directory for embedding model
RUN mkdir -p /root/.cache/torch/sentence_transformers

# Inject features.json based on ML build flag
ARG INSTALL_ML=false
RUN mkdir -p /etc/testsquad && \
    if [ "$INSTALL_ML" = "true" ]; then \
        echo '{"vector_matching": true, "llm": true}' > /etc/testsquad/features.json; \
    else \
        echo '{"vector_matching": false, "llm": false}' > /etc/testsquad/features.json; \
    fi

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "testsquad_core.main:app", "--host", "0.0.0.0", "--port", "8000"]