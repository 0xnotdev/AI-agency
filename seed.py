import uuid
from app.core.db import get_service_client
from app.core.logging import logger

def seed():
    logger.info("Starting seed script...")
    service_client = get_service_client()
    
    # 1. Create a dummy active client
    dummy_client_id = str(uuid.uuid4())
    client_data = {
        "id": dummy_client_id,
        "business_name": "Acme HVAC & Plumbing",
        "niche": "HVAC",
        "status": "active"
    }
    
    logger.info(f"Inserting dummy client with ID: {dummy_client_id}")
    service_client.table("clients").insert(client_data).execute()
    
    # 2. Create config for the client
    config_data = {
        "client_id": dummy_client_id,
        "services": ["AC Repair", "Furnace Installation", "Plumbing"],
        "pricing_notes": {"dispatch_fee": 50, "hourly_rate": 120},
        "faq": {"do_you_do_commercial": "Yes, we handle commercial HVAC."},
        "tone_instructions": "Be polite, urgent, and empathetic. Emphasize that we have 24/7 emergency service.",
        "booking_link": "https://calendly.com/acme-hvac/book",
        "business_hours": {"monday_friday": "8am - 6pm", "weekend": "Emergency only"}
    }
    
    logger.info("Inserting client config...")
    service_client.table("client_configs").insert(config_data).execute()
    
    logger.info("Seed completed successfully.")
    print(f"Seed Client ID: {dummy_client_id}")

if __name__ == "__main__":
    seed()
