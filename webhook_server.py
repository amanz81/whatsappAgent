"""
WhatsApp B2B Operations Manager - Main Application

Unified webhook server supporting multiple WhatsApp gateways:
- Meta Cloud API at /webhook/meta
- WPPConnect at /webhook/wpp

Both gateways share the same Gemini B2B classification and Google Sheets logging.
"""

from fastapi import FastAPI, Request, Response, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn
import logging
import os
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import routers
from routers.meta_router import router as meta_router, verify_meta_webhook, handle_meta_webhook
from routers.wpp_router import router as wpp_router

# Import service for config info
from services.message_processor import load_clients, CLIENTS_FILE, GEMINI_MODEL
from services.wpp_client import send_wpp_message

# Verify Service Account File
SERVICE_ACCOUNT_FILE = '/app/service-account.json'
if os.path.exists(SERVICE_ACCOUNT_FILE):
    logger.info(f"Found service account file: {SERVICE_ACCOUNT_FILE}")
else:
    logger.warning(f"Service account file NOT found at: {SERVICE_ACCOUNT_FILE}")

app = FastAPI(
    title="WhatsApp B2B Operations Manager",
    description="Unified webhook server for Meta Cloud API and WPPConnect gateways",
    version="2.0.0"
)

# HTML Templates
templates = Jinja2Templates(directory="templates")

# Mount gateway routers
app.include_router(meta_router)
app.include_router(wpp_router)

# Legacy route aliases
app.add_api_route("/whatsapp-webhook", verify_meta_webhook, methods=["GET"])
app.add_api_route("/whatsapp-webhook", handle_meta_webhook, methods=["POST"])


# --- Dashboard Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the Admin Dashboard"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "gemini_model": GEMINI_MODEL
    })


@app.get("/api/clients")
async def get_clients():
    """List all authorized clients"""
    return load_clients()


@app.post("/api/clients")
async def add_client(payload: dict = Body(...)):
    """Add a new client to the whitelist"""
    name = payload.get("name")
    phone = payload.get("phone")
    
    if not name or not phone:
        return {"status": "error", "message": "Name and Phone required"}
        
    try:
        clients = load_clients()
        # Clean phone
        phone_clean = ''.join(filter(str.isdigit, phone))
        
        clients[phone_clean] = name
        
        with open(CLIENTS_FILE, 'w') as f:
            json.dump(clients, f, indent=4)
            
        return {"status": "success", "message": f"Added {name}"}
    except Exception as e:
        logger.error(f"Error adding client: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/send")
async def send_manual_message(payload: dict = Body(...)):
    """Send a manual message via the bot"""
    phone = payload.get("phone")
    message = payload.get("message")
    
    if not phone or not message:
        return {"status": "error", "message": "Phone and Message required"}
        
    success = send_wpp_message(phone, message)
    
    if success:
        return {"status": "success"}
    else:
        return {"status": "error", "message": "Failed to send message via Gateway"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)