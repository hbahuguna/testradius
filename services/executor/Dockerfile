# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Copy shared package and install it
COPY packages/shared /build/packages/shared
RUN pip install --no-cache-dir /build/packages/shared

# Copy executor service and install it
COPY services/executor /build/services/executor
WORKDIR /build/services/executor
RUN pip install --no-cache-dir .

# Runtime stage
FROM python:3.11-slim

# Install git since executor needs it to clone repos
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code
COPY services/executor/src/testsquad_executor /app/testsquad_executor
COPY services/executor/src/main.py /app/main.py

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
