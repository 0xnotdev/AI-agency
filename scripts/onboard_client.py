import os
import sys
import json
import uuid

# Ensure we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
from app.core.config import settings


def onboard_client_core(business_name, niche, services_list, pricing_notes, faq, tone_instructions, outbound_offer, whatsapp_phone_number_id=None, inbound_email_address=None):
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    
    client_id = str(uuid.uuid4())
    
    client_data = {
        "id": client_id,
        "business_name": business_name,
        "niche": niche,
        "status": "active"
    }
    supabase.table("clients").insert(client_data).execute()
    
    config_data = {
        "client_id": client_id,
        "services": {"list": services_list},
        "pricing_notes": {"notes": pricing_notes},
        "faq": faq,
        "tone_instructions": tone_instructions,
        "outbound_offer": outbound_offer,
        "whatsapp_phone_number_id": whatsapp_phone_number_id,
        "inbound_email_address": inbound_email_address
    }
    supabase.table("client_configs").insert(config_data).execute()
    return client_id

def main():
    print("=== Client Onboarding ===")
    
    business_name = input("Business Name: ").strip()
    niche = input("Niche (e.g., HVAC, Dental): ").strip()
    
    print("\nEnter services offered as a comma-separated list (e.g. AC Repair, Heating Installation):")
    services_input = input("> ").strip()
    services_list = [s.strip() for s in services_input.split(",") if s.strip()]
    
    print("\nEnter pricing notes (e.g., $99 dispatch fee, free estimates):")
    pricing_notes = input("> ").strip()
    
    print("\nEnter FAQ as a JSON string (e.g., {\"Do you offer financing?\": \"Yes\"}) or leave blank for empty:")
    faq_input = input("> ").strip()
    faq = json.loads(faq_input) if faq_input else {}
    
    print("\nEnter tone instructions (e.g., professional, friendly, brief):")
    tone_instructions = input("> ").strip()
    
    print("\nEnter outbound offer for reactivation campaigns (e.g., 'We are doing a spring AC tune-up special for $50'):")
    outbound_offer = input("> ").strip()
    
    print("\nEnter WhatsApp Phone Number ID (leave blank if not using WhatsApp):")
    whatsapp_phone_number_id = input("> ").strip() or None
    
    print("\nEnter Inbound Email Address (leave blank if not using Email):")
    inbound_email_address = input("> ").strip() or None
    
    print("\nCreating client records...")
    
    try:
        client_id = onboard_client_core(business_name, niche, services_list, pricing_notes, faq, tone_instructions, outbound_offer, whatsapp_phone_number_id, inbound_email_address)
        print(f"\nSuccess! Client onboarded.")
        print(f"Client ID: {client_id}")
        
    except Exception as e:
        print(f"\nError onboarding client: {str(e)}")

if __name__ == "__main__":
    main()
