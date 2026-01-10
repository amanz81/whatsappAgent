"""
Google Sheets Service for B2B Operations Manager
Logs structured tasks with intent classification, priority, and client name lookup.

SETUP:
1. Create a Google Sheet with headers:
   Timestamp | Client Name | Phone Number | Intent | Priority | Summary | Action Items | Media Link
2. Share with your service account (Editor)
3. Set SPREADSHEET_ID env var
4. Create clients.json with phone-to-name mapping
"""

import os
import json
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Configuration
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', '/app/service-account.json')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', None)
CLIENTS_FILE = os.getenv('CLIENTS_FILE', '/app/clients.json')

# Load client name mapping
_client_names = {}

def _load_client_names():
    """Load phone-to-name mapping from clients.json"""
    global _client_names
    try:
        # Try container path first, then local path
        paths = [CLIENTS_FILE, './clients.json', 'clients.json']
        for path in paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    _client_names = json.load(f)
                logger.info(f"Loaded {len(_client_names)} client names from {path}")
                return
        logger.warning("clients.json not found - client names will be empty")
    except Exception as e:
        logger.error(f"Error loading clients.json: {e}")

_load_client_names()

def get_client_name(phone_number: str) -> str:
    """Look up client name by phone number"""
    if not phone_number:
        return ""
    # Normalize phone number (remove non-digits)
    normalized = ''.join(c for c in phone_number if c.isdigit())
    # Try exact match first, then partial matches
    if normalized in _client_names:
        return _client_names[normalized]
    # Try matching last 9-10 digits
    for stored_phone, name in _client_names.items():
        if normalized.endswith(stored_phone[-9:]) or stored_phone.endswith(normalized[-9:]):
            return name
    return ""


class GoogleSheetsService:
    """Manages B2B task logging to Google Sheets"""
    
    def __init__(self):
        self.sheets_service = None
        self._initialize_service()
    
    def _initialize_service(self):
        try:
            sa_file = SERVICE_ACCOUNT_FILE
            if not os.path.exists(sa_file):
                sa_file = './service-account.json'
            
            if not os.path.exists(sa_file):
                logger.error("Service account file not found")
                return
            
            creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=SCOPES
            )
            self.sheets_service = build('sheets', 'v4', credentials=creds)
            logger.info("Google Sheets service initialized for B2B Operations")
            
        except Exception as e:
            logger.error(f"Failed to initialize Sheets service: {e}")
    
    def save_b2b_task(self, phone_number: str, task_data: dict) -> dict:
        """
        Save a B2B task with structured fields to Google Sheets.
        
        Expected columns (matching user's sheet):
        Timestamp | Client Name | Phone Number | Intent | Priority | Summary | Action Items | Media Link | Gateway
        
        Args:
            phone_number: Client phone number
            task_data: Dict with intent, priority, summary, client_action, wamid, meta_timestamp, gateway, etc.
        
        Returns:
            dict with success status and doc_url
        """
        try:
            if not self.sheets_service:
                logger.error("Sheets service not initialized")
                return {'success': False, 'error': 'Sheets service not initialized'}
            
            if not SPREADSHEET_ID:
                logger.error("SPREADSHEET_ID environment variable not set!")
                return {'success': False, 'error': 'SPREADSHEET_ID not set'}
            
            # Format timestamp
            timestamp = task_data.get('timestamp', datetime.now())
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M") if isinstance(timestamp, datetime) else str(timestamp)
            
            # Build row matching user's sheet columns:
            # Timestamp | Client Name | Phone Number | Intent | Priority | Summary | Action Items | Media Link | Channel
            client_name = get_client_name(phone_number)
            row = [[
                timestamp_str,                                          # A: Timestamp
                client_name,                                            # B: Client Name (auto-lookup)
                phone_number or "",                                     # C: Phone Number
                task_data.get('intent', 'Unknown'),                     # D: Intent
                task_data.get('priority', 'Medium'),                    # E: Priority
                task_data.get('summary', '')[:500],                     # F: Summary (truncated)
                task_data.get('client_action', ''),                     # G: Action Items
                task_data.get('media_url', '') or "",                   # H: Media Link
                task_data.get('channel', 'Unknown')                     # I: Channel (Meta/WPP)
            ]]
            
            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='Sheet1!A:I',  # 9 columns
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': row}
            ).execute()
            
            logger.info(f"Appended B2B task for {phone_number}: {task_data.get('intent')}")
            
            return {
                'success': True,
                'doc_url': f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}",
                'doc_id': SPREADSHEET_ID
            }
            
        except Exception as e:
            logger.error(f"Error saving B2B task: {e}")
            return {'success': False, 'error': str(e)}
    
    def append_note(self, phone_number: str, note_data: dict) -> bool:
        """
        Legacy function for backward compatibility.
        Converts old note format to B2B task format.
        """
        try:
            # Convert legacy format to B2B format
            b2b_data = {
                'intent': 'New Task',
                'priority': 'Medium',
                'summary': note_data.get('summary', ''),
                'timestamp': note_data.get('timestamp', datetime.now()),
                'original_message': note_data.get('transcription', ''),
                'wamid': '',
                'meta_timestamp': '',
                'media_url': ''
            }
            
            result = self.save_b2b_task(phone_number, b2b_data)
            return result.get('success', False)
            
        except Exception as e:
            logger.error(f"Error in legacy append_note: {e}")
            return False
    
    def save_voice_note(self, phone_number: str, note_data: dict) -> dict:
        """
        Legacy entry point for backward compatibility.
        Redirects to B2B task saving.
        """
        try:
            # Convert legacy format
            b2b_data = {
                'intent': 'New Task',
                'priority': 'Medium',
                'summary': note_data.get('summary', ''),
                'timestamp': note_data.get('timestamp', datetime.now()),
                'original_message': note_data.get('transcription', ''),
                'wamid': note_data.get('wamid', ''),
                'meta_timestamp': note_data.get('meta_timestamp', ''),
                'media_url': note_data.get('media_url', '')
            }
            
            return self.save_b2b_task(phone_number, b2b_data)
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


# Singleton instance
_sheets_service = None

def get_drive_service() -> GoogleSheetsService:
    """Get singleton instance of GoogleSheetsService"""
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
    return _sheets_service


def parse_gemini_response(response_text: str) -> dict:
    """
    Legacy function: Parse Gemini's structured text response.
    Kept for backward compatibility with old note-taking format.
    
    NOTE: New B2B flow uses JSON parsing in webhook_server.py
    """
    result = {
        'transcription': '', 'summary': '',
        'action_items': [], 'deadlines': [], 'shopping_items': [],
        'timestamp': datetime.now()
    }
    
    if not response_text:
        return result
    
    sections = {
        'TRANSCRIPTION': 'transcription', 'SUMMARY': 'summary',
        'ACTION ITEMS': 'action_items', 'DEADLINES': 'deadlines',
        'SHOPPING ITEMS': 'shopping_items'
    }
    
    current_section = None
    current_content = []
    
    for line in response_text.split('\n'):
        line_stripped = line.strip()
        is_header = False
        
        for header, key in sections.items():
            if header in line_stripped.upper() and '---' in line_stripped:
                if current_section:
                    _save_section(result, current_section, current_content)
                current_section = key
                current_content = []
                is_header = True
                break
        
        if not is_header and current_section:
            current_content.append(line)
    
    if current_section:
        _save_section(result, current_section, current_content)
    
    return result


def _save_section(result: dict, section: str, content: list):
    """Helper to save parsed section content"""
    text = '\n'.join(content).strip()
    
    if section in ['action_items', 'deadlines', 'shopping_items']:
        items = []
        for line in content:
            line = line.strip()
            if line.startswith(('-', '•', '*')):
                item = line.lstrip('-•* ').strip()
                if item:
                    items.append(item)
            elif line and not line.startswith('---'):
                items.append(line)
        result[section] = items
    else:
        result[section] = text
