import secrets
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.core.config import settings
from app.core.db import get_service_client

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBasic()

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify operator password via HTTP Basic Auth."""
    if not secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# ---------------------------------------------------------------------------
# Pydantic models for request bodies
# ---------------------------------------------------------------------------

class ConfigUpdate(BaseModel):
    business_name: str | None = None
    niche: str | None = None
    services: dict | None = None
    pricing_notes: dict | None = None
    faq: dict | None = None
    tone_instructions: str | None = None
    booking_link: str | None = None
    outbound_offer: str | None = None
    whatsapp_phone_number_id: str | None = None
    inbound_email_address: str | None = None

class StatusUpdate(BaseModel):
    status: str

# ---------------------------------------------------------------------------
# Dashboard HTML serving (read at request time per user requirement)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(credentials: HTTPBasicCredentials = Depends(security)):
    """Serve the operator dashboard. Protected by Basic Auth."""
    if not secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    html_path = STATIC_DIR / "dashboard.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Dashboard file not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@router.get("/client/{dashboard_token}", response_class=HTMLResponse)
async def serve_client_view(dashboard_token: str):
    """Serve the client-facing read-only view. Token in URL is the security."""
    service = get_service_client()
    client_resp = service.table("clients").select("id").eq("dashboard_token", dashboard_token).execute()
    if not client_resp.data:
        raise HTTPException(status_code=404, detail="Client not found")
    html_path = STATIC_DIR / "client_view.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Client view file not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Admin API endpoints (all protected by verify_admin)
# ---------------------------------------------------------------------------

@router.get("/admin/clients")
async def list_clients(auth: bool = Depends(verify_admin)):
    """List all clients with their configs."""
    service = get_service_client()
    clients = service.table("clients").select("*").order("created_at", desc=True).execute()
    configs = service.table("client_configs").select("*").execute()
    
    config_map = {c["client_id"]: c for c in configs.data}
    result = []
    for client in clients.data:
        client["config"] = config_map.get(client["id"], {})
        result.append(client)
    return {"clients": result}

@router.patch("/admin/clients/{client_id}/config")
async def update_client_config(client_id: str, update: ConfigUpdate, auth: bool = Depends(verify_admin)):
    """Update client config fields. Also updates business_name/niche on clients table if provided."""
    service = get_service_client()
    
    # Update fields on the clients table if provided
    client_fields = {}
    if update.business_name is not None:
        client_fields["business_name"] = update.business_name
    if update.niche is not None:
        client_fields["niche"] = update.niche
    if client_fields:
        service.table("clients").update(client_fields).eq("id", client_id).execute()
    
    # Update fields on client_configs table
    config_fields = update.model_dump(exclude_none=True, exclude={"business_name", "niche"})
    if config_fields:
        service.table("client_configs").update(config_fields).eq("client_id", client_id).execute()
    
    return {"status": "updated"}

@router.patch("/admin/clients/{client_id}/status")
async def toggle_client_status(client_id: str, update: StatusUpdate, auth: bool = Depends(verify_admin)):
    """Toggle client status between active/paused."""
    if update.status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'paused'")
    service = get_service_client()
    service.table("clients").update({"status": update.status}).eq("id", client_id).execute()
    return {"status": update.status}

@router.get("/admin/clients/{client_id}/leads")
async def list_client_leads(client_id: str, status_filter: str | None = None, auth: bool = Depends(verify_admin)):
    """List leads for a client with optional status filter."""
    service = get_service_client()
    query = service.table("leads").select("*").eq("client_id", client_id).order("created_at", desc=True)
    if status_filter:
        query = query.eq("status", status_filter)
    leads = query.execute()
    return {"leads": leads.data, "count": len(leads.data)}

@router.get("/admin/clients/{client_id}/conversations")
async def list_client_conversations(client_id: str, auth: bool = Depends(verify_admin)):
    """List conversations for a client with last message preview."""
    service = get_service_client()
    conversations = service.table("conversations").select("*, leads(name, phone, email)").eq("client_id", client_id).order("id", desc=True).execute()
    
    result = []
    for conv in conversations.data:
        # Get last message for preview
        last_msg = service.table("messages").select("content, direction, created_at").eq("conversation_id", conv["id"]).order("created_at", desc=True).limit(1).execute()
        conv["last_message"] = last_msg.data[0] if last_msg.data else None
        result.append(conv)
    
    return {"conversations": result}

@router.get("/admin/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, auth: bool = Depends(verify_admin)):
    """Get full message thread for a conversation."""
    service = get_service_client()
    messages = service.table("messages").select("*").eq("conversation_id", conversation_id).order("created_at").execute()
    return {"messages": messages.data}

@router.patch("/admin/conversations/{conversation_id}/status")
async def update_conversation_status(conversation_id: str, update: StatusUpdate, auth: bool = Depends(verify_admin)):
    """Update conversation status (e.g., close a handoff)."""
    if update.status not in ("active", "handed_off", "closed"):
        raise HTTPException(status_code=400, detail="Status must be 'active', 'handed_off', or 'closed'")
    service = get_service_client()
    service.table("conversations").update({"status": update.status}).eq("id", conversation_id).execute()
    return {"status": update.status}

@router.get("/admin/clients/{client_id}/events")
async def list_client_events(client_id: str, type_filter: str | None = None, auth: bool = Depends(verify_admin)):
    """List events for a client with optional type filter."""
    service = get_service_client()
    query = service.table("events").select("*").eq("client_id", client_id).order("created_at", desc=True)
    if type_filter:
        query = query.eq("type", type_filter)
    events = query.execute()
    return {"events": events.data}

# ---------------------------------------------------------------------------
# Client-facing API endpoints (no auth — token in URL is access control)
# ---------------------------------------------------------------------------

def _get_client_id_by_token(dashboard_token: str) -> str:
    """Look up client_id by dashboard_token. Raises 404 if not found."""
    service = get_service_client()
    resp = service.table("clients").select("id").eq("dashboard_token", dashboard_token).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Client not found")
    return resp.data[0]["id"]

@router.get("/client/{dashboard_token}/api/summary")
async def client_summary(dashboard_token: str):
    """Client-facing summary: lead counts by status, weekly stats."""
    client_id = _get_client_id_by_token(dashboard_token)
    service = get_service_client()
    
    # Lead counts by status
    leads = service.table("leads").select("status").eq("client_id", client_id).execute()
    status_counts = {}
    for lead in leads.data:
        s = lead["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    
    # Weekly stats from events
    from datetime import datetime, timedelta, timezone
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    
    events = service.table("events").select("type").eq("client_id", client_id).gte("created_at", week_ago).execute()
    weekly = {"leads_contacted": 0, "replies_received": 0, "appointments_booked": 0}
    for ev in events.data:
        if ev["type"] == "lead_contacted":
            weekly["leads_contacted"] += 1
        elif ev["type"] == "lead_replied":
            weekly["replies_received"] += 1
        elif ev["type"] == "appointment_booked":
            weekly["appointments_booked"] += 1
    
    return {"lead_counts": status_counts, "total_leads": len(leads.data), "weekly": weekly}

@router.get("/client/{dashboard_token}/api/conversations")
async def client_conversations(dashboard_token: str):
    """Client-facing conversations list with last message."""
    client_id = _get_client_id_by_token(dashboard_token)
    service = get_service_client()
    
    conversations = service.table("conversations").select("*, leads(name, phone, email)").eq("client_id", client_id).order("id", desc=True).execute()
    
    result = []
    for conv in conversations.data:
        last_msg = service.table("messages").select("content, direction, created_at").eq("conversation_id", conv["id"]).order("created_at", desc=True).limit(1).execute()
        conv["last_message"] = last_msg.data[0] if last_msg.data else None
        result.append(conv)
    
    return {"conversations": result}

@router.get("/client/{dashboard_token}/api/conversations/{conversation_id}/messages")
async def client_conversation_messages(dashboard_token: str, conversation_id: str):
    """Client-facing full message thread (read-only)."""
    client_id = _get_client_id_by_token(dashboard_token)
    service = get_service_client()
    
    # Verify conversation belongs to this client
    conv = service.table("conversations").select("client_id").eq("id", conversation_id).execute()
    if not conv.data or conv.data[0]["client_id"] != client_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = service.table("messages").select("*").eq("conversation_id", conversation_id).order("created_at").execute()
    return {"messages": messages.data}
