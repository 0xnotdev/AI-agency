from fastapi import APIRouter, HTTPException, status, Request, Response
from app.models.webhooks import WebhookLeadPayload
from app.core.db import get_service_client, get_client_scoped_client
from app.core.logging import logger
from postgrest.exceptions import APIError
from app.core.config import settings
from app.services.tasks import enqueue_message_processing
import svix.webhooks
from uuid import uuid4

router = APIRouter()

@router.post("/webhooks/lead", status_code=status.HTTP_202_ACCEPTED)
async def ingest_lead(payload: WebhookLeadPayload):
    """
    Ingests a new lead via webhook.
    Idempotent: Duplicate external_lead_id will be ignored and return 202.
    """
    client_id_str = str(payload.client_id)
    
    # 1. Validate client exists and is active using SERVICE ROLE client
    service_client = get_service_client()
    client_resp = service_client.table("clients").select("id, status").eq("id", client_id_str).execute()
    
    if not client_resp.data:
        raise HTTPException(status_code=404, detail="Client not found")
        
    if client_resp.data[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="Client is not active")

    # 2. Use SCOPED JWT client to enforce RLS for data ingestion
    scoped_client = get_client_scoped_client(client_id_str)
    
    lead_data = {
        "client_id": client_id_str,
        "external_lead_id": payload.external_lead_id,
        "name": payload.name,
        "phone": payload.phone,
        "email": payload.email,
        "source": payload.source,
        "status": "new"
    }
    
    try:
        lead_resp = scoped_client.table("leads").insert(lead_data).execute()
        lead_id = lead_resp.data[0]["id"]
        
        scoped_client.table("events").insert({
            "client_id": client_id_str,
            "type": "lead_created",
            "payload": payload.model_dump(mode='json')
        }).execute()
        
    except APIError as e:
        if "23505" in str(e.message) or "23505" in str(getattr(e, 'code', '')):
            return {"status": "accepted", "detail": "Lead already exists"}
        raise e

    return {"status": "accepted"}


@router.get("/webhooks/whatsapp")
async def verify_whatsapp(request: Request):
    """Meta webhook verification handshake."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.META_WEBHOOK_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Invalid verify token")


@router.post("/webhooks/whatsapp", status_code=status.HTTP_200_OK)
async def handle_whatsapp(request: Request):
    """Handles inbound WhatsApp messages."""
    payload = await request.json()
    
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        if "messages" not in value:
            return {"status": "ok"} # Not a message event (could be status update)
            
        message_data = value["messages"][0]
        contact_data = value["contacts"][0]
        
        external_message_id = message_data["id"]
        contact_phone = message_data["from"]
        lead_name = contact_data["profile"]["name"]
        text_content = message_data.get("text", {}).get("body", "")
        
        # Phone ID indicates which business account received this (used to lookup client)
        phone_number_id = value["metadata"]["phone_number_id"]
        
        # 1. Lookup Client by phone_number_id (Using Service Client)
        service_client = get_service_client()
        config_resp = service_client.table("client_configs").select("client_id").eq("whatsapp_phone_number_id", phone_number_id).execute()
        
        if not config_resp.data:
            err_msg = f"No client config found matching WhatsApp phone_number_id: {phone_number_id}"
            logger.error(err_msg)
            from app.core.alerts import send_telegram_alert
            send_telegram_alert(f"⚠️ <b>Routing Error</b>\n\n{err_msg}")
            return {"status": "ok"}
            
        client_id = config_resp.data[0]["client_id"]
        client_resp = service_client.table("clients").select("status").eq("id", client_id).execute()
        if not client_resp.data or client_resp.data[0].get("status") != "active":
            logger.error(f"Client {client_id} is inactive, dropping message.")
            return {"status": "ok"}
        scoped = get_client_scoped_client(client_id)
        
        # 2. Check/Create Lead
        lead_resp = scoped.table("leads").select("id").eq("phone", contact_phone).execute()
        if lead_resp.data:
            lead_id = lead_resp.data[0]["id"]
        else:
            new_lead = scoped.table("leads").insert({
            "client_id": client_id,
            "name": lead_name,
            "phone": contact_phone,
            "source": "inbound"
        }).execute()
            lead_id = new_lead.data[0]["id"]
            
        # 3. Check/Create Conversation
        conv_resp = scoped.table("conversations").select("id").eq("lead_id", lead_id).eq("status", "active").execute()
        if conv_resp.data:
            conv_id = conv_resp.data[0]["id"]
        else:
            new_conv = scoped.table("conversations").insert({
                "client_id": client_id,
                "lead_id": lead_id,
                "channel": "whatsapp",
                "status": "active"
            }).execute()
            conv_id = new_conv.data[0]["id"]
            
        # 4. Save Inbound Message (Idempotent)
        try:
            scoped.table("messages").insert({
                "id": str(uuid4()),
                "conversation_id": conv_id,
                "direction": "inbound",
                "content": text_content,
                "external_message_id": external_message_id
            }).execute()
        except APIError as e:
            if "23505" in str(e.message) or "23505" in str(getattr(e, 'code', '')):
                logger.info("Duplicate WhatsApp message ignored")
                return {"status": "ok"}
            raise e
            
        # 5. Enqueue Task for Processing
        await enqueue_message_processing({
            "client_id": client_id,
            "lead_id": lead_id,
            "conversation_id": conv_id,
            "channel": "whatsapp",
            "contact_info": contact_phone,
            "lead_name": lead_name
        })

    except Exception as e:
        logger.error(f"Error handling WhatsApp webhook: {e}")
        # Always return 200 to Meta so they stop retrying a permanently bad payload
        
    return {"status": "ok"}


@router.post("/webhooks/email", status_code=status.HTTP_200_OK)
async def handle_email(request: Request):
    """Handles inbound Email messages from Resend."""
    payload = await request.body()
    headers = request.headers
    
    if settings.RESEND_WEBHOOK_SECRET:
        wh = svix.webhooks.Webhook(settings.RESEND_WEBHOOK_SECRET)
        try:
            event = wh.verify(payload, headers)
        except svix.webhooks.WebhookVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        import json
        event = json.loads(payload)
        
    if event.get("type") != "email.received":
        return {"status": "ok"}
        
    data = event.get("data", {})
    from_email = data.get("from")
    text_content = data.get("text", "")
    external_message_id = data.get("id", str(uuid4())) # Resend message ID
    
    # 1. Lookup Client by email destination
    service_client = get_service_client()
    to_address = data.get("to")
    if isinstance(to_address, list):
        to_address = to_address[0]
        
    if not to_address:
        logger.error("No 'to' address found in Resend payload.")
        return {"status": "ok"}
        
    config_resp = service_client.table("client_configs").select("client_id").eq("inbound_email_address", to_address).execute()
    if not config_resp.data:
        err_msg = f"No client config found matching inbound_email_address: {to_address}"
        logger.error(err_msg)
        from app.core.alerts import send_telegram_alert
        send_telegram_alert(f"⚠️ <b>Routing Error</b>\n\n{err_msg}")
        return {"status": "ok"}
        
    client_id = config_resp.data[0]["client_id"]
    client_resp = service_client.table("clients").select("status").eq("id", client_id).execute()
    if not client_resp.data or client_resp.data[0].get("status") != "active":
        logger.error(f"Client {client_id} is inactive, dropping message.")
        return {"status": "ok"}
    scoped = get_client_scoped_client(client_id)
    
    # 2. Check/Create Lead
    lead_resp = scoped.table("leads").select("id").eq("email", from_email).execute()
    if lead_resp.data:
        lead_id = lead_resp.data[0]["id"]
    else:
        new_lead = scoped.table("leads").insert({
            "client_id": client_id,
            "name": from_email,
            "email": from_email,
            "source": "inbound"
        }).execute()
        lead_id = new_lead.data[0]["id"]
        
    # 3. Check/Create Conversation
    conv_resp = scoped.table("conversations").select("id").eq("lead_id", lead_id).eq("status", "active").execute()
    if conv_resp.data:
        conv_id = conv_resp.data[0]["id"]
    else:
        new_conv = scoped.table("conversations").insert({
            "client_id": client_id,
            "lead_id": lead_id,
            "channel": "email",
            "status": "active"
        }).execute()
        conv_id = new_conv.data[0]["id"]
        
    # 4. Save Inbound Message (Idempotent)
    try:
        scoped.table("messages").insert({
            "id": str(uuid4()),
            "conversation_id": conv_id,
            "direction": "inbound",
            "content": text_content,
            "external_message_id": external_message_id
        }).execute()
    except APIError as e:
        if "23505" in str(e.message) or "23505" in str(getattr(e, 'code', '')):
            logger.info("Duplicate Email message ignored")
            return {"status": "ok"}
        raise e
        
    # 5. Enqueue Task for Processing
    await enqueue_message_processing({
        "client_id": client_id,
        "lead_id": lead_id,
        "conversation_id": conv_id,
        "channel": "email",
        "contact_info": from_email,
        "lead_name": from_email
    })

    return {"status": "ok"}
