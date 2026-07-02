import asyncio
import logging
from arq.connections import RedisSettings
from app.core.config import settings

# Import core synchronous processing functions
from app.services.conversation import process_inbound_message as core_inbound
from app.services.outbound import process_outbound_message as core_outbound

# Setup logging for the worker
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("worker")

async def process_inbound_message(ctx, payload: dict):
    logger.info(f"Worker starting inbound processing for lead: {payload.get('lead_id')}")
    # Run the synchronous function in a separate thread to avoid blocking the asyncio event loop
    await asyncio.to_thread(core_inbound, **payload)
    logger.info(f"Worker finished inbound processing for lead: {payload.get('lead_id')}")

async def process_outbound_message(ctx, payload: dict):
    logger.info(f"Worker starting outbound processing for lead: {payload.get('lead_id')}")
    await asyncio.to_thread(core_outbound, **payload)
    logger.info(f"Worker finished outbound processing for lead: {payload.get('lead_id')}")

class WorkerSettings:
    functions = [process_inbound_message, process_outbound_message]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 60  # LLM calls may take some time
