FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY license_server ./license_server

RUN pip install --no-cache-dir .

EXPOSE 8100

CMD ["uvicorn", "license_server.app:app", "--host", "0.0.0.0", "--port", "8100"]
