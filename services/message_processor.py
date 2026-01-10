"""
Unified B2B Message Processor Service.

Refactored architecture to support Multi-Gateway (Meta & WPPConnect).
Implements a standardized MessageProcessor class and MessageObject.
"""

import logging
import json
import os
import re
import base64
import requests
import datetime
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any

from google.oauth2 import service_account
import google.auth.transport.requests

# Configure logging
logger = logging.getLogger(__name__)

# --- Configuration ---
PROJECT_ID = os.getenv('GOOGLE_PROJECT_ID', 'your-project-id')
LOCATION = os.getenv('GOOGLE_LOCATION', 'us-central1')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-001')
SERVICE_ACCOUNT_FILE = '/app/service-account.json'
CLIENTS_FILE = os.getenv('CLIENTS_FILE', '/app/clients.json')

# --- Data Structures ---

@dataclass
class MessageObject:
    """Standardized internal message representation."""
    sender: str             # Phone number (clean)
    text: str               # Text content or description
    gateway: str            # "Meta" or "WPP"
    message_id: str         # Legal ID (wamid / id)
    timestamp: Any          # Original timestamp
    is_group: bool = False
    group_id: Optional[str] = None  # JID
    group_name: Optional[str] = None
    media_url: Optional[str] = None
    mime_type: Optional[str] = None
    is_audio: bool = False
    auth_headers: Optional[Dict] = None # For Meta download


# --- System Prompts ---

B2B_SYSTEM_PROMPT = """You are a B2B Operations Manager AI assistant. Analyze the incoming message and classify it for business operations.

You MUST respond with a valid JSON object ONLY (no markdown, no code blocks).
Fields:
{
    "intent": "<New Task | Revision | Inquiry | Urgent | Noise>",
    "priority": "<High | Medium | Low>",
    "summary": "<Brief English summary, max 200 chars>",
    "action_items": "<List of actions in ORIGINAL language>",
    "original_language": "<Language code>",
    "context_tag": "<Group/Project Name or 'Direct'>"
}

Intent Definitions:
- New Task: New work request
- Revision: Change to existing work
- Inquiry: Question requiring answer
- Urgent: Critical/Time-sensitive
- Noise: Non-actionable (Thanks/Hello)
"""

# --- Message Processor Class ---

class MessageProcessor:
    """
    Central intelligence bridge for all gateways.
    Handles Validation -> Audio Proc -> AI -> Persistence -> Reply.
    """
    
    def __init__(self):
        self._load_clients()
    
    def _load_clients(self):
        self.clients = {}
        try:
            if os.path.exists(CLIENTS_FILE):
                with open(CLIENTS_FILE, 'r') as f:
                    self.clients = json.load(f)
        except Exception as e:
            logger.error(f"Error loading clients: {e}")

    def is_whitelisted(self, phone: str, group_id: str = None) -> bool:
        """Check if sender OR group is allowed."""
        # Check env override
        env_whitelist = [x.strip() for x in os.getenv('WHITELIST_NUMBERS', '').split(',') if x.strip()]
        
        # Clean phone
        clean_phone = re.sub(r'\D', '', phone)
        
        # Check explicit client list
        for c in self.clients.keys():
            if clean_phone.endswith(c) or c.endswith(clean_phone):
                return True
                
        # Check ENV whitelist (phones or group IDs)
        for allowed in env_whitelist:
            if allowed in clean_phone or (group_id and allowed in group_id):
                return True
                
        return False

    def process(self, msg: MessageObject, reply_func: Callable[[str, str], None]):
        """Main processing pipeline."""
        try:
            logger.info(f"Processing {msg.gateway} Msg from {msg.sender} (Group: {msg.is_group})")
            
            # 1. Security Check
            if not self.is_whitelisted(msg.sender, msg.group_id):
                logger.warning(f"⛔ Blocked unauthorized sender: {msg.sender}")
                return

            # 2. Acknowledge (Optional - avoid spamming groups)
            if not msg.is_group:
                reply_func(msg.sender, "⏳ Processing...")

            # 3. Media Handling
            audio_bytes = None
            if msg.is_audio and msg.media_url:
                audio_bytes = self._fetch_audio(msg)
                if not audio_bytes:
                    reply_func(msg.sender, "❌ Failed to download audio.")
                    return

            # 4. Intelligence (Gemini)
            b2b_result = self._call_gemini(msg, audio_bytes)
            
            if not b2b_result:
                reply_func(msg.sender, "❌ AI Classification Failed.")
                return

            # 5. Persistence (Google Sheets)
            from google_drive_service import get_drive_service
            drive = get_drive_service()
            
            # Prepare row data
            row_data = {
                "intent": b2b_result.get("intent", "Noise"),
                "priority": b2b_result.get("priority", "Low"),
                "summary": b2b_result.get("summary", ""),
                "action_items": b2b_result.get("action_items", ""),
                "source": msg.gateway,
                "context": msg.group_name if msg.is_group else "Direct",
                "legal_id": msg.message_id,
                "timestamp": msg.timestamp,
                "sender": msg.sender,
                "media_link": msg.media_url
            }
            
            save_result = drive.append_to_sheet(row_data)
            
            # 6. Reply
            response_text = self._format_reply(b2b_result, save_result)
            reply_func(msg.sender, response_text)

        except Exception as e:
            logger.error(f"Pipeline Error: {e}", exc_info=True)
            reply_func(msg.sender, "❌ System Error.")

    def _fetch_audio(self, msg: MessageObject) -> Optional[bytes]:
        """Unified audio fetcher (URL or Base64/DataURI)."""
        url = msg.media_url
        if not url: return None
        
        try:
            if url.startswith("data:"):
                # Handle Data URI
                header, encoded = url.split(",", 1)
                return base64.b64decode(encoded)
            else:
                # Handle URL
                headers = msg.auth_headers or {}
                headers["User-Agent"] = "WhatsAppAgent/2.0"
                res = requests.get(url, headers=headers, timeout=30)
                if res.status_code == 200:
                    return res.content
                else:
                    logger.error(f"Audio download failed: {res.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Audio fetch error: {e}")
            return None

    def _call_gemini(self, msg: MessageObject, audio_bytes: bytes = None) -> Optional[dict]:
        """Call Vertex AI Gemini."""
        try:
            token = self._get_vertex_token()
            url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{GEMINI_MODEL}:generateContent"
            
            # Construct Prompt
            context_str = f"Context: {'Group ' + msg.group_name if msg.is_group else 'Direct Message'}"
            final_prompt = f"{B2B_SYSTEM_PROMPT}\n\n{context_str}\n\nMessage Input:"
            
            parts = []
            if audio_bytes:
                b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                parts.append({
                    "inlineData": {"mimeType": msg.mime_type or "audio/ogg", "data": b64_audio}
                })
                parts.append({"text": final_prompt + " [Audio Message]"})
            else:
                parts.append({"text": f"{final_prompt}\n{msg.text}"})

            payload = {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024, "responseMimeType": "application/json"}
            }
            
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
            else:
                logger.error(f"Gemini API Error: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Gemini Call Error: {e}")
            return None

    def _get_vertex_token(self):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/cloud-platform'])
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        return creds.token

    def _format_reply(self, ai_data: dict, save_result: dict) -> str:
        emoji_map = {"New Task": "🆕", "Urgent": "🚨", "Noise": "👀"}
        icon = emoji_map.get(ai_data.get("intent"), "📝")
        
        reply = f"{icon} *{ai_data.get('intent')}* ({ai_data.get('priority')})\n"
        reply += f"Summary: {ai_data.get('summary')}\n"
        if ai_data.get('action_items'):
            reply += f"Action: {ai_data.get('action_items')}\n"
            
        if save_result.get('success'):
            reply += "\n✅ Logged."
        else:
            reply += "\n⚠️ Log Failed."
            
        return reply

# Singleton
processor = MessageProcessor()

# Bridge Functions for Routers (Backward Compatibility / Easy Import)
def process_message_unified(msg_obj: MessageObject, reply_func):
    processor.process(msg_obj, reply_func)
