import logging
from arq import create_pool
from arq.connections import RedisSettings
from app.core.config import settings

logger = logging.getLogger(__name__)

async def get_redis_pool():
    return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

async def enqueue_message_processing(payload: dict) -> None:
    """
    Enqueues a task to process an inbound message asynchronously via arq Redis queue.
    """
    try:
        redis = await get_redis_pool()
        job = await redis.enqueue_job('process_inbound_message', payload)
        if job:
            logger.info(f"Enqueued inbound task: {job.job_id}")
    except Exception as e:
        logger.error(f"Failed to enqueue task: {str(e)}")
        raise

async def enqueue_outbound_processing(payload: dict, schedule_time=None) -> None:
    """
    Enqueues a task to process an outbound reactivation message asynchronously via arq.
    schedule_time should be a datetime object indicating when to send it.
    """
    try:
        redis = await get_redis_pool()
        if schedule_time:
            job = await redis.enqueue_job('process_outbound_message', payload, _defer_until=schedule_time)
        else:
            job = await redis.enqueue_job('process_outbound_message', payload)
            
        if job:
            logger.info(f"Enqueued outbound task: {job.job_id} at {schedule_time}")
    except Exception as e:
        logger.error(f"Failed to enqueue outbound task: {str(e)}")
        raise
