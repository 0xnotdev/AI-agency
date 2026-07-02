import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def send_whatsapp_message(phone_number_id: str, phone_number: str, text: str) -> dict:
    """
    Sends a message via the Meta WhatsApp Cloud API.
    Retries up to 3 times on transient failures.
    """
    if not settings.META_API_TOKEN:
        raise ValueError("META_API_TOKEN is not set.")
    
    if not phone_number_id:
        raise ValueError("phone_number_id is required to route WhatsApp message.")
    
    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.META_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": text}
    }
    
    response = httpx.post(url, headers=headers, json=payload, timeout=10.0)
    response.raise_for_status()
    return response.json()
