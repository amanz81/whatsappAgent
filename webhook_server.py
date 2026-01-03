from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Response
import uvicorn
import logging
import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import requests
import base64
import google.auth.transport.requests

# Import our new Google Drive service
from google_drive_service import get_drive_service, parse_gemini_response

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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

SERVICE_ACCOUNT_FILE = '/app/service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Verify Service Account File
if os.path.exists(SERVICE_ACCOUNT_FILE):
    logger.info(f"Found service account file: {SERVICE_ACCOUNT_FILE}")
else:
    logger.warning(f"Service account file NOT found at: {SERVICE_ACCOUNT_FILE}")

def get_raw_drive_api():
    """Legacy function - returns raw Drive API (not used anymore)"""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# import google.auth # Already imported
from google.oauth2 import service_account
import google.auth.transport.requests
import requests

# --- Configuration (Vertex AI) ---
PROJECT_ID = "wife-business-ai"
LOCATION = "us-central1"
GEMINI_MODEL = "gemini-2.0-flash-001" 
EVOLUTION_URL = "http://evolution_api:8080" # Internal Docker URL
EVOLUTION_APIKEY = "assaftest#1!"
INSTANCE_NAME = "CloudAgent" # Make sure this matches your instance

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

def get_gemini_response(audio_bytes, mime_type="audio/ogg"):
    """
    Call Vertex AI Gemini via REST API (No SDK Hell)
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
        
        # Base64 encode audio
        b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64_audio
                            }
                        },
                        {
                            "text": """
You are a smart personal assistant analyzing a voice note. Perform these tasks:

1. TRANSCRIBE the audio accurately (include the original language if not English)
2. Provide a concise SUMMARY of the main points
3. Extract any ACTION ITEMS (tasks the speaker needs to do or wants someone to do)
4. Identify any DEADLINES or time-sensitive items mentioned
5. List any SHOPPING ITEMS or things to buy/get mentioned

Format your response EXACTLY like this:

--- TRANSCRIPTION ---
[Full transcription here]

--- SUMMARY ---
[2-3 sentence summary of the main points]

--- ACTION ITEMS ---
- [Task 1]
- [Task 2]
(Leave empty if none found)

--- DEADLINES ---
- [Deadline with date/time if mentioned]
(Leave empty if none found)

--- SHOPPING ITEMS ---
- [Item 1]
- [Item 2]
(Leave empty if none found)
                            """
                        }
                    ]
                }
            ]
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            # Extract text
            try:
                return result['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError):
                logger.error(f"Unexpected Vertex Response: {result}")
                return None
        else:
            logger.error(f"Vertex API Error {response.status_code}: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Vertex/REST Error: {e}")
        return None

def get_gemini_text_response(text_content: str):
    """
    Call Vertex AI Gemini to analyze text content
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
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"""
You are a smart personal assistant analyzing a text note. Perform these tasks:

1. SUMMARIZE the main points
2. Extract any ACTION ITEMS (tasks to do)
3. Identify any DEADLINES or time-sensitive items
4. List any SHOPPING ITEMS or things to buy/get

The text to analyze:
{text_content}

Format your response EXACTLY like this:

--- TRANSCRIPTION ---
{text_content}

--- SUMMARY ---
[2-3 sentence summary of the main points]

--- ACTION ITEMS ---
- [Task 1]
- [Task 2]
(Leave empty if none found)

--- DEADLINES ---
- [Deadline with date/time if mentioned]
(Leave empty if none found)

--- SHOPPING ITEMS ---
- [Item 1]
- [Item 2]
(Leave empty if none found)
                            """
                        }
                    ]
                }
            ]
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            try:
                return result['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError):
                logger.error(f"Unexpected Vertex Response: {result}")
                return None
        else:
            logger.error(f"Vertex API Error {response.status_code}: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Vertex/REST Error: {e}")
        return None

def process_text_message(sender_number: str, text_content: str):
    """
    Process a text message triggered by 'keepAI' keyword.
    1. Analyze with Gemini
    2. Save to Google Sheets
    3. Send confirmation
    """
    try:
        logger.info(f"Processing text message from {sender_number}")
        
        # Remove the keepAI trigger from the text
        import re
        clean_text = re.sub(r'keepai', '', text_content, flags=re.IGNORECASE).strip()
        
        if not clean_text:
            send_whatsapp_message(sender_number, "📝 Please include some text after 'keepAI' to save.")
            return
        
        # Send acknowledgment
        send_whatsapp_message(sender_number, "📝 Text note received! Analyzing...")
        
        # Analyze with Gemini
        logger.info("Sending text to Gemini...")
        analysis_text = get_gemini_text_response(clean_text)
        
        if not analysis_text:
            logger.error("Gemini returned no analysis for text.")
            send_whatsapp_message(sender_number, "❌ Failed to analyze text.")
            return
        
        logger.info("Gemini Text Analysis Complete!")
        
        # Parse the response
        parsed_data = parse_gemini_response(analysis_text)
        parsed_data['timestamp'] = datetime.datetime.now()
        parsed_data['transcription'] = clean_text  # Use original text
        
        # Save to Google Sheets
        logger.info("Saving text note to Google Sheets...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_voice_note(sender_number, parsed_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Sheets: {drive_result.get('doc_url')}")
            
            action_count = len(parsed_data.get('action_items', []))
            shopping_count = len(parsed_data.get('shopping_items', []))
            deadline_count = len(parsed_data.get('deadlines', []))
            
            summary = parsed_data.get('summary', 'Text note processed.')
            
            reply_parts = ["✅ *Got it!* Your text note has been saved.\n"]
            reply_parts.append(f"📋 *Summary:* {summary[:200]}..." if len(summary) > 200 else f"📋 *Summary:* {summary}")
            
            if action_count > 0:
                reply_parts.append(f"\n✅ Found {action_count} action item(s)")
            if deadline_count > 0:
                reply_parts.append(f"\n⏰ Found {deadline_count} deadline(s)")
            if shopping_count > 0:
                reply_parts.append(f"\n🛒 Found {shopping_count} shopping item(s)")
            
            reply_parts.append(f"\n\n📁 View all notes: {drive_result.get('doc_url', 'Check your Drive')}")
            
            final_reply = ''.join(reply_parts)
        else:
            logger.error(f"Failed to save to Sheets: {drive_result.get('error')}")
            final_reply = f"✅ *Analysis Complete*\n\n{analysis_text}\n\n⚠️ Note: Failed to save to Sheets."
        
        send_whatsapp_message(sender_number, final_reply)

    except Exception as e:
        logger.error(f"Error processing text message: {e}")
        send_whatsapp_message(sender_number, f"❌ Error processing text: {str(e)}")

def process_voice_note(message_data: dict):
    """
    Background Task:
    1. Download audio
    2. Transcribe/Summarize with Vertex AI
    3. Upload to Google Drive
    """
    try:
        msg_id = message_data.get('id', 'unknown')
        logger.info(f"Processing Voice Note ID: {msg_id}")
        
        msg_content = message_data.get("message", {})
        
        # Extract Sender Number (remoteJid)
        # Structure: data -> key -> remoteJid
        key = message_data.get("key", {})
        sender_jid = key.get("remoteJid")
        
        # Clean JID (remove @s.whatsapp.net) usually not needed for Evolution, but safe to keep
        if sender_jid:
             sender_number = sender_jid.split("@")[0]
             # Send "Processing..." update
             send_whatsapp_message(sender_number, "🎙️ Voice Note received! Transcribing...")
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
        
        # Always add User-Agent
        headers["User-Agent"] = "Mozilla/5.0 (compatible; WhatsAppAgent/1.0)"

        import requests
        response = requests.get(audio_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to download audio: {response.status_code} - {response.text}")
            if sender_number:
                send_whatsapp_message(sender_number, "❌ Failed to download audio from Meta.")
            return
            
        audio_bytes = response.content
        logger.info(f"Audio Downloaded: {len(audio_bytes)} bytes")
        
        # 3. Call Gemini
        logger.info("Sending to Gemini (Vertex AI)...")
        analysis_text = get_gemini_response(audio_bytes, mimetype)
        
        if not analysis_text:
            logger.error("Gemini returned no text.")
            if sender_number:
                send_whatsapp_message(sender_number, "❌ Gemini failed to analyze audio.")
            return
            
        logger.info("Gemini Analysis Complete!")
        
        # Parse the structured response
        parsed_data = parse_gemini_response(analysis_text)
        parsed_data['timestamp'] = datetime.datetime.now()
        
        # Save to Google Drive
        logger.info("Saving to Google Drive...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_voice_note(sender_number, parsed_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Drive: {drive_result.get('doc_url')}")
            
            # Build user-friendly reply
            action_count = len(parsed_data.get('action_items', []))
            shopping_count = len(parsed_data.get('shopping_items', []))
            deadline_count = len(parsed_data.get('deadlines', []))
            
            # Summary message
            summary = parsed_data.get('summary', 'Voice note processed.')
            
            reply_parts = ["✅ *Got it!* Your voice note has been saved.\n"]
            reply_parts.append(f"📋 *Summary:* {summary[:200]}..." if len(summary) > 200 else f"📋 *Summary:* {summary}")
            
            if action_count > 0:
                reply_parts.append(f"\n✅ Found {action_count} action item(s)")
            if deadline_count > 0:
                reply_parts.append(f"\n⏰ Found {deadline_count} deadline(s)")
            if shopping_count > 0:
                reply_parts.append(f"\n🛒 Found {shopping_count} shopping item(s)")
            
            reply_parts.append(f"\n\n📁 View all notes: {drive_result.get('doc_url', 'Check your Drive')}")
            
            final_reply = ''.join(reply_parts)
        else:
            logger.error(f"Failed to save to Drive: {drive_result.get('error')}")
            # Still send the analysis even if Drive fails
            final_reply = f"✅ *Analysis Complete*\n\n{analysis_text}\n\n⚠️ Note: Failed to save to Drive."
        
        if sender_number:
            send_whatsapp_message(sender_number, final_reply)

    except Exception as e:
        logger.error(f"Error processing voice note: {e}")
        if 'sender_number' in locals() and sender_number:
             send_whatsapp_message(sender_number, f"❌ Error processing voice note: {str(e)}")

@app.get("/")
async def root():
    return {"message": "WhatsApp Agent Brain is Running!"}



async def process_webhook_data(data):
    """
    Background worker to handle analytics and logic
    """
    try:
        # Log full data
        logger.info(f"Full Payload: {json.dumps(data)}")

        # 1. Handle Standard Meta Cloud API
        if data.get("object") == "whatsapp_business_account":
             for entry in data.get("entry", []):
                 for change in entry.get("changes", []):
                     value = change.get("value", {})
                     if "messages" in value:
                          for msg in value["messages"]:
                              sender_number = msg.get('from')
                              
                              # Handle audio/voice messages
                              if msg.get("type") == "audio":
                                  logger.info("Detected Standard Meta Audio Message")
                                  normalized = {
                                      "key": {"remoteJid": f"{sender_number}@s.whatsapp.net"},
                                      "message": {
                                          "audioMessage": {
                                              "url": msg.get("audio", {}).get("url"),
                                              "mimetype": msg.get("audio", {}).get("mime_type")
                                          }
                                      },
                                      "id": msg.get("id")
                                  }
                                  process_voice_note(normalized)
                              
                              # Handle text messages with "keepAI" trigger
                              elif msg.get("type") == "text":
                                  text_body = msg.get("text", {}).get("body", "")
                                  if "keepai" in text_body.lower():
                                      logger.info(f"Detected 'keepAI' trigger in text message")
                                      process_text_message(sender_number, text_body)
             return {"status": "success"}

        # 2. Handle Evolution API
        event_type = data.get("type")
        logger.info(f"Processing event: {event_type}")
        
        if event_type == "MESSAGES_UPSERT":
            message_data = data.get("data", {})
            msg_content = message_data.get("message", {})

            if "audioMessage" in msg_content:
                logger.info("Voice note detected (Key Found)! Queuing background task.")
                process_voice_note(message_data)
            elif "audioMessage" in str(msg_content):
                 logger.info("Voice note detected (String Check)! Queuing background task.")
                 process_voice_note(message_data)
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "detail": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)