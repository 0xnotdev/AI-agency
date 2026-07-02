import pytest
import uuid
from unittest.mock import patch, MagicMock
from app.services.conversation import process_inbound_message
from app.services.llm import LLMResponse
from app.core.db import get_service_client

@pytest.fixture
def test_data():
    service = get_service_client()
    
    # Create test client
    client_id = str(uuid.uuid4())
    service.table("clients").insert({
        "id": client_id,
        "business_name": "Test Conversational AI",
        "status": "active"
    }).execute()
    
    # Create client config
    service.table("client_configs").insert({
        "client_id": client_id,
        "services": {"list": ["Test services"]},
        "pricing_notes": {"note": "Free"},
        "faq": {"q1": "Test FAQ"},
        "tone_instructions": "helpful",
        "whatsapp_phone_number_id": "mock_wa_id_" + client_id[:8],
        "inbound_email_address": "mock_email_" + client_id[:8] + "@example.com"
    }).execute()
    
    # Create lead
    lead_id = str(uuid.uuid4())
    service.table("leads").insert({
        "id": lead_id,
        "client_id": client_id,
        "name": "Test Lead",
        "phone": "1234567890",
        "source": "inbound"
    }).execute()
    
    # Create conversation
    conv_id = str(uuid.uuid4())
    service.table("conversations").insert({
        "id": conv_id,
        "client_id": client_id,
        "lead_id": lead_id,
        "channel": "whatsapp",
        "status": "active"
    }).execute()
    
    # Insert inbound message (as webhook would do)
    msg_id = str(uuid.uuid4())
    service.table("messages").insert({
        "id": msg_id,
        "conversation_id": conv_id,
        "direction": "inbound",
        "content": "Hello, I need help.",
        "external_message_id": f"ext-test-msg-{uuid.uuid4()}"
    }).execute()
    
    return {
        "client_id": client_id,
        "lead_id": lead_id,
        "conversation_id": conv_id,
        "contact_info": "1234567890",
        "lead_name": "Test Lead"
    }

@patch("app.services.conversation.generate_reply")
@patch("app.services.conversation.send_whatsapp_message")
def test_successful_conversation_flow(mock_send_wa, mock_generate, test_data):
    # Mock LLM to return a normal reply
    mock_generate.return_value = LLMResponse(
        reply_text="Hello! How can I assist you?",
        handoff_required=False,
        book_calendar=False
    )
    
    process_inbound_message(
        client_id=test_data["client_id"],
        lead_id=test_data["lead_id"],
        conversation_id=test_data["conversation_id"],
        channel="whatsapp",
        contact_info=test_data["contact_info"],
        lead_name=test_data["lead_name"]
    )
    
    # Verify WA message was sent
    mock_send_wa.assert_called_once_with("mock_wa_id_" + test_data["client_id"][:8], "1234567890", "Hello! How can I assist you?")
    
    # Verify outbound message was saved
    service = get_service_client()
    msgs = service.table("messages").select("*").eq("conversation_id", test_data["conversation_id"]).execute().data
    assert len(msgs) == 2 # 1 inbound, 1 outbound
    assert msgs[1]["direction"] == "outbound"
    assert msgs[1]["content"] == "Hello! How can I assist you?"


@patch("app.services.conversation.generate_reply")
@patch("app.services.conversation.send_telegram_alert")
@patch("app.services.conversation.send_whatsapp_message")
def test_handoff_logic(mock_send_wa, mock_alert, mock_generate, test_data):
    # Mock LLM to require handoff
    mock_generate.return_value = LLMResponse(
        reply_text="I can't help with that. Let me get a human.",
        handoff_required=True,
        book_calendar=False
    )
    
    process_inbound_message(
        client_id=test_data["client_id"],
        lead_id=test_data["lead_id"],
        conversation_id=test_data["conversation_id"],
        channel="whatsapp",
        contact_info=test_data["contact_info"],
        lead_name=test_data["lead_name"]
    )
    
    # Verify conversation status was updated to handed_off
    service = get_service_client()
    conv = service.table("conversations").select("status").eq("id", test_data["conversation_id"]).execute().data[0]
    assert conv["status"] == "handed_off"
    
    # Verify Telegram alert was sent
    mock_alert.assert_called_once()
    alert_args = mock_alert.call_args[0][0]
    assert "Handoff Required" in alert_args
    assert test_data["client_id"] in alert_args


@patch("app.services.conversation.generate_reply")
@patch("app.services.conversation.send_telegram_alert")
@patch("app.services.conversation.send_whatsapp_message")
def test_failed_external_call_resilience(mock_send_wa, mock_alert, mock_generate, test_data):
    mock_generate.return_value = LLMResponse(
        reply_text="This will fail to send.",
        handoff_required=False,
        book_calendar=False
    )
    
    # Mock WA sender to raise Exception (simulating ultimate failure after retries)
    mock_send_wa.side_effect = Exception("WhatsApp API Down")
    
    with pytest.raises(Exception, match="WhatsApp API Down"):
        process_inbound_message(
            client_id=test_data["client_id"],
            lead_id=test_data["lead_id"],
            conversation_id=test_data["conversation_id"],
            channel="whatsapp",
            contact_info=test_data["contact_info"],
            lead_name=test_data["lead_name"]
        )
        
    # Verify an error event was recorded in the events table
    service = get_service_client()
    events = service.table("events").select("*").eq("client_id", test_data["client_id"]).execute().data
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) > 0
    assert "WhatsApp API Down" in error_events[0]["payload"]["error"]
    
    # Verify a crash alert was fired
    mock_alert.assert_called()
    alert_args = mock_alert.call_args_list[-1][0][0]
    assert "System Error" in alert_args
