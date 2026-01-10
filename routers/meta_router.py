"""
Meta Cloud API Webhook Router

Handles incoming webhooks from Meta's WhatsApp Business Cloud API.
Routes: /webhook/meta (GET for verification, POST for messages)
"""

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Response
import logging
import json
import os
import requests

from services.message_processor import (
    is_whitelisted,
    process_text_message,
    process_voice_note
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Meta Cloud API"])


def send_meta_message(recipient: str, text: str) -> bool:
    """
    Send a text message reply via Meta Cloud API.
    
    Args:
        recipient: Phone number (without @s.whatsapp.net)
        text: Message content
    
    Returns:
        bool: True if successful
    """
    try:
        phone_number_id = os.getenv('META_PHONE_NUMBER_ID', '')
        meta_token = os.getenv('META_API_TOKEN', '')
        
        if not meta_token:
            logger.error("META_API_TOKEN not set")
            return False
        
        # Strip any JID suffix if present
        if '@' in recipient:
            recipient = recipient.split('@')[0]
        
        url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"body": text}
        }
        
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            logger.info(f"Meta: Reply sent to {recipient}")
            return True
        else:
            logger.error(f"Meta: Failed to send reply: {res.status_code} - {res.text}")
            return False
            
    except Exception as e:
        logger.error(f"Meta: Error sending reply: {e}")
        return False


@router.get("/webhook/meta")
async def verify_meta_webhook(request: Request):
    """
    Handle Meta's Webhook Verification Challenge.
    
    Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.
    We must return the challenge value if the token matches.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    # Accept both 'evolution' (legacy) and 'assaf123' (user choice)
    if mode == "subscribe" and token in ["evolution", "assaf123"]:
        logger.info("Meta Webhook Verified!")
        return Response(content=challenge, media_type="text/plain")
    
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook/meta")
async def handle_meta_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Process incoming messages from Meta Cloud API.
    
    Meta sends a nested JSON structure:
    {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [...]
                }
            }]
        }]
    }
    """
    try:
        body_bytes = await request.body()
        try:
            data = json.loads(body_bytes)
        except json.JSONDecodeError:
            return Response(status_code=200)

        background_tasks.add_task(process_meta_webhook_data, data)
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"Meta webhook error: {e}")
        return Response(status_code=200)


async def process_meta_webhook_data(data: dict):
    """
    Background worker to process Meta Cloud API messages.
    """
    try:
        logger.info(f"Meta Payload: {json.dumps(data)[:500]}...")

        # Handle Standard Meta Cloud API
        if data.get("object") != "whatsapp_business_account":
            logger.debug("Not a whatsapp_business_account event, ignoring")
            return {"status": "ignored"}

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                if "messages" not in value:
                    continue
                    
                for msg in value["messages"]:
                    sender_number = msg.get('from')
                    wamid = msg.get('id')  # Message ID for legal proof
                    meta_timestamp = msg.get('timestamp')  # Unix timestamp
                    
                    # Check whitelist
                    if not is_whitelisted(sender_number):
                        logger.info(f"Ignoring message from non-whitelisted number: {sender_number}")
                        continue
                    
                    logger.info(f"Processing message from whitelisted number: {sender_number}")
                    
                    # Handle audio/voice messages
                    if msg.get("type") == "audio":
                        logger.info("Detected B2B Audio Message via Meta")
                        
                        audio_info = msg.get("audio", {})
                        audio_id = audio_info.get("id")
                        mime_type = audio_info.get("mime_type", "audio/ogg").split(";")[0]
                        
                        # Get audio URL from Meta
                        audio_url = get_meta_media_url(audio_id)
                        if audio_url:
                            # Build auth headers for Meta media download
                            meta_token = os.getenv('META_API_TOKEN', '')
                            auth_headers = {"Authorization": f"Bearer {meta_token}"} if meta_token else None
                            
                            process_voice_note(
                                sender_id=sender_number,
                                audio_url=audio_url,
                                mime_type=mime_type,
                                send_reply_func=send_meta_message,
                                wamid=wamid,
                                meta_timestamp=meta_timestamp,
                                is_group=False,
                                auth_headers=auth_headers
                            )
                    
                    # Handle text messages
                    elif msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        logger.info(f"Processing B2B text message: {text_body[:50]}...")
                        
                        process_text_message(
                            sender_id=sender_number,
                            text_content=text_body,
                            send_reply_func=send_meta_message,
                            wamid=wamid,
                            meta_timestamp=meta_timestamp,
                            is_group=False
                        )

        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Meta webhook processing error: {e}")
        return {"status": "error", "detail": str(e)}


def get_meta_media_url(media_id: str) -> str:
    """
    Get the download URL for a media file from Meta.
    
    Args:
        media_id: The media ID from the webhook payload
    
    Returns:
        str: Download URL or None
    """
    try:
        meta_token = os.getenv('META_API_TOKEN', '')
        if not meta_token:
            logger.error("META_API_TOKEN not set")
            return None
        
        url = f"https://graph.facebook.com/v21.0/{media_id}"
        headers = {"Authorization": f"Bearer {meta_token}"}
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get("url")
        else:
            logger.error(f"Failed to get media URL: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting media URL: {e}")
        return None
