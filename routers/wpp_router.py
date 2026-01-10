"""
WPPConnect Webhook Router

Handles incoming webhooks from WPPConnect server.
Supports both private messages and group messages (ending in @g.us).

Route: /webhook/wpp (POST for messages)
"""

from fastapi import APIRouter, Request, BackgroundTasks, Response
import logging
import json

from services.message_processor import (
    is_whitelisted,
    process_text_message,
    process_voice_note
)
from services.wpp_client import send_wpp_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WPPConnect"])


@router.post("/webhook/wpp")
async def handle_wpp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Process incoming messages from WPPConnect.
    
    WPPConnect sends a flat JSON structure like:
    {
        "event": "message",
        "session": "default",
        "data": {
            "from": "972509926644@s.whatsapp.net",  # or @g.us for groups
            "to": "972501234567@s.whatsapp.net",
            "body": "Hello",
            "type": "chat",
            "isGroupMsg": false,
            "sender": {
                "id": "...",
                "name": "Contact Name",
                "pushname": "Display Name"
            },
            "notifyName": "Display Name",
            "quotedMsg": null,
            "mimetype": "audio/ogg",  # for media
            "mediaUrl": "..."  # for media
        }
    }
    
    Alternative structure (some WPPConnect versions):
    {
        "wook": "message",
        "me": {...},
        "from": "972xxx@s.whatsapp.net",
        "body": "text",
        ...
    }
    """
    try:
        body_bytes = await request.body()
        try:
            data = json.loads(body_bytes)
        except json.JSONDecodeError:
            logger.warning("WPP: Invalid JSON received")
            return Response(status_code=200)

        background_tasks.add_task(process_wpp_webhook_data, data)
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"WPP webhook error: {e}")
        return Response(status_code=200)


async def process_wpp_webhook_data(data: dict):
    """
    Background worker to process WPPConnect messages.
    """
    try:
        logger.info(f"WPP Payload: {json.dumps(data)[:500]}...")

        # Determine payload structure
        # Structure 1: Nested under "data" key
        if "data" in data:
            event = data.get("event", "")
            if event not in ["message", "onMessage"]:
                logger.debug(f"WPP: Ignoring event type: {event}")
                return {"status": "ignored"}
            
            msg_data = data.get("data", {})
        else:
            # Structure 2: Flat structure (older WPPConnect versions)
            wook = data.get("wook", data.get("event", ""))
            if wook not in ["message", "onMessage"]:
                logger.debug(f"WPP: Ignoring wook type: {wook}")
                return {"status": "ignored"}
            
            msg_data = data

        # Extract sender information
        sender_jid = msg_data.get("from", "")
        if not sender_jid:
            logger.warning("WPP: No sender found in message")
            return {"status": "error", "detail": "No sender"}

        # Determine if group message
        is_group = "@g.us" in sender_jid or msg_data.get("isGroupMsg", False)
        
        # Extract phone number from JID
        sender_id = sender_jid.split("@")[0] if "@" in sender_jid else sender_jid
        
        # For groups, get the actual sender's number
        if is_group:
            participant = msg_data.get("author", msg_data.get("participant", ""))
            if participant:
                participant_number = participant.split("@")[0]
            else:
                # Try to get from sender object
                sender_obj = msg_data.get("sender", {})
                participant_number = sender_obj.get("id", "").split("@")[0] if sender_obj.get("id") else sender_id
            
            # Use participant for whitelist check, but keep group JID for replies
            whitelist_number = participant_number
            reply_to = sender_jid  # Reply to the group
            group_name = msg_data.get("chat", {}).get("name", msg_data.get("notifyName", "Group"))
        else:
            whitelist_number = sender_id
            reply_to = sender_jid
            group_name = None

        # Check whitelist
        if not is_whitelisted(whitelist_number):
            logger.info(f"WPP: Ignoring message from non-whitelisted: {whitelist_number}")
            return {"status": "success"}

        logger.info(f"WPP: Processing message from {whitelist_number} (group={is_group})")

        # Get message ID and timestamp
        msg_id = msg_data.get("id", {})
        if isinstance(msg_id, dict):
            wamid = msg_id.get("_serialized", str(msg_id))
        else:
            wamid = str(msg_id) if msg_id else None
        
        timestamp = msg_data.get("timestamp", msg_data.get("t", ""))

        # Determine message type
        msg_type = msg_data.get("type", "chat")
        
        # Handle audio/voice messages
        if msg_type in ["ptt", "audio"]:
            logger.info("WPP: Detected Voice Message")
            
            # Get audio URL - WPPConnect may provide it directly or we may need to fetch
            audio_url = msg_data.get("mediaUrl", msg_data.get("media", ""))
            mime_type = msg_data.get("mimetype", "audio/ogg").split(";")[0]
            
            if audio_url:
                process_voice_note(
                    sender_id=reply_to,
                    audio_url=audio_url,
                    mime_type=mime_type,
                    send_reply_func=send_wpp_message,
                    wamid=wamid,
                    meta_timestamp=str(timestamp),
                    is_group=is_group,
                    group_name=group_name
                )
            else:
                logger.warning("WPP: Voice message without mediaUrl")
                send_wpp_message(reply_to, "❌ Could not process voice message - no media URL")
        
        # Handle text messages
        elif msg_type in ["chat", "text"]:
            text_body = msg_data.get("body", msg_data.get("content", ""))
            
            if text_body:
                logger.info(f"WPP: Processing text message: {text_body[:50]}...")
                
                process_text_message(
                    sender_id=reply_to,
                    text_content=text_body,
                    send_reply_func=send_wpp_message,
                    wamid=wamid,
                    meta_timestamp=str(timestamp),
                    is_group=is_group,
                    group_name=group_name
                )
        
        # Handle image messages with caption
        elif msg_type == "image":
            caption = msg_data.get("caption", "")
            if caption:
                logger.info(f"WPP: Processing image caption: {caption[:50]}...")
                
                process_text_message(
                    sender_id=reply_to,
                    text_content=f"[Image] {caption}",
                    send_reply_func=send_wpp_message,
                    wamid=wamid,
                    meta_timestamp=str(timestamp),
                    is_group=is_group,
                    group_name=group_name
                )
        
        else:
            logger.debug(f"WPP: Ignoring message type: {msg_type}")

        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"WPP webhook processing error: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


@router.get("/webhook/wpp/status")
async def wpp_status():
    """
    Check WPPConnect connection status.
    """
    from services.wpp_client import get_wpp_session_status
    
    status = get_wpp_session_status()
    return {
        "gateway": "wppconnect",
        "session_status": status
    }
