import logging
from uuid import uuid4
from app.core.db import get_client_scoped_client
from app.services.llm import generate_reply
from app.services.whatsapp import send_whatsapp_message
from app.services.email import send_email_reply
from app.core.alerts import send_telegram_alert

logger = logging.getLogger(__name__)

def process_inbound_message(
    client_id: str,
    lead_id: str,
    conversation_id: str,
    channel: str,
    contact_info: str,
    lead_name: str
) -> None:
    """
    Core conversation engine executed in the background via Cloud Tasks.
    The inbound message has already been saved to the DB by the webhook.
    """
    try:
        scoped = get_client_scoped_client(client_id)
        
        # 1. Fetch Client Config
        config_resp = scoped.table("client_configs").select("*").eq("client_id", client_id).execute()
        if not config_resp.data:
            raise ValueError(f"No config found for client_id {client_id}")
        client_config = config_resp.data[0]
        
        # 2. Fetch Conversation History
        history_resp = scoped.table("messages").select("content, direction").eq("conversation_id", conversation_id).order("created_at").execute()
        history = history_resp.data
        
        if not history:
            raise ValueError(f"No messages found for conversation {conversation_id}")
            
        # The webhook saved the inbound message last.
        last_message = history.pop()
        if last_message["direction"] != "inbound":
            logger.warning(f"Task executed but last message was not inbound. Convo: {conversation_id}")
            return
            
        new_message_content = last_message["content"]
        
        # 3. Call LLM (which now internally handles Calendar Function Calling)
        llm_response = generate_reply(client_config, history, new_message_content, lead_name, contact_info)
        
        # 5. Save Outbound Message
        scoped.table("messages").insert({
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "direction": "outbound",
            "content": llm_response.reply_text
        }).execute()
        
        # 6. Send Reply via Channel
        try:
            if channel == "whatsapp":
                phone_number_id = client_config.get("whatsapp_phone_number_id")
                send_whatsapp_message(phone_number_id, contact_info, llm_response.reply_text)
            elif channel == "email":
                send_email_reply(contact_info, "Re: Your Inquiry", llm_response.reply_text)
            else:
                logger.error(f"Unknown channel: {channel}")
        except Exception as e:
            # We fail the task here because we didn't send the message.
            # Cloud Tasks will retry it.
            raise e
        
        # 7. Handle Handoff / Alerting
        if llm_response.handoff_required:
            scoped.table("conversations").update({"status": "handed_off"}).eq("id", conversation_id).execute()
            
            alert_msg = (
                f"🚨 <b>Handoff Required</b>\n\n"
                f"<b>Client ID:</b> {client_id}\n"
                f"<b>Lead:</b> {lead_name} ({contact_info})\n"
                f"<b>Reason:</b> LLM flagged handoff.\n"
                f"<b>Last Inbound:</b> {new_message_content}\n"
                f"<b>Outbound Sent:</b> {llm_response.reply_text}"
            )
            send_telegram_alert(alert_msg)

    except Exception as e:
        logger.error(f"Error processing inbound message: {str(e)}", exc_info=True)
        # Log to events table for visibility
        try:
            scoped = get_client_scoped_client(client_id)
            scoped.table("events").insert({
                "id": str(uuid4()),
                "client_id": client_id,
                "type": "error",
                "payload": {"error": str(e) + " | " + repr(getattr(e, "last_attempt", None) and e.last_attempt.exception()), "conversation_id": conversation_id}
            }).execute()
            
            # Send Telegram alert for the crash
            send_telegram_alert(f"💥 <b>System Error</b>\n\nClient: {client_id}\nConv: {conversation_id}\nError: {str(e)}")
        except Exception as inner_e:
            logger.error(f"Failed to log error event: {inner_e}")
        
        # Reraise so Cloud Tasks registers the failure and schedules a retry
        raise e
