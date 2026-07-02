from fastapi import APIRouter, Response, status
from app.core.db import get_service_client
from app.core.logging import logger

router = APIRouter()

@router.get("/health")
async def health_check(response: Response):
    """
    Health check endpoint.
    Verifies connectivity to the Supabase database.
    """
    try:
        # Simple query to verify DB connectivity
        service_client = get_service_client()
        service_client.table("clients").select("id").limit(1).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error("Health check failed", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "Database unavailable"}
