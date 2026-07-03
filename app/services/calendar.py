import logging
import httpx
from datetime import datetime, timedelta, timezone
from tenacity import retry, stop_after_attempt, wait_exponential
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from dateutil import parser
from app.core.db import get_service_client

logger = logging.getLogger(__name__)

def _get_valid_credentials(calendar_tokens: dict, client_id: str) -> Credentials:
    """Helper to get valid credentials, refreshing and saving if necessary."""
    
    # Parse expiry if it exists
    expiry = None
    if calendar_tokens.get("expiry"):
        expiry = datetime.fromisoformat(calendar_tokens.get("expiry").replace('Z', '+00:00'))
        
    creds = Credentials(
        token=calendar_tokens.get("token"),
        refresh_token=calendar_tokens.get("refresh_token"),
        token_uri=calendar_tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=calendar_tokens.get("client_id"),
        client_secret=calendar_tokens.get("client_secret"),
        scopes=calendar_tokens.get("scopes", ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.readonly"]),
        expiry=expiry
    )
    
    # If expiry is None, creds.expired is False. We must treat None as expired to force a refresh.
    is_expired = creds.expired if creds.expiry else True
    
    if is_expired and creds.refresh_token:
        logger.info(f"Refreshing Google Calendar tokens for client {client_id}")
        creds.refresh(GoogleAuthRequest())
        
        # Save refreshed token to DB
        tokens_dict = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "expiry": creds.expiry.isoformat() if creds.expiry else None
        }
        service = get_service_client()
        service.table("client_configs").update({
            "google_calendar_tokens": tokens_dict
        }).eq("client_id", client_id).execute()
        
    return creds

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def check_availability(calendar_tokens: dict, client_id: str, start_time: str, end_time: str) -> list[str]:
    """
    Checks the client's Google Calendar FreeBusy API to find available 30-minute slots.
    Returns a list of available start times in ISO format.
    start_time and end_time should be ISO 8601 strings (e.g. 2026-07-04T09:00:00Z)
    """
    if not calendar_tokens:
        raise ValueError("No calendar tokens provided for client.")
        
    creds = _get_valid_credentials(calendar_tokens, client_id)
    
    # Convert string to datetime and ensure they are timezone-aware using a robust parser
    try:
        dt_start = parser.parse(start_time)
    except Exception:
        # Fallback if parser completely fails
        dt_start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        
    if dt_start.tzinfo is None:
        dt_start = dt_start.replace(tzinfo=timezone.utc)
        
    try:
        dt_end = parser.parse(end_time)
    except Exception:
        dt_end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        
    if dt_end.tzinfo is None:
        dt_end = dt_end.replace(tzinfo=timezone.utc)
        
    payload = {
        "timeMin": dt_start.isoformat(),
        "timeMax": dt_end.isoformat(),
        "timeZone": "UTC",
        "items": [{"id": "primary"}]
    }
    
    url = "https://www.googleapis.com/calendar/v3/freeBusy"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }
    
    response = httpx.post(url, headers=headers, json=payload, timeout=10.0)
    response.raise_for_status()
    data = response.json()
    
    busy_slots = data.get("calendars", {}).get("primary", {}).get("busy", [])
    
    # Generate 30-minute slots between start and end
    available_slots = []
    current_slot = dt_start
    
    while current_slot + timedelta(minutes=30) <= dt_end:
        slot_end = current_slot + timedelta(minutes=30)
        is_free = True
        
        # Check against busy slots
        for busy in busy_slots:
            b_start = datetime.fromisoformat(busy["start"].replace('Z', '+00:00'))
            b_end = datetime.fromisoformat(busy["end"].replace('Z', '+00:00'))
            
            # If current slot overlaps with busy slot, it's not free
            if (current_slot < b_end) and (slot_end > b_start):
                is_free = False
                break
                
        if is_free:
            available_slots.append(current_slot.isoformat())
            
        current_slot += timedelta(minutes=30)
        
    return available_slots

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def book_calendar_event(calendar_tokens: dict, client_id: str, lead_name: str, lead_phone: str, start_time: str, end_time: str, meeting_summary: str = None) -> str:
    """
    Books a calendar event using the client's stored OAuth tokens.
    start_time and end_time should be ISO 8601 strings.
    Returns the event htmlLink.
    """
    if not calendar_tokens:
        raise ValueError("No calendar tokens provided for client.")
        
    creds = _get_valid_credentials(calendar_tokens, client_id)
    
    event_payload = {
        "summary": meeting_summary if meeting_summary else f"Meeting with {lead_name}",
        "description": f"Lead Phone: {lead_phone}\nBooked by LeadRecover AI",
        "start": {
            "dateTime": start_time,
        },
        "end": {
            "dateTime": end_time,
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
    return event_data.get("htmlLink", "Event created successfully")
