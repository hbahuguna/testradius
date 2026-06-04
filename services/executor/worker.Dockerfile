FROM python:3.11-slim

WORKDIR /app

# Install common testing tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    playwright \
    pydantic \
    httpx

# Default command
CMD ["python", "--version"]
