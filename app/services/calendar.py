import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def book_calendar_event(calendar_tokens: dict, lead_name: str, lead_phone: str) -> str:
    """
    Books a calendar event using the client's stored OAuth tokens.
    Automatically refreshes the token if expired using google-auth.
    Returns the event summary or link.
    """
    if not calendar_tokens:
        raise ValueError("No calendar tokens provided for client.")
        
    creds = Credentials(
        token=calendar_tokens.get("access_token"),
        refresh_token=calendar_tokens.get("refresh_token"),
        token_uri=calendar_tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=calendar_tokens.get("client_id"),
        client_secret=calendar_tokens.get("client_secret"),
        scopes=["https://www.googleapis.com/auth/calendar.events"]
    )
    
    # Refresh token if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        # In a complete implementation, we would write the new creds.token back to the DB here.
        
    start_time = datetime.utcnow() + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)
    
    event_payload = {
        "summary": f"Meeting with {lead_name}",
        "description": f"Lead Phone: {lead_phone}",
        "start": {
            "dateTime": start_time.isoformat() + "Z",
        },
        "end": {
            "dateTime": end_time.isoformat() + "Z",
        }
    }
    
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }
    
    response = httpx.post(url, headers=headers, json=event_payload, timeout=10.0)
    response.raise_for_status()
    
    event_data = response.json()
    return event_data.get("htmlLink", "Event created")
