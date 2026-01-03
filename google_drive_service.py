"""
Google Sheets Service for WhatsApp Voice Notes
Simple approach: Appends to a spreadsheet YOU create and share with the service account.

SETUP:
1. Create a Google Sheet manually
2. Add headers: Timestamp | Phone | Summary | Action Items | Deadlines | Shopping | Transcription
3. Share with: whatsapp-agent@wife-business-ai.iam.gserviceaccount.com (Editor)
4. Copy the spreadsheet ID from the URL and set SPREADSHEET_ID env var
"""

import os
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Configuration
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', '/app/service-account.json')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Get spreadsheet ID from URL: https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', None)


class GoogleSheetsService:
    """Appends voice notes to a shared Google Sheet"""
    
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
            logger.info("Google Sheets service initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Sheets service: {e}")
    
    def append_note(self, phone_number: str, note_data: dict) -> bool:
        """Append a voice note row to the spreadsheet."""
        try:
            if not self.sheets_service:
                logger.error("Sheets service not initialized")
                return False
            
            if not SPREADSHEET_ID:
                logger.error("SPREADSHEET_ID environment variable not set!")
                return False
            
            timestamp = note_data.get('timestamp', datetime.now())
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(timestamp, datetime) else str(timestamp)
            
            action_items = '\n'.join([f"• {item}" for item in note_data.get('action_items', [])])
            deadlines = '\n'.join([f"• {item}" for item in note_data.get('deadlines', [])])
            shopping_items = '\n'.join([f"• {item}" for item in note_data.get('shopping_items', [])])
            
            row = [[
                timestamp_str,
                phone_number,
                note_data.get('summary', ''),
                action_items,
                deadlines,
                shopping_items,
                note_data.get('transcription', '')
            ]]
            
            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='Sheet1!A:G',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': row}
            ).execute()
            
            logger.info(f"Appended note for {phone_number}")
            return True
            
        except Exception as e:
            logger.error(f"Error appending note: {e}")
            return False
    
    def save_voice_note(self, phone_number: str, note_data: dict) -> dict:
        """Main entry point."""
        try:
            success = self.append_note(phone_number, note_data)
            
            if success:
                return {
                    'success': True,
                    'doc_url': f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}",
                    'doc_id': SPREADSHEET_ID
                }
            else:
                return {'success': False, 'error': 'Failed to append note'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


_sheets_service = None

def get_drive_service() -> GoogleSheetsService:
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
    return _sheets_service


def parse_gemini_response(response_text: str) -> dict:
    """Parse Gemini's structured response."""
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
