import os
import uuid
import pytest
from app.core.db import get_service_client, get_client_scoped_client

def test_rls_isolation():
    """
    Test to prove that Client A's scoped client cannot read Client B's leads.
    """
    service = get_service_client()
    
    # Setup: Create two clients
    client_a_id = str(uuid.uuid4())
    client_b_id = str(uuid.uuid4())
    
    service.table("clients").insert([
        {"id": client_a_id, "business_name": "Client A", "status": "active"},
        {"id": client_b_id, "business_name": "Client B", "status": "active"}
    ]).execute()
    
    # Insert leads for both clients using the service key
    lead_a_id = str(uuid.uuid4())
    lead_b_id = str(uuid.uuid4())
    
    service.table("leads").insert([
        {"id": lead_a_id, "client_id": client_a_id, "name": "Lead A", "source": "inbound"},
        {"id": lead_b_id, "client_id": client_b_id, "name": "Lead B", "source": "inbound"}
    ]).execute()
    
    # Test RLS
    scoped_a = get_client_scoped_client(client_a_id)
    
    # Client A should only see Lead A
    resp_a = scoped_a.table("leads").select("*").execute()
    lead_ids = [lead["id"] for lead in resp_a.data]
    
    assert lead_a_id in lead_ids
    assert lead_b_id not in lead_ids, "CRITICAL: RLS failed, Client A saw Client B's lead"
    assert len(lead_ids) == 1
    
    # Attempt to specifically fetch Client B's lead, should return empty
    resp_b_attempt = scoped_a.table("leads").select("*").eq("id", lead_b_id).execute()
    assert len(resp_b_attempt.data) == 0, "CRITICAL: RLS failed, Client A fetched Client B's lead directly"

    # Cleanup (optional since we're in a test DB, but good practice)
    service.table("clients").delete().in_("id", [client_a_id, client_b_id]).execute()
