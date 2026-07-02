import logging
import uuid
from supabase import create_client, Client
from app.core.config import settings
from app.core.alerts import send_telegram_alert
from app.services.llm import generate_reply
from app.services.whatsapp import send_whatsapp_message
from app.services.email import send_email_reply

logger = logging.getLogger(__name__)

# Using Service Role Key here because background tasks run unattended 
# and need to perform admin-level state updates safely.
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def process_outbound_message(client_id: str, lead_id: str):
    """
    Processes an outbound reactivation message for a dormant lead.
    This runs asynchronously via Cloud Tasks.
    """
    try:
        # 1. Verify lead is still new
        lead_res = supabase.table("leads").select("*").eq("id", lead_id).eq("client_id", client_id).execute()
        if not lead_res.data:
            logger.error(f"Lead {lead_id} not found.")
            return
            
        lead = lead_res.data[0]
        if lead.get("status") != "new":
            logger.info(f"Lead {lead_id} is no longer 'new' (status: {lead.get('status')}). Skipping outbound.")
            return

        contact_info = ""
        channel = ""
        
        # Determine Channel: Default to email, fallback to whatsapp
        if lead.get("email"):
            channel = "email"
            contact_info = lead.get("email")
        elif lead.get("phone"):
            channel = "whatsapp"
            contact_info = lead.get("phone")
        else:
            logger.error(f"Lead {lead_id} has no email or phone. Cannot send outbound.")
            return

        # 2. Get Client Config
        config_res = supabase.table("client_configs").select("*").eq("client_id", client_id).execute()
        if not config_res.data:
            logger.error(f"No config found for client {client_id}")
            return
            
        config = config_res.data[0]
        client_res = supabase.table("clients").select("business_name").eq("id", client_id).execute()
        business_name = client_res.data[0]["business_name"] if client_res.data else "the business"

        # 3. Generate LLM Opener
        outbound_offer = config.get("outbound_offer", "We are doing a check-in to see if you need our services.")
        
        system_prompt = f"""You are an assistant for {business_name}.
You are sending a cold/warm re-engagement message to a past lead named {lead.get("name", "there")}.
Your goal is to pitch the following offer: {outbound_offer}

CRITICAL RULES:
1. Keep the message to exactly 1-2 sentences.
2. End with a clear, low-friction call to action (e.g. "reply YES for a quick callback slot" or "reply YES if you're interested") rather than an open-ended question.
3. Be friendly but extremely concise. Do NOT be overly talkative.
"""
        
        # We use generate_reply but without history since it's the first message
        llm_response = generate_reply(
            system_prompt=system_prompt,
            conversation_history=[],
            tone_instructions=config.get("tone_instructions", "")
        )
        
        # 4. Create Conversation Row
        conversation_id = str(uuid.uuid4())
        supabase.table("conversations").insert({
            "id": conversation_id,
            "lead_id": lead_id,
            "client_id": client_id,
            "channel": channel,
            "status": "active"
        }).execute()
        
        # 5. Send Message
        if channel == "whatsapp":
            phone_number_id = config.get("whatsapp_phone_number_id")
            send_whatsapp_message(phone_number_id, contact_info, llm_response.reply_text)
        else:
            send_email_reply(contact_info, f"Checking in from {business_name}", llm_response.reply_text)
            
        # 6. Log to Messages
        supabase.table("messages").insert({
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "direction": "outbound",
            "content": llm_response.reply_text
        }).execute()
        
        # 7. Update Lead Status
        supabase.table("leads").update({
            "status": "contacted",
            "last_contacted_at": "now()"
        }).eq("id", lead_id).execute()
        
        logger.info(f"Successfully processed outbound message for lead {lead_id} via {channel}.")
        
    except Exception as e:
        logger.error(f"Error processing outbound message: {str(e)}")
        
        # Log to events table
        try:
            supabase.table("events").insert({
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "type": "error",
                "payload": {"error": f"Outbound processing error: {str(e)}", "lead_id": lead_id}
            }).execute()
        except Exception as event_e:
            logger.error(f"Failed to log error event: {str(event_e)}")
            
        # Send Alert
        try:
            send_telegram_alert(f"⚠️ <b>Outbound Processing Error</b>\n\nClient: {client_id}\nLead: {lead_id}\nError: {str(e)}")
        except Exception:
            pass
            
        raise e
