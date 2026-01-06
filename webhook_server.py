from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Response
import uvicorn
import logging
import json
import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import requests
import base64
import google.auth.transport.requests

# Import our Google Sheets service
from google_drive_service import get_drive_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- Configuration (from environment variables) ---
PROJECT_ID = os.getenv('GOOGLE_PROJECT_ID', 'your-project-id')
LOCATION = os.getenv('GOOGLE_LOCATION', 'us-central1')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-001')
SERVICE_ACCOUNT_FILE = '/app/service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# B2B Whitelist Configuration
# Comma-separated phone numbers (without + or spaces)
WHITELIST_NUMBERS = [
    num.strip() 
    for num in os.getenv('WHITELIST_NUMBERS', '').split(',') 
    if num.strip()
]

# Verify Service Account File
if os.path.exists(SERVICE_ACCOUNT_FILE):
    logger.info(f"Found service account file: {SERVICE_ACCOUNT_FILE}")
else:
    logger.warning(f"Service account file NOT found at: {SERVICE_ACCOUNT_FILE}")

logger.info(f"B2B Whitelist loaded: {len(WHITELIST_NUMBERS)} numbers configured")


def is_whitelisted(phone_number: str) -> bool:
    """
    Check if a phone number is in the B2B whitelist.
    If whitelist is empty, allow all numbers (for testing/demo).
    """
    if not WHITELIST_NUMBERS:
        logger.debug("Whitelist is empty - allowing all numbers (demo mode)")
        return True
    
    # Normalize the phone number (remove any non-digit characters)
    normalized = re.sub(r'\D', '', phone_number)
    
    for allowed in WHITELIST_NUMBERS:
        allowed_normalized = re.sub(r'\D', '', allowed)
        if normalized.endswith(allowed_normalized) or allowed_normalized.endswith(normalized):
            return True
    
    return False


# Meta Webhook Verification
@app.get("/webhook/meta")
@app.get("/whatsapp-webhook")
async def verify_meta_webhook(request: Request):
    """
    Handle Meta's Webhook Verification Challenge
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


# Meta & Evolution Webhook Handler
@app.post("/webhook/meta")
@app.post("/whatsapp-webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Unified Endpoint for Evolution and Meta Cloud API
    """
    try:
        body_bytes = await request.body()
        try:
             data = json.loads(body_bytes)
        except json.JSONDecodeError:
            return Response(status_code=200)

        background_tasks.add_task(process_webhook_data, data)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response(status_code=200)


def send_whatsapp_message(number, text):
    """
    Send a text message reply via Meta Cloud API directly
    """
    try:
        phone_number_id = os.getenv('META_PHONE_NUMBER_ID', '')
        meta_token = os.getenv('META_API_TOKEN', '')
        
        if not meta_token:
            logger.error("META_API_TOKEN not set")
            return
        
        url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {"body": text}
        }
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            logger.info(f"Reply sent to {number}")
        else:
            logger.error(f"Failed to send reply: {res.status_code} - {res.text}")
    except Exception as e:
        logger.error(f"Error sending reply: {e}")


def get_vertex_token():
    """
    Get generic Google Cloud Access Token using Service Account
    """
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, 
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return creds.token


# B2B System Prompt for Intent Classification
B2B_SYSTEM_PROMPT = """You are a B2B Operations Manager AI assistant. Analyze the incoming message and classify it for business operations.

You MUST respond with a valid JSON object ONLY (no markdown, no code blocks, no explanation). The JSON must have these exact fields:

{
    "intent": "<one of: New Task, Revision, Inquiry, Urgent, Noise>",
    "priority": "<one of: High, Medium, Low>",
    "summary": "<Brief English summary of the message content, max 200 characters>",
    "client_action": "<Recommended action in the ORIGINAL language of the message>",
    "original_language": "<Language of the original message>",
    "transcription": "<Full transcription if audio, or original text if text message>"
}

Intent Definitions:
- New Task: A new request, order, or task that needs to be started
- Revision: A modification, change, or update to an existing task/order
- Inquiry: A question or request for information
- Urgent: Any message marked urgent or requiring immediate attention
- Noise: Greetings, thanks, confirmations, or non-actionable messages

Priority Guidelines:
- High: Urgent requests, complaints, time-sensitive matters
- Medium: Standard business requests, normal tasks
- Low: General inquiries, follow-ups, non-urgent matters

IMPORTANT: Keep client_action in the ORIGINAL language of the message. Return ONLY the JSON object."""


def get_gemini_b2b_response(content: str, content_type: str = "text", audio_bytes: bytes = None, mime_type: str = "audio/ogg"):
    """
    Call Vertex AI Gemini for B2B intent classification.
    
    Args:
        content: Text content to analyze (or description for audio)
        content_type: "text" or "audio"
        audio_bytes: Raw audio bytes if content_type is "audio"
        mime_type: MIME type of audio
    
    Returns:
        dict: Parsed B2B classification or None on error
    """
    try:
        token = get_vertex_token()
        if not token:
            logger.error("Failed to get Vertex Auth Token")
            return None

        url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Build the request parts
        parts = []
        
        if content_type == "audio" and audio_bytes:
            # Add audio data
            b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
            parts.append({
                "inlineData": {
                    "mimeType": mime_type,
                    "data": b64_audio
                }
            })
            parts.append({"text": B2B_SYSTEM_PROMPT + "\n\nAnalyze the above voice message."})
        else:
            # Text only
            parts.append({"text": B2B_SYSTEM_PROMPT + f"\n\nAnalyze this message:\n{content}"})
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for consistent JSON output
                "topP": 0.8,
                "maxOutputTokens": 1024
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            try:
                raw_text = result['candidates'][0]['content']['parts'][0]['text']
                return parse_b2b_json_response(raw_text)
            except (KeyError, IndexError):
                logger.error(f"Unexpected Vertex Response: {result}")
                return None
        else:
            logger.error(f"Vertex API Error {response.status_code}: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Vertex/REST Error: {e}")
        return None


def parse_b2b_json_response(response_text: str) -> dict:
    """
    Parse Gemini's B2B JSON response with fallback for malformed output.
    
    Returns:
        dict: Parsed data with intent classification fields
    """
    # Default fallback structure
    fallback = {
        "intent": "Noise",
        "priority": "Low",
        "summary": "Could not parse message",
        "client_action": "Manual review required",
        "original_language": "Unknown",
        "transcription": "",
        "parse_error": False,
        "raw_response": ""
    }
    
    if not response_text:
        fallback["parse_error"] = True
        return fallback
    
    try:
        # Clean up the response - remove markdown code blocks if present
        cleaned = response_text.strip()
        
        # Remove markdown code block markers
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        cleaned = cleaned.strip()
        
        # Try to parse as JSON
        parsed = json.loads(cleaned)
        
        # Validate required fields exist
        required_fields = ["intent", "priority", "summary", "client_action"]
        for field in required_fields:
            if field not in parsed:
                logger.warning(f"Missing required field: {field}")
                parsed[field] = fallback.get(field, "")
        
        # Validate intent values
        valid_intents = ["New Task", "Revision", "Inquiry", "Urgent", "Noise"]
        if parsed.get("intent") not in valid_intents:
            logger.warning(f"Invalid intent '{parsed.get('intent')}', defaulting to 'Noise'")
            parsed["intent"] = "Noise"
        
        # Validate priority values
        valid_priorities = ["High", "Medium", "Low"]
        if parsed.get("priority") not in valid_priorities:
            logger.warning(f"Invalid priority '{parsed.get('priority')}', defaulting to 'Medium'")
            parsed["priority"] = "Medium"
        
        parsed["parse_error"] = False
        return parsed
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.error(f"Raw response: {response_text[:500]}")
        
        # Fallback: extract what we can from the raw text
        fallback["parse_error"] = True
        fallback["raw_response"] = response_text[:1000]
        fallback["summary"] = response_text[:200] if response_text else "Parse error"
        fallback["client_action"] = "Manual review required - AI response was not valid JSON"
        return fallback


def process_text_message(sender_number: str, text_content: str, wamid: str = None, meta_timestamp: str = None):
    """
    Process a text message from a B2B client.
    No trigger word required - all messages from whitelisted numbers are processed.
    
    Args:
        sender_number: Phone number of sender
        text_content: Message content
        wamid: WhatsApp Message ID for legal proof
        meta_timestamp: Original timestamp from Meta
    """
    try:
        logger.info(f"Processing B2B text message from {sender_number}")
        
        if not text_content.strip():
            logger.info("Empty message content, skipping")
            return
        
        # Send acknowledgment
        send_whatsapp_message(sender_number, "📋 Message received! Processing...")
        
        # Analyze with Gemini B2B
        logger.info("Sending to Gemini for B2B classification...")
        b2b_data = get_gemini_b2b_response(text_content, content_type="text")
        
        if not b2b_data:
            logger.error("Gemini returned no analysis for text.")
            send_whatsapp_message(sender_number, "❌ Failed to analyze message.")
            return
        
        logger.info(f"B2B Classification: intent={b2b_data.get('intent')}, priority={b2b_data.get('priority')}")
        
        # Add metadata for logging
        b2b_data['timestamp'] = datetime.datetime.now()
        b2b_data['wamid'] = wamid
        b2b_data['meta_timestamp'] = meta_timestamp
        b2b_data['original_message'] = text_content
        b2b_data['media_url'] = None  # No media for text messages
        
        # Save to Google Sheets
        logger.info("Saving to Google Sheets...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_b2b_task(sender_number, b2b_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Sheets: {drive_result.get('doc_url')}")
            
            # Build user-friendly reply
            intent_emoji = {
                "New Task": "🆕",
                "Revision": "🔄",
                "Inquiry": "❓",
                "Urgent": "🚨",
                "Noise": "💬"
            }
            
            emoji = intent_emoji.get(b2b_data.get('intent', 'Noise'), "📝")
            
            reply_parts = [f"{emoji} *{b2b_data.get('intent', 'Received')}* - {b2b_data.get('priority', 'Medium')} Priority\n"]
            reply_parts.append(f"📋 {b2b_data.get('summary', 'Message logged')}")
            
            if b2b_data.get('client_action'):
                reply_parts.append(f"\n\n💡 *Action:* {b2b_data.get('client_action')}")
            
            reply_parts.append(f"\n\n📁 {drive_result.get('doc_url')}")
            
            final_reply = ''.join(reply_parts)
        else:
            logger.error(f"Failed to save to Sheets: {drive_result.get('error')}")
            final_reply = f"✅ *Received*\n\n{b2b_data.get('summary', 'Message logged')}\n\n⚠️ Note: Failed to save to Sheets."
        
        send_whatsapp_message(sender_number, final_reply)

    except Exception as e:
        logger.error(f"Error processing text message: {e}")
        send_whatsapp_message(sender_number, f"❌ Error processing message: {str(e)}")


def process_voice_note(message_data: dict, wamid: str = None, meta_timestamp: str = None):
    """
    Background Task for B2B voice message processing:
    1. Download audio
    2. Classify with Vertex AI Gemini
    3. Log to Google Sheets
    
    Args:
        message_data: Message payload
        wamid: WhatsApp Message ID for legal proof  
        meta_timestamp: Original timestamp from Meta
    """
    try:
        msg_id = message_data.get('id', 'unknown')
        logger.info(f"Processing B2B Voice Note ID: {msg_id}")
        
        msg_content = message_data.get("message", {})
        
        # Extract Sender Number
        key = message_data.get("key", {})
        sender_jid = key.get("remoteJid")
        
        if sender_jid:
             sender_number = sender_jid.split("@")[0]
             send_whatsapp_message(sender_number, "🎙️ Voice message received! Analyzing...")
        else:
             sender_number = None

        audio_info = msg_content.get("audioMessage", {})
        
        # 1. Get Audio URL
        audio_url = audio_info.get("url")
        raw_mime = audio_info.get("mimetype", "audio/ogg")
        mimetype = raw_mime.split(";")[0] if raw_mime else "audio/ogg"
        
        if not audio_url:
            logger.error("No audio URL found in message.")
            return

        logger.info(f"Downloading Audio from: {audio_url}")
        
        # 2. Download Audio
        headers = {}
        if "facebook" in audio_url or "whatsapp" in audio_url or "fbsbx" in audio_url:
             token = os.getenv('META_API_TOKEN', '')
             headers = {"Authorization": f"Bearer {token}"}
        
        headers["User-Agent"] = "Mozilla/5.0 (compatible; WhatsAppAgent/1.0)"

        response = requests.get(audio_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to download audio: {response.status_code} - {response.text}")
            if sender_number:
                send_whatsapp_message(sender_number, "❌ Failed to download audio from Meta.")
            return
            
        audio_bytes = response.content
        logger.info(f"Audio Downloaded: {len(audio_bytes)} bytes")
        
        # 3. Call Gemini B2B Classification
        logger.info("Sending to Gemini for B2B classification...")
        b2b_data = get_gemini_b2b_response(
            content="Voice message", 
            content_type="audio",
            audio_bytes=audio_bytes,
            mime_type=mimetype
        )
        
        if not b2b_data:
            logger.error("Gemini returned no classification.")
            if sender_number:
                send_whatsapp_message(sender_number, "❌ Failed to analyze voice message.")
            return
            
        logger.info(f"B2B Classification: intent={b2b_data.get('intent')}, priority={b2b_data.get('priority')}")
        
        # Add metadata for logging
        b2b_data['timestamp'] = datetime.datetime.now()
        b2b_data['wamid'] = wamid or msg_id
        b2b_data['meta_timestamp'] = meta_timestamp
        b2b_data['original_message'] = b2b_data.get('transcription', '[Voice Message]')
        b2b_data['media_url'] = audio_url
        
        # 4. Save to Google Sheets
        logger.info("Saving to Google Sheets...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_b2b_task(sender_number, b2b_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Sheets: {drive_result.get('doc_url')}")
            
            # Build user-friendly reply
            intent_emoji = {
                "New Task": "🆕",
                "Revision": "🔄", 
                "Inquiry": "❓",
                "Urgent": "🚨",
                "Noise": "💬"
            }
            
            emoji = intent_emoji.get(b2b_data.get('intent', 'Noise'), "📝")
            
            reply_parts = [f"{emoji} *{b2b_data.get('intent', 'Received')}* - {b2b_data.get('priority', 'Medium')} Priority\n"]
            reply_parts.append(f"📋 {b2b_data.get('summary', 'Voice message logged')}")
            
            if b2b_data.get('client_action'):
                reply_parts.append(f"\n\n💡 *Action:* {b2b_data.get('client_action')}")
            
            reply_parts.append(f"\n\n📁 {drive_result.get('doc_url')}")
            
            final_reply = ''.join(reply_parts)
        else:
            logger.error(f"Failed to save to Sheets: {drive_result.get('error')}")
            final_reply = f"✅ *Received*\n\n{b2b_data.get('summary', 'Voice message logged')}\n\n⚠️ Note: Failed to save to Sheets."
        
        if sender_number:
            send_whatsapp_message(sender_number, final_reply)

    except Exception as e:
        logger.error(f"Error processing voice note: {e}")
        if 'sender_number' in locals() and sender_number:
             send_whatsapp_message(sender_number, f"❌ Error processing voice message: {str(e)}")


@app.get("/")
async def root():
    return {"message": "WhatsApp B2B Operations Manager is Running!", "whitelist_count": len(WHITELIST_NUMBERS)}


async def process_webhook_data(data):
    """
    Background worker to handle B2B message processing
    """
    try:
        logger.info(f"Full Payload: {json.dumps(data)}")

        # 1. Handle Standard Meta Cloud API
        if data.get("object") == "whatsapp_business_account":
             for entry in data.get("entry", []):
                 for change in entry.get("changes", []):
                     value = change.get("value", {})
                     if "messages" in value:
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
                                  logger.info("Detected B2B Audio Message")
                                  normalized = {
                                      "key": {"remoteJid": f"{sender_number}@s.whatsapp.net"},
                                      "message": {
                                          "audioMessage": {
                                              "url": msg.get("audio", {}).get("url"),
                                              "mimetype": msg.get("audio", {}).get("mime_type")
                                          }
                                      },
                                      "id": wamid
                                  }
                                  process_voice_note(normalized, wamid=wamid, meta_timestamp=meta_timestamp)
                              
                              # Handle ALL text messages (no keepAI trigger required)
                              elif msg.get("type") == "text":
                                  text_body = msg.get("text", {}).get("body", "")
                                  logger.info(f"Processing B2B text message: {text_body[:50]}...")
                                  process_text_message(sender_number, text_body, wamid=wamid, meta_timestamp=meta_timestamp)
             return {"status": "success"}

        # 2. Handle Evolution API (legacy support)
        event_type = data.get("type")
        logger.info(f"Processing event: {event_type}")
        
        if event_type == "MESSAGES_UPSERT":
            message_data = data.get("data", {})
            msg_content = message_data.get("message", {})
            
            # Extract sender for whitelist check
            key = message_data.get("key", {})
            sender_jid = key.get("remoteJid", "")
            sender_number = sender_jid.split("@")[0] if sender_jid else ""
            
            if not is_whitelisted(sender_number):
                logger.info(f"Ignoring Evolution message from non-whitelisted: {sender_number}")
                return {"status": "success"}

            if "audioMessage" in msg_content:
                logger.info("B2B Voice note detected via Evolution!")
                process_voice_note(message_data)
            elif "audioMessage" in str(msg_content):
                 logger.info("B2B Voice note detected (String Check) via Evolution!")
                 process_voice_note(message_data)
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)