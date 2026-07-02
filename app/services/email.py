import logging
import resend
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def send_email_reply(to_email: str, subject: str, text: str) -> dict:
    """
    Sends an email using the Resend API.
    Retries up to 3 times on transient failures.
    """
    if not settings.RESEND_API_KEY:
        raise ValueError("RESEND_API_KEY is not set.")
        
    resend.api_key = settings.RESEND_API_KEY
    
    # In a real app, the sender email might be dynamic per client.
    # We use a placeholder or generic domain for the foundation.
    sender = "bot@example.com"
    
    payload = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": text
    }
    
    # The resend python SDK uses httpx under the hood and raises exceptions on failure
    response = resend.Emails.send(payload)
    return response
