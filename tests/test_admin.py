import pytest
import uuid
import base64
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_service_client
from app.core.config import settings
from scripts.onboard_client import onboard_client_core

client = TestClient(app)

def auth_header(password=None):
    """Build HTTP Basic Auth header."""
    pw = password if password is not None else settings.DASHBOARD_PASSWORD
    creds = base64.b64encode(f"operator:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}

@pytest.fixture(scope="module")
def admin_test_data():
    """Onboard a test client with leads, conversations, messages, and events for admin tests."""
    service = get_service_client()
    
    client_id, dashboard_token = onboard_client_core(
        business_name="Admin Test Business",
        niche="Testing",
        services_list=["Admin Testing"],
        pricing_notes="Free",
        faq={"Q": "A"},
        tone_instructions="professional",
        outbound_offer="Test offer",
        whatsapp_phone_number_id=f"admin_wa_{uuid.uuid4().hex[:8]}",
        inbound_email_address=f"admin_{uuid.uuid4().hex[:8]}@example.com"
    )
    
    # Create a lead
    lead_id = str(uuid.uuid4())
    service.table("leads").insert({
        "id": lead_id,
        "client_id": client_id,
        "name": "Admin Test Lead",
        "phone": "5551234567",
        "email": "adminlead@test.com",
        "source": "inbound",
        "status": "new"
    }).execute()
    
    # Create a conversation
    conv_id = str(uuid.uuid4())
    service.table("conversations").insert({
        "id": conv_id,
        "client_id": client_id,
        "lead_id": lead_id,
        "channel": "whatsapp",
        "status": "active"
    }).execute()
    
    # Create messages
    service.table("messages").insert([
        {
            "id": str(uuid.uuid4()),
            "conversation_id": conv_id,
            "direction": "inbound",
            "content": "Hello, I need help!",
            "external_message_id": f"ext-admin-{uuid.uuid4()}"
        },
        {
            "id": str(uuid.uuid4()),
            "conversation_id": conv_id,
            "direction": "outbound",
            "content": "Hi! How can I assist you?"
        }
    ]).execute()
    
    # Create events
    service.table("events").insert([
        {"client_id": client_id, "type": "lead_created", "payload": {"name": "Admin Test Lead"}},
        {"client_id": client_id, "type": "error", "payload": {"error": "test error"}}
    ]).execute()
    
    yield {
        "client_id": client_id,
        "dashboard_token": dashboard_token,
        "lead_id": lead_id,
        "conv_id": conv_id
    }
    
    # Teardown
    service.table("clients").delete().eq("id", client_id).execute()


# ---------- Auth Tests ----------

def test_admin_correct_password(admin_test_data):
    resp = client.get("/admin/clients", headers=auth_header())
    assert resp.status_code == 200

def test_admin_wrong_password():
    resp = client.get("/admin/clients", headers=auth_header("wrong-password"))
    assert resp.status_code == 401

def test_admin_no_password():
    resp = client.get("/admin/clients")
    assert resp.status_code == 401


# ---------- Client List ----------

def test_list_clients(admin_test_data):
    resp = client.get("/admin/clients", headers=auth_header())
    assert resp.status_code == 200
    data = resp.json()
    assert "clients" in data
    client_ids = [c["id"] for c in data["clients"]]
    assert admin_test_data["client_id"] in client_ids


# ---------- Config Update ----------

def test_update_config(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.patch(
        f"/admin/clients/{cid}/config",
        json={"tone_instructions": "very friendly"},
        headers=auth_header()
    )
    assert resp.status_code == 200
    
    # Verify it persisted
    service = get_service_client()
    config = service.table("client_configs").select("tone_instructions").eq("client_id", cid).execute()
    assert config.data[0]["tone_instructions"] == "very friendly"


# ---------- Status Toggle ----------

def test_toggle_status(admin_test_data):
    cid = admin_test_data["client_id"]
    
    # Pause
    resp = client.patch(f"/admin/clients/{cid}/status", json={"status": "paused"}, headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    
    # Re-activate
    resp = client.patch(f"/admin/clients/{cid}/status", json={"status": "active"}, headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


# ---------- Leads ----------

def test_list_leads(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.get(f"/admin/clients/{cid}/leads", headers=auth_header())
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(l["name"] == "Admin Test Lead" for l in data["leads"])

def test_list_leads_status_filter(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.get(f"/admin/clients/{cid}/leads?status_filter=new", headers=auth_header())
    assert resp.status_code == 200
    assert all(l["status"] == "new" for l in resp.json()["leads"])

    # Filter for a status that shouldn't match
    resp = client.get(f"/admin/clients/{cid}/leads?status_filter=booked", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ---------- Conversations ----------

def test_list_conversations(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.get(f"/admin/clients/{cid}/conversations", headers=auth_header())
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert len(convs) >= 1
    # Should have last_message preview
    assert convs[0]["last_message"] is not None


# ---------- Message Thread ----------

def test_get_messages(admin_test_data):
    conv_id = admin_test_data["conv_id"]
    resp = client.get(f"/admin/conversations/{conv_id}/messages", headers=auth_header())
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    # Should be in chronological order (inbound first, then outbound)
    assert msgs[0]["direction"] == "inbound"
    assert msgs[1]["direction"] == "outbound"


# ---------- Conversation Status ----------

def test_update_conversation_status(admin_test_data):
    conv_id = admin_test_data["conv_id"]
    resp = client.patch(
        f"/admin/conversations/{conv_id}/status",
        json={"status": "closed"},
        headers=auth_header()
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    
    # Restore to active for other tests
    client.patch(f"/admin/conversations/{conv_id}/status", json={"status": "active"}, headers=auth_header())


# ---------- Events ----------

def test_list_events(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.get(f"/admin/clients/{cid}/events", headers=auth_header())
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 2

def test_list_events_type_filter(admin_test_data):
    cid = admin_test_data["client_id"]
    resp = client.get(f"/admin/clients/{cid}/events?type_filter=error", headers=auth_header())
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["type"] == "error" for e in events)
    assert len(events) >= 1


# ---------- Client Token View ----------

def test_client_view_valid_token(admin_test_data):
    token = admin_test_data["dashboard_token"]
    resp = client.get(f"/client/{token}")
    assert resp.status_code == 200
    assert "LeadRecover" in resp.text

def test_client_view_invalid_token():
    resp = client.get(f"/client/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------- Client API ----------

def test_client_api_summary(admin_test_data):
    token = admin_test_data["dashboard_token"]
    resp = client.get(f"/client/{token}/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "lead_counts" in data
    assert "total_leads" in data
    assert "weekly" in data

def test_client_api_conversations(admin_test_data):
    token = admin_test_data["dashboard_token"]
    resp = client.get(f"/client/{token}/api/conversations")
    assert resp.status_code == 200
    assert "conversations" in resp.json()

def test_client_api_invalid_token():
    resp = client.get(f"/client/{uuid.uuid4()}/api/summary")
    assert resp.status_code == 404
