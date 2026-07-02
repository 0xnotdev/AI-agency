import uuid
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from supabase import create_client

from app.core.config import settings
from scripts.onboard_client import onboard_client_core
from scripts.import_leads import import_leads
from scripts.start_campaign import start_campaign
from app.services.outbound import process_outbound_message
from app.services.llm import LLMResponse

# We reuse the get_service_client from the conversation tests or just define a quick one
def get_service_client():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

@pytest.fixture
def test_client_id():
    service = get_service_client()
    
    # 1. Onboard a test client
    client_id = onboard_client_core(
        business_name="Reactivation Test Business",
        niche="Testing",
        services_list=["Testing"],
        pricing_notes="Free",
        faq={},
        tone_instructions="brief",
        outbound_offer="Reply YES for a free test.",
        whatsapp_phone_number_id="wa_id_" + str(uuid.uuid4()),
        inbound_email_address="email_" + str(uuid.uuid4()) + "@example.com"
    )
    
    yield client_id
    
    # Teardown
    service.table("clients").delete().eq("id", client_id).execute()

def test_onboard_client_creates_rows(test_client_id):
    service = get_service_client()
    
    client_res = service.table("clients").select("*").eq("id", test_client_id).execute()
    assert len(client_res.data) == 1
    assert client_res.data[0]["business_name"] == "Reactivation Test Business"
    
    config_res = service.table("client_configs").select("*").eq("client_id", test_client_id).execute()
    assert len(config_res.data) == 1
    assert config_res.data[0]["outbound_offer"] == "Reply YES for a free test."

def test_csv_import_leads(test_client_id, tmp_path):
    # Create a dummy CSV file
    csv_file = tmp_path / "leads.csv"
    csv_content = """Name,Phone,Email,External_Lead_ID
John Doe,1234567890,,ext-1
Jane Doe,,jane@example.com,ext-2
Bad Row,,,ext-3
Duplicate,999888777,,ext-1
"""
    csv_file.write_text(csv_content, encoding="utf-8")
    
    import_leads(test_client_id, str(csv_file))
    
    service = get_service_client()
    leads = service.table("leads").select("*").eq("client_id", test_client_id).execute().data
    
    # We should have exactly 2 valid distinct leads (ext-1 and ext-2). ext-3 has no contact info. 
    # The duplicate ext-1 should UPSERT over the first one, meaning 'Duplicate' overwrites 'John Doe'.
    assert len(leads) == 2
    
    ext_1_lead = next(l for l in leads if l["external_lead_id"] == "ext-1")
    ext_2_lead = next(l for l in leads if l["external_lead_id"] == "ext-2")
    
    assert ext_1_lead["name"] == "Duplicate"
    assert ext_1_lead["phone"] == "999888777"
    assert ext_2_lead["email"] == "jane@example.com"
    assert ext_1_lead["status"] == "new"
    assert ext_1_lead["source"] == "reactivation"

@pytest.mark.asyncio
@patch("scripts.start_campaign.enqueue_outbound_processing")
async def test_campaign_scheduler(mock_enqueue, test_client_id):
    service = get_service_client()
    
    # Insert 3 leads directly
    service.table("leads").insert([
        {"client_id": test_client_id, "name": "A", "phone": "1", "source": "reactivation", "status": "new"},
        {"client_id": test_client_id, "name": "B", "phone": "2", "source": "reactivation", "status": "new"},
        {"client_id": test_client_id, "name": "C", "phone": "3", "source": "reactivation", "status": "new"}
    ]).execute()
    
    # Run scheduling at 120/hour (1 every 30 seconds)
    await start_campaign(test_client_id, 120)
    
    assert mock_enqueue.call_count == 3
    
    # Verify schedule times are roughly 30 seconds apart
    call_args_list = mock_enqueue.call_args_list
    time_0 = call_args_list[0].kwargs["schedule_time"]
    time_1 = call_args_list[1].kwargs["schedule_time"]
    time_2 = call_args_list[2].kwargs["schedule_time"]
    
    diff_1 = (time_1 - time_0).total_seconds()
    diff_2 = (time_2 - time_1).total_seconds()
    
    # Should be exactly 30.0 but let's just check bounds
    assert 29.0 < diff_1 < 31.0
    assert 29.0 < diff_2 < 31.0

@patch("app.services.outbound.generate_reply")
@patch("app.services.outbound.send_email_reply")
@patch("app.services.outbound.send_whatsapp_message")
def test_outbound_processing(mock_wa, mock_email, mock_generate, test_client_id):
    service = get_service_client()
    
    # Insert one lead with email (default is email)
    lead_id = str(uuid.uuid4())
    service.table("leads").insert({
        "id": lead_id,
        "client_id": test_client_id,
        "name": "Outbound Test",
        "email": "test@outbound.com",
        "source": "reactivation",
        "status": "new"
    }).execute()
    
    mock_generate.return_value = LLMResponse(
        reply_text="Hello, reply YES.",
        handoff_required=False,
        book_calendar=False
    )
    
    process_outbound_message(test_client_id, lead_id)
    
    # Verify it used email, not whatsapp
    mock_email.assert_called_once_with("test@outbound.com", "Checking in from Reactivation Test Business", "Hello, reply YES.")
    mock_wa.assert_not_called()
    
    # Verify lead status updated
    updated_lead = service.table("leads").select("status").eq("id", lead_id).execute().data[0]
    assert updated_lead["status"] == "contacted"
    
    # Verify conversation created
    convs = service.table("conversations").select("*").eq("lead_id", lead_id).execute().data
    assert len(convs) == 1
    conv_id = convs[0]["id"]
    assert convs[0]["channel"] == "email"
    
    # Verify message logged
    msgs = service.table("messages").select("*").eq("conversation_id", conv_id).execute().data
    assert len(msgs) == 1
    assert msgs[0]["direction"] == "outbound"
    assert msgs[0]["content"] == "Hello, reply YES."
