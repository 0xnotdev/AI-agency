import jwt
import time
from supabase import create_client, Client
from app.core.config import settings

def get_service_client() -> Client:
    """
    Returns a Supabase client authenticated with the Service Role Key.
    This client BYPASSES Row-Level Security (RLS).
    
    CRITICAL: Only use this for global checks (e.g., verifying if a client_id 
    exists and is active before trusting a webhook payload). 
    Do NOT use this for inserting or querying tenant data.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def get_client_scoped_client(client_id: str) -> Client:
    """
    Returns a Supabase client scoped to a specific client_id.
    This client is authenticated using a short-lived JWT that we mint ourselves,
    so PostgREST enforces the Row-Level Security (RLS) policies for that client_id.
    
    CRITICAL: Only call this AFTER validating the client_id using the service-role 
    key. Do not mint a JWT for an unverified client_id.
    """
    payload = {
        "role": "authenticated",
        "sub": str(client_id),
        "iat": int(time.time()),
        "exp": int(time.time()) + 300  # 5 minute expiration
    }
    
    # Mint a custom JWT signed with the Supabase JWT secret
    token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    
    # We must use the ANON key as the `supabase_key` so the API Gateway (Kong) 
    # accepts the request via the `apikey` header.
    # Then we override the `Authorization` header with our custom JWT so PostgREST 
    # enforces RLS for this specific client_id based on the `sub` claim.
    from supabase.client import ClientOptions
    options = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY, options=options)
