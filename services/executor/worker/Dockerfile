FROM python:3.11-slim

# Install system dependencies for Playwright and git
RUN apt-get update && apt-get install -y \
    git \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python testing dependencies
RUN pip install --no-cache-dir \
    pytest \
    pytest-mock \
    pytest-asyncio \
    pytest-cov \
    coverage \
    httpx \
    requests \
    SQLModel \
    sqlalchemy \
    neo4j \
    pydantic \
    fastapi \
    gitpython \
    pyyaml

# Install smother for per-test coverage tracking
RUN pip install --no-cache-dir smother || true

WORKDIR /app

# The executor will mount the code to /app
# and provide the command to run.

CMD ["python", "--version"]
