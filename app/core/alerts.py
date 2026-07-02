import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def send_telegram_alert(message: str) -> None:
    """
    Send an alert to the global Telegram admin channel.
    Fails silently (with a log) if the Telegram API is unreachable or misconfigured,
    so that an alert failure doesn't crash the main process.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ADMIN_CHAT_ID:
        logger.warning("Telegram alerting skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID is not configured", extra={"alert_message": message})
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = httpx.post(url, json=payload, timeout=5.0)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {str(e)}", extra={"alert_message": message})
        raise e  # Reraise for tenacity to retry
