import time
import uuid
import traceback
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.api import webhooks, health, admin, auth
from app.core.logging import setup_logging, logger

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Lead Response Platform")

# Register routers
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(auth.router)

# Middleware for structured access logging and latency
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    
    logger.info(
        "Request processed",
        extra={
            "endpoint": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "latency_ms": round(process_time, 2),
        }
    )
    return response

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches all unhandled exceptions so the process never crashes on a single bad request.
    Logs full context and returns a clean 500 JSON response.
    """
    error_id = str(uuid.uuid4())
    logger.error(
        "Unhandled exception",
        extra={
            "error_id": error_id,
            "endpoint": request.url.path,
            "method": request.method,
            "error": str(exc),
            "traceback": traceback.format_exc()
        }
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Internal server error", "error_id": error_id}
    )

# Pydantic validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on request", extra={
        "endpoint": request.url.path,
        "errors": exc.errors()
    })
    return JSONResponse(
        status_code=422,
        content={"status": "error", "detail": "Unprocessable Entity", "errors": exc.errors()}
    )


from fastapi.responses import HTMLResponse
@app.get("/chat", response_class=HTMLResponse)
async def chat_ui():
    return """
    <html>
    <head>
        <title>AI Agency Tester</title>
        <style>
            body { font-family: sans-serif; background: #111; color: #fff; display: flex; justify-content: center; padding: 50px; }
            #chat { width: 400px; height: 500px; background: #222; border-radius: 10px; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
            .msg { padding: 10px 15px; border-radius: 20px; max-width: 80%; word-wrap: break-word; }
            .user { background: #007bff; align-self: flex-end; }
            .bot { background: #444; align-self: flex-start; }
            .input-box { display: flex; margin-top: 10px; width: 440px; }
            input { flex-grow: 1; padding: 10px; border-radius: 5px; border: none; outline: none; }
            button { padding: 10px 20px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; margin-left: 10px; }
        </style>
    </head>
    <body>
        <div>
            <h2 style="text-align: center">WhatsApp Bypass Tester</h2>
            <div id="chat"></div>
            <div class="input-box">
                <input type="text" id="msgInput" placeholder="Type a message..." onkeypress="if(event.key==='Enter') sendMsg()">
                <button onclick="sendMsg()">Send</button>
            </div>
        </div>
        <script>
            let polling = false;
            let lastMsgCount = 0;
            
            async function pollDB() {
                if(polling) return;
                polling = true;
                try {
                    let res = await fetch('/api/chat-history');
                    let data = await res.json();
                    if(data.length > lastMsgCount) {
                        let chat = document.getElementById('chat');
                        chat.innerHTML = '';
                        data.forEach(msg => {
                            let div = document.createElement('div');
                            div.className = 'msg ' + (msg.direction === 'inbound' ? 'user' : 'bot');
                            div.innerText = msg.content;
                            chat.appendChild(div);
                        });
                        chat.scrollTop = chat.scrollHeight;
                        lastMsgCount = data.length;
                    }
                } catch(e) {}
                polling = false;
            }
            
            setInterval(pollDB, 2000);
            pollDB();
            
            async function sendMsg() {
                let input = document.getElementById('msgInput');
                let text = input.value;
                if(!text) return;
                input.value = '';
                
                // Optimistic UI update
                let chat = document.getElementById('chat');
                let div = document.createElement('div');
                div.className = 'msg user';
                div.innerText = text;
                chat.appendChild(div);
                chat.scrollTop = chat.scrollHeight;
                
                await fetch('/api/test-webhook', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text})
                });
            }
        </script>
    </body>
    </html>
    """

from pydantic import BaseModel
class ChatRequest(BaseModel):
    text: str

@app.post("/api/test-webhook")
async def api_test_webhook(req: ChatRequest):
    import urllib.request, json, uuid
    payload = {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "1292589239343299",
        "changes": [{
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550750524", "phone_number_id": "1152249817976388"},
            "contacts": [{"profile": {"name": "TestUser"}, "wa_id": "917978806779"}],
            "messages": [{
                "from": "917978806779",
                "id": str(uuid.uuid4()),
                "timestamp": "1234567890",
                "text": {"body": req.text},
                "type": "text"
            }]
          },
          "field": "messages"
        }]
      }]
    }
    
    # Internal HTTP request to the webhook endpoint using async httpx to prevent deadlock
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                'https://ai-agency-production-a6a9.up.railway.app/webhooks/whatsapp',
                json=payload,
                timeout=5.0
            )
    except Exception as e:
        pass
    return {"status": "ok"}

@app.get("/api/chat-history")
async def get_chat_history():
    from app.core.db import get_client_scoped_client, get_service_client
    # Hardcoded client ID for testing based on phone number ID
    
    service_client = get_service_client()
    config_resp = service_client.table("client_configs").select("client_id").eq("whatsapp_phone_number_id", "1152249817976388").limit(1).execute()
    if not config_resp.data: return []
    client_id = config_resp.data[0]["client_id"]
 # We will fetch latest conversation for this client
    scoped = get_client_scoped_client(client_id)
    
    # Find lead by phone
    lead_resp = scoped.table("leads").select("id").eq("phone", "917978806779").execute()
    if not lead_resp.data: return []
    lead_id = lead_resp.data[0]["id"]
    
    # Find active conversation
    conv_resp = scoped.table("conversations").select("id").eq("lead_id", lead_id).order("created_at.desc").limit(1).execute()
    if not conv_resp.data: return []
    conv_id = conv_resp.data[0]["id"]
    
    # Get messages
    msgs_resp = scoped.table("messages").select("content, direction, created_at").eq("conversation_id", conv_id).order("created_at").execute()
    return msgs_resp.data
