import logging
import csv
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel
from app.core.db import get_service_client
from app.api.admin import verify_admin

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/admin/clients/{client_id}/campaigns")
async def create_drip_campaign(
    client_id: str,
    name: str = Form(...),
    file: UploadFile = File(...),
    auth: bool = Depends(verify_admin)
):
    """
    Upload a CSV of dormant leads and create a drip campaign for them.
    Expected CSV columns: name, phone, email (at least name and one contact method).
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    service = get_service_client()
    
    # Verify client exists
    client_check = service.table("clients").select("id").eq("id", client_id).execute()
    if not client_check.data:
        raise HTTPException(status_code=404, detail="Client not found")
        
    try:
        contents = await file.read()
        decoded = contents.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        # Create campaign
        campaign_id = str(uuid.uuid4())
        campaign_res = service.table("campaigns").insert({
            "id": campaign_id,
            "client_id": client_id,
            "name": name,
            "status": "active"
        }).execute()
        
        if not campaign_res.data:
            raise Exception("Failed to create campaign record.")
            
        # Parse leads
        leads_to_insert = []
        for row in reader:
            # Normalize keys to lower case
            row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            
            lead_name = row.get("name", "Unknown")
            phone = row.get("phone", "")
            email = row.get("email", "")
            
            if not phone and not email:
                continue # Skip invalid leads
                
            leads_to_insert.append({
                "client_id": client_id,
                "name": lead_name,
                "phone": phone if phone else None,
                "email": email if email else None,
                "source": "reactivation",
                "status": "new",
                "campaign_id": campaign_id
            })
            
        if not leads_to_insert:
            # Rollback empty campaign
            service.table("campaigns").delete().eq("id", campaign_id).execute()
            raise HTTPException(status_code=400, detail="CSV contains no valid leads (must have phone or email).")
            
        # Bulk insert leads
        # Supabase allows bulk inserts up to ~1000 rows easily.
        service.table("leads").insert(leads_to_insert).execute()
        
        return {
            "status": "success", 
            "campaign_id": campaign_id, 
            "leads_imported": len(leads_to_insert)
        }
        
    except Exception as e:
        logger.error(f"Error processing CSV upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
