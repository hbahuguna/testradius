FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

RUN pip install --no-cache-dir \
    fastapi>=0.135.1 \
    uvicorn[standard]>=0.41.0 \
    pydantic>=2.12.5 \
    httpx>=0.28.1 \
    jinja2>=3.1.3 \
    beautifulsoup4>=4.12.0 \
    lxml>=5.1.0 \
    playwright>=1.58.0

RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
    transformers>=4.49.0 \
    sentencepiece>=0.2.0 \
    accelerate>=1.3.0

RUN playwright install chromium && \
    playwright install-deps chromium 2>/dev/null || true

COPY services/workbench /app/services/workbench
COPY packages/shared /app/packages/shared

RUN pip install --no-cache-dir /app/packages/shared

ENV PYTHONPATH=/app/services/workbench:/app/packages/shared

EXPOSE 8002

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8002"]
