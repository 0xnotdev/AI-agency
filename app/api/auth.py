from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from app.core.config import settings
from app.core.db import get_service_client

router = APIRouter(tags=["auth"])

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def get_google_flow(state=None):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_REDIRECT_URI:
        raise ValueError("Google OAuth credentials are not fully configured.")
        
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "project_id": "leadrecover",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI]
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow

@router.get("/auth/google/login")
async def google_login(dashboard_token: str):
    """Initiates the Google OAuth flow for a client."""
    service = get_service_client()
    resp = service.table("clients").select("id").eq("dashboard_token", dashboard_token).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Invalid dashboard token")
        
    try:
        flow = get_google_flow(state=dashboard_token)
        flow.autogenerate_code_verifier = False
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Force consent to get refresh_token
        )
        return RedirectResponse(url=authorization_url)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/auth/google/callback")
async def google_callback(request: Request):
    """Handles the OAuth callback and stores tokens."""
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth Error: {error}")
    
    if not state or not code:
        raise HTTPException(status_code=400, detail="Missing state or code")
        
    service = get_service_client()
    client_resp = service.table("clients").select("id").eq("dashboard_token", state).execute()
    if not client_resp.data:
        raise HTTPException(status_code=404, detail="Client not found for this state")
        
    client_id = client_resp.data[0]["id"]
    
    try:
        flow = get_google_flow(state=state)
        # Fetch token (Force https since Railway terminates SSL and passes it internally as http)
        auth_url = str(request.url).replace('http://', 'https://')
        flow.fetch_token(authorization_response=auth_url)
        credentials = flow.credentials
        
        tokens_dict = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        
        service.table("client_configs").update({
            "google_calendar_tokens": tokens_dict
        }).eq("client_id", client_id).execute()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to authenticate: {str(e)}")
        
    return RedirectResponse(url=f"/client/{state}?calendar_connected=true")
