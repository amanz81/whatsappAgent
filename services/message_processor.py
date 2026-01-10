"""
Shared Message Processing Service for B2B Operations Manager

This module contains the core Gemini classification and message processing logic
shared by both Meta Cloud API and WPPConnect gateways.
"""

import logging
import json
import os
import re
import base64
import datetime
import requests
from google.oauth2 import service_account
import google.auth.transport.requests

# Configure logging
logger = logging.getLogger(__name__)

# --- Configuration (from environment variables) ---
PROJECT_ID = os.getenv('GOOGLE_PROJECT_ID', 'your-project-id')
LOCATION = os.getenv('GOOGLE_LOCATION', 'us-central1')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-001')
SERVICE_ACCOUNT_FILE = '/app/service-account.json'

# Client Configuration
CLIENTS_FILE = os.getenv('CLIENTS_FILE', '/app/clients.json')

def load_clients():
    """Load authorized clients from JSON file."""
    try:
        if os.path.exists(CLIENTS_FILE):
            with open(CLIENTS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading clients file: {e}")
        return {}

def is_whitelisted(phone_number: str) -> bool:
    """
    Check if a phone number is an authorized client.
    STRICT MODE: Only allowed if in clients.json
    """
    clients = load_clients()
    
    # Also check env var for overrides
    env_whitelist = [
        num.strip() 
        for num in os.getenv('WHITELIST_NUMBERS', '').split(',') 
        if num.strip()
    ]
    
    # Normalize input
    normalized = re.sub(r'\D', '', phone_number)
    
    # Check clients.json
    for client_number in clients.keys():
        client_norm = re.sub(r'\D', '', client_number)
        if normalized.endswith(client_norm) or client_norm.endswith(normalized):
            return True
            
    # Check env var
    for allowed in env_whitelist:
        allowed_normalized = re.sub(r'\D', '', allowed)
        if normalized.endswith(allowed_normalized) or allowed_normalized.endswith(normalized):
            return True
            
    return False


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


def build_reply_message(b2b_data: dict, drive_result: dict) -> str:
    """
    Build user-friendly reply message from B2B classification data.
    
    Args:
        b2b_data: Classified data from Gemini
        drive_result: Result from Google Sheets save operation
    
    Returns:
        str: Formatted reply message
    """
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
    
    if drive_result.get('success'):
        reply_parts.append(f"\n\n📁 {drive_result.get('doc_url')}")
    else:
        reply_parts.append("\n\n⚠️ Note: Failed to save to Sheets.")
    
    return ''.join(reply_parts)


def process_text_message(sender_id: str, text_content: str, send_reply_func, 
                         wamid: str = None, meta_timestamp: str = None, 
                         is_group: bool = False, group_name: str = None,
                         gateway: str = "Unknown"):
    """
    Process a text message from a B2B client.
    
    Args:
        sender_id: Phone number or group JID of sender
        text_content: Message content
        send_reply_func: Function to send reply (gateway-specific)
        wamid: WhatsApp Message ID for legal proof
        meta_timestamp: Original timestamp from Meta/WPP
        is_group: Whether this is a group message
        group_name: Name of the group (if applicable)
        gateway: Channel source (Meta/WPP)
    """
    from google_drive_service import get_drive_service
    
    try:
        logger.info(f"Processing B2B text message from {sender_id}")
        
        if not text_content.strip():
            logger.info("Empty message content, skipping")
            return
        
        # Send acknowledgment
        send_reply_func(sender_id, "📋 Message received! Processing...")
        
        # Analyze with Gemini B2B
        logger.info("Sending to Gemini for B2B classification...")
        b2b_data = get_gemini_b2b_response(text_content, content_type="text")
        
        if not b2b_data:
            logger.error("Gemini returned no analysis for text.")
            send_reply_func(sender_id, "❌ Failed to analyze message.")
            return
        
        logger.info(f"B2B Classification: intent={b2b_data.get('intent')}, priority={b2b_data.get('priority')}")
        
        # Add metadata for logging
        b2b_data['timestamp'] = datetime.datetime.now()
        b2b_data['wamid'] = wamid
        b2b_data['meta_timestamp'] = meta_timestamp
        b2b_data['original_message'] = text_content
        b2b_data['media_url'] = None  # No media for text messages
        b2b_data['is_group'] = is_group
        b2b_data['group_name'] = group_name
        b2b_data['channel'] = gateway
        
        # Save to Google Sheets
        logger.info("Saving to Google Sheets...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_b2b_task(sender_id, b2b_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Sheets: {drive_result.get('doc_url')}")
        else:
            logger.error(f"Failed to save to Sheets: {drive_result.get('error')}")
        
        # Build and send reply
        final_reply = build_reply_message(b2b_data, drive_result)
        send_reply_func(sender_id, final_reply)

    except Exception as e:
        logger.error(f"Error processing text message: {e}")
        send_reply_func(sender_id, f"❌ Error processing message: {str(e)}")


def process_voice_note(sender_id: str, audio_url: str, mime_type: str, send_reply_func,
                       wamid: str = None, meta_timestamp: str = None,
                       is_group: bool = False, group_name: str = None,
                       auth_headers: dict = None, gateway: str = "Unknown"):
    """
    Process a voice message from a B2B client.
    
    Args:
        sender_id: Phone number or group JID of sender
        audio_url: URL to download audio from
        mime_type: MIME type of the audio
        send_reply_func: Function to send reply (gateway-specific)
        wamid: WhatsApp Message ID for legal proof
        meta_timestamp: Original timestamp
        is_group: Whether this is a group message
        group_name: Name of the group (if applicable)
        auth_headers: Optional auth headers for downloading audio
    """
    from google_drive_service import get_drive_service
    
    try:
        logger.info(f"Processing B2B Voice Note from: {sender_id}")
        
        # Send acknowledgment
        send_reply_func(sender_id, "🎙️ Voice message received! Analyzing...")
        
        # 1. Download Audio
        logger.info(f"Downloading Audio from: {audio_url}")
        
        headers = auth_headers or {}
        headers["User-Agent"] = "Mozilla/5.0 (compatible; WhatsAppAgent/1.0)"
        
        response = requests.get(audio_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Failed to download audio: {response.status_code} - {response.text}")
            send_reply_func(sender_id, "❌ Failed to download audio.")
            return
            
        audio_bytes = response.content
        logger.info(f"Audio Downloaded: {len(audio_bytes)} bytes")
        
        # 2. Call Gemini B2B Classification
        logger.info("Sending to Gemini for B2B classification...")
        b2b_data = get_gemini_b2b_response(
            content="Voice message", 
            content_type="audio",
            audio_bytes=audio_bytes,
            mime_type=mime_type
        )
        
        if not b2b_data:
            logger.error("Gemini returned no classification.")
            send_reply_func(sender_id, "❌ Failed to analyze voice message.")
            return
            
        logger.info(f"B2B Classification: intent={b2b_data.get('intent')}, priority={b2b_data.get('priority')}")
        
        # Add metadata for logging
        b2b_data['timestamp'] = datetime.datetime.now()
        b2b_data['wamid'] = wamid
        b2b_data['meta_timestamp'] = meta_timestamp
        b2b_data['original_message'] = b2b_data.get('transcription', '[Voice Message]')
        b2b_data['media_url'] = audio_url
        b2b_data['is_group'] = is_group
        b2b_data['group_name'] = group_name
        b2b_data['channel'] = gateway
        
        # 3. Save to Google Sheets
        logger.info("Saving to Google Sheets...")
        drive_service = get_drive_service()
        drive_result = drive_service.save_b2b_task(sender_id, b2b_data)
        
        if drive_result['success']:
            logger.info(f"Saved to Sheets: {drive_result.get('doc_url')}")
        else:
            logger.error(f"Failed to save to Sheets: {drive_result.get('error')}")
        
        # Build and send reply
        final_reply = build_reply_message(b2b_data, drive_result)
        send_reply_func(sender_id, final_reply)

    except Exception as e:
        logger.error(f"Error processing voice note: {e}")
        send_reply_func(sender_id, f"❌ Error processing voice message: {str(e)}")
