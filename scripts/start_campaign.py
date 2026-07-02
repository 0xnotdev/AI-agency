import os
import sys
import argparse
import asyncio
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
from app.core.config import settings
from app.services.tasks import enqueue_outbound_processing

async def start_campaign(client_id: str, rate_per_hour: int):
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    
    print(f"Starting reactivation campaign for client {client_id}")
    print(f"Target rate: {rate_per_hour} messages/hour")
    
    # Query leads
    res = supabase.table("leads").select("id").eq("client_id", client_id).eq("source", "reactivation").eq("status", "new").execute()
    leads = res.data
    
    if not leads:
        print("No new reactivation leads found for this client.")
        return
        
    total_leads = len(leads)
    print(f"Found {total_leads} new reactivation leads.")
    
    # Calculate spacing in seconds
    spacing_seconds = 3600.0 / rate_per_hour
    now = datetime.now(timezone.utc)
    
    success_count = 0
    
    for index, lead in enumerate(leads):
        lead_id = lead["id"]
        
        # Calculate when this specific message should go out
        delay = timedelta(seconds=spacing_seconds * index)
        schedule_time = now + delay
        
        payload = {
            "client_id": client_id,
            "lead_id": lead_id
        }
        
        try:
            # Enqueue to Redis via arq
            await enqueue_outbound_processing(payload, schedule_time=schedule_time)
            success_count += 1
            print(f"Enqueued {lead_id} for {schedule_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        except Exception as e:
            print(f"Failed to enqueue {lead_id}: {str(e)}")
            
    print(f"\nCampaign scheduling complete. Enqueued {success_count}/{total_leads} tasks.")
    expected_duration_hours = (total_leads * spacing_seconds) / 3600.0
    print(f"Estimated completion time: {expected_duration_hours:.2f} hours from now.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Schedule outbound reactivation campaign via Redis Queue.")
    parser.add_argument("--client-id", required=True, help="Supabase UUID for the client")
    parser.add_argument("--rate-per-hour", type=int, default=30, help="Number of messages to send per hour (default: 30)")
    
    args = parser.parse_args()
    asyncio.run(start_campaign(args.client_id, args.rate_per_hour))
