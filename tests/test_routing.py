import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_service_client
from scripts.onboard_client import onboard_client_core
import uuid
import json

client = TestClient(app)

@pytest.fixture(scope="module")
def routing_clients():
    service = get_service_client()
    
    wa_id_a = f"wa_test_A_{uuid.uuid4().hex[:8]}"
    email_a = f"email_A_{uuid.uuid4().hex[:8]}@example.com"
    
    wa_id_b = f"wa_test_B_{uuid.uuid4().hex[:8]}"
    email_b = f"email_B_{uuid.uuid4().hex[:8]}@example.com"

    # 1. Onboard Client A
    client_a_id, _ = onboard_client_core(
        business_name="Routing Client A",
        niche="Test",
        services_list=["Service A"],
        pricing_notes="Test A",
        faq={},
        tone_instructions="professional",
        outbound_offer="Offer A",
        whatsapp_phone_number_id=wa_id_a,
        inbound_email_address=email_a
    )
    
    # 2. Onboard Client B
    client_b_id, _ = onboard_client_core(
        business_name="Routing Client B",
        niche="Test",
        services_list=["Service B"],
        pricing_notes="Test B",
        faq={},
        tone_instructions="friendly",
        outbound_offer="Offer B",
        whatsapp_phone_number_id=wa_id_b,
        inbound_email_address=email_b
    )
    
    yield {
        "A": {"id": client_a_id, "wa": wa_id_a, "email": email_a},
        "B": {"id": client_b_id, "wa": wa_id_b, "email": email_b}
    }
    
    # Teardown
    for c_id in [client_a_id, client_b_id]:
        service.table("clients").delete().eq("id", c_id).execute()


def test_unique_constraint_rejects_duplicates(routing_clients):
    """
    Proves that the database uniquely constrains whatsapp_phone_number_id and inbound_email_address.
    """
    from postgrest.exceptions import APIError
    
    wa_id_a = routing_clients["A"]["wa"]
    email_b = routing_clients["B"]["email"]
    
    # Try to onboard Client C with Client A's WhatsApp ID
    with pytest.raises(APIError) as exc_info:
        onboard_client_core(
            business_name="Routing Client C (Collision WA)",
            niche="Test",
            services_list=[],
            pricing_notes="",
            faq={},
            tone_instructions="",
            outbound_offer="",
            whatsapp_phone_number_id=wa_id_a,
            inbound_email_address=f"safe_{uuid.uuid4().hex[:8]}@example.com"
        )
    assert "23505" in str(exc_info.value) # Postgres unique violation code
    
    # Try to onboard Client D with Client B's Email Address
    with pytest.raises(APIError) as exc_info:
        onboard_client_core(
            business_name="Routing Client D (Collision Email)",
            niche="Test",
            services_list=[],
            pricing_notes="",
            faq={},
            tone_instructions="",
            outbound_offer="",
            whatsapp_phone_number_id=f"wa_safe_{uuid.uuid4().hex[:8]}",
            inbound_email_address=email_b
        )
    assert "23505" in str(exc_info.value)

from unittest.mock import patch

@patch("app.api.webhooks.enqueue_message_processing")
def test_whatsapp_routes_to_correct_client(mock_enqueue, routing_clients):
    service = get_service_client()
    wa_id_a = routing_clients["A"]["wa"]
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "mock_entry_id",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "1234", "phone_number_id": wa_id_a},
                    "contacts": [{"profile": {"name": "Test User A"}, "wa_id": "1111111111"}],
                    "messages": [{
                        "from": "1111111111",
                        "id": f"wamid.{uuid.uuid4().hex}",
                        "timestamp": "1600000000",
                        "text": {"body": "Hello for Client A!"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    
    resp = client.post("/webhooks/whatsapp", json=payload)
    assert resp.status_code == 200
    
    # Verify Client A received it
    leads_a = service.table("leads").select("id").eq("client_id", routing_clients["A"]["id"]).execute()
    assert len(leads_a.data) == 1
    
    # Verify Client B did NOT receive it
    leads_b = service.table("leads").select("id").eq("client_id", routing_clients["B"]["id"]).execute()
    assert len(leads_b.data) == 0

@patch("app.api.webhooks.enqueue_message_processing")
def test_email_routes_to_correct_client(mock_enqueue, routing_clients):
    service = get_service_client()
    email_b = routing_clients["B"]["email"]
    
    payload = {
        "type": "email.received",
        "data": {
            "to": email_b,
            "from": "customer_b@test.com",
            "text": "Hello for Client B!",
            "id": str(uuid.uuid4())
        }
    }
    
    resp = client.post("/webhooks/email", json=payload)
    assert resp.status_code == 200
    
    # Verify Client B received it
    leads_b = service.table("leads").select("id").eq("client_id", routing_clients["B"]["id"]).execute()
    assert len(leads_b.data) == 1
    
    # Wait, the previous test might have added no leads to B. Now there should be 1.
    # Client A's leads should remain at 1 from the previous test.
    leads_a = service.table("leads").select("id").eq("client_id", routing_clients["A"]["id"]).execute()
    assert len(leads_a.data) == 1

def test_unknown_routing_is_dropped():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "mock_entry_id",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "1234", "phone_number_id": "unknown_ghost_id"},
                    "contacts": [{"profile": {"name": "Ghost User"}, "wa_id": "00000"}],
                    "messages": [{
                        "from": "00000",
                        "id": f"wamid.{uuid.uuid4().hex}",
                        "timestamp": "1600000000",
                        "text": {"body": "Spooky"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    
    resp = client.post("/webhooks/whatsapp", json=payload)
    assert resp.status_code == 200 # Webhook acknowledges to prevent retries
    # No clients should have received this lead. 
