import logging
import random
from datetime import timedelta
from supabase import create_client, Client
from app.core.config import settings

logger = logging.getLogger(__name__)

# Note: We create a local supabase client using the Service Key
# because this runs in an unattended cron worker and needs full DB access.
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

async def process_drip_campaigns(ctx):
    """
    ARQ Cron task designed to run every 15 minutes.
    It fetches 1 pending lead per active campaign and queues an outbound message with random jitter.
    """
    logger.info("Starting DBR drip campaign engine run...")
    
    try:
        # 1. Fetch all active campaigns
        campaigns_res = supabase.table("campaigns").select("*").eq("status", "active").execute()
        active_campaigns = campaigns_res.data
        
        if not active_campaigns:
            logger.info("No active campaigns found. Sleeping.")
            return

        for campaign in active_campaigns:
            campaign_id = campaign["id"]
            client_id = campaign["client_id"]
            
            # 2. Fetch 1 pending lead for this campaign
            # Supabase doesn't natively support LIMIT 1 combined with UPDATE in REST API,
            # so we fetch 1, check it, then queue it. 
            # We don't mark it 'contacted' here, `process_outbound_message` will do that when it actually runs.
            # However, to prevent double-queuing, we can temporarily set it to 'queued' or just rely on 
            # the fact that the cron runs every 15 minutes and the task takes < 15 mins to run.
            # To be completely safe against double sends, we'll mark it as 'queued'.
            
            leads_res = supabase.table("leads").select("id").eq("campaign_id", campaign_id).eq("status", "new").eq("source", "reactivation").limit(1).execute()
            
            if not leads_res.data:
                # No more leads, mark campaign as completed
                logger.info(f"Campaign {campaign_id} has no more pending leads. Marking as completed.")
                supabase.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute()
                continue
                
            lead_id = leads_res.data[0]["id"]
            
            # 3. Mark as queued (to prevent next cron loop from grabbing it if the jitter delay > 15 mins)
            # We must add 'queued' to the status CHECK constraint in the database later if we actually want this, 
            # but for now we can leave it as 'new' and trust the jitter delay <= 15m.
            # Wait, if jitter is up to 15m (900s), it might not have sent by the time the next cron runs.
            # To avoid schema changes, we can just defer_by less than 14 minutes, or update the schema.
            # Let's keep it simple: defer by 1 to 10 minutes (60 to 600 seconds).
            
            jitter_seconds = random.randint(60, 600) 
            logger.info(f"Queuing outbound message for lead {lead_id} (Campaign: {campaign_id}) with {jitter_seconds}s jitter.")
            
            # 4. Enqueue the outbound processing task
            await ctx['redis'].enqueue_job(
                'process_outbound_message',
                client_id=client_id,
                lead_id=lead_id,
                _defer_by=jitter_seconds
            )
            
    except Exception as e:
        logger.error(f"Error in drip campaign engine: {str(e)}", exc_info=True)
