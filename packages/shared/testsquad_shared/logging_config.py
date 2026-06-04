import logging
import sys
import time
import uuid
import json
import traceback
from typing import Callable
from fastapi import Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

# Configure standard logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("testsquad")

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        start_time = time.time()
        
        # Log request basic info
        headers_to_log = {k: "********" if "key" in k.lower() or "token" in k.lower() or "auth" in k.lower() else v 
                          for k, v in request.headers.items()}
        logger.info(f"[{request_id}] Incoming {request.method} {request.url.path} | Headers: {headers_to_log}")
        
        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000
            logger.info(f"[{request_id}] Completed {request.method} {request.url.path} - Status {response.status_code} - {process_time:.2f}ms")
            return response
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.error(f"[{request_id}] Unhandled Exception: {str(e)}\n{traceback.format_exc()}")
            return Response(
                content=json.dumps({"detail": "Internal Server Error", "request_id": request_id}),
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="application/json"
            )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"[{request_id}] Validation Error: {exc.errors()}\n"
        f"URL: {request.url}"
    )
    return Response(
        content=json.dumps({"detail": exc.errors()}),
        status_code=400,
        media_type="application/json"
    )

async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"[{request_id}] HTTP {exc.status_code}: {exc.detail}")
    return Response(
        content=json.dumps({"detail": exc.detail}),
        status_code=exc.status_code,
        media_type="application/json"
    )

def setup_logging(app):
    app.add_middleware(LoggingMiddleware)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    logger.info("TestSquad Standardized Logging Initialized.")
