import time
import uuid
import traceback
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.api import webhooks, health, admin, auth
from app.core.logging import setup_logging, logger

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Lead Response Platform")

# Register routers
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(auth.router)

# Middleware for structured access logging and latency
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    
    logger.info(
        "Request processed",
        extra={
            "endpoint": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "latency_ms": round(process_time, 2),
        }
    )
    return response

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches all unhandled exceptions so the process never crashes on a single bad request.
    Logs full context and returns a clean 500 JSON response.
    """
    error_id = str(uuid.uuid4())
    logger.error(
        "Unhandled exception",
        extra={
            "error_id": error_id,
            "endpoint": request.url.path,
            "method": request.method,
            "error": str(exc),
            "traceback": traceback.format_exc()
        }
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Internal server error", "error_id": error_id}
    )

# Pydantic validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on request", extra={
        "endpoint": request.url.path,
        "errors": exc.errors()
    })
    return JSONResponse(
        status_code=422,
        content={"status": "error", "detail": "Unprocessable Entity", "errors": exc.errors()}
    )

