"""
Meta Cloud API Webhook Router.
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Response
import logging
import json
import os
from services.message_processor import MessageObject, process_message_unified
from typing import Optional

router = APIRouter(tags=["Meta"])
logger = logging.getLogger(__name__)

# --- Helper Reply Function ---
# (Needs to be a callable that takes sender, text)
# We can import existing send logic or redefine here.
# Assuming existing meta_sender logic exists in previous files, but I will reimplement briefly or import.
# For Clean Code, I should use services.meta_client if it exists, or local function.
# I'll implement internal helper for now to ensure closure.

def send_meta_reply(sender: str, text: str):
    import requests
    token = os.getenv('META_API_TOKEN')
    phone_id = os.getenv('META_PHONE_NUMBER_ID')
    if not token or not phone_id: return
    
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)

@router.get("/webhook/meta")
async def verify_meta(request: Request):
    """Verification Challenge"""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == "assaf123":
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(403, "Verification failed")

@router.post("/webhook/meta")
async def meta_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        
        # Standard Meta structure traversal
        entry = body.get('entry', [])[0]
        changes = entry.get('changes', [])[0]
        value = changes.get('value', {})
        
        if 'messages' not in value:
            return Response("OK", 200) # Not a message (maybe status update)
            
        msg_data = value['messages'][0]
        sender = msg_data.get('from')
        msg_type = msg_data.get('type')
        
        # Build MessageObject
        msg_obj = MessageObject(
            sender=sender,
            text="",
            gateway="Meta",
            message_id=msg_data.get('id'),
            timestamp=msg_data.get('timestamp')
        )
        
        # Handle Type
        if msg_type == 'text':
            msg_obj.text = msg_data['text']['body']
            
        elif msg_type == 'audio':
            audio = msg_data['audio']
            msg_obj.is_audio = True
            msg_obj.mime_type = audio.get('mime_type')
            # For Meta, we need to fetch the Media URL using the ID
            # But wait, MessageProcessor._fetch_audio uses a URL.
            # Meta gives an ID. We need a helper to swap ID for URL.
            # I'll do that here or in processor.
            # Processor expects `media_url`.
            msg_obj.media_url = _get_meta_media_url(audio.get('id'))
            msg_obj.auth_headers = {"Authorization": f"Bearer {os.getenv('META_API_TOKEN')}"}
            msg_obj.text = "[Audio Message]"
            
        else:
            return Response("Unsupported Type", 200)

        # Dispatch
        background_tasks.add_task(process_message_unified, msg_obj, send_meta_reply)
        return Response("OK", 200)

    except Exception as e:
        logger.error(f"Meta processing error: {e}")
        return Response("Error", 200)

def _get_meta_media_url(media_id: str) -> Optional[str]:
    try:
        token = os.getenv('META_API_TOKEN')
        res = requests.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        if res.status_code == 200:
            return res.json().get('url')
    except:
        pass
    return None

# Import requests for the helper
import requests
