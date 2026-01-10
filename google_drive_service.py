"""
Google Sheets Service.
Modified to support Atomic Appending with unified B2B Metadata.
"""

import os
import logging
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SERVICE_ACCOUNT_FILE = '/app/service-account.json'
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

class GoogleSheetsService:
    def __init__(self):
        self.creds = None
        self.service = None
        self._auth()

    def _auth(self):
        try:
            if os.path.exists(SERVICE_ACCOUNT_FILE):
                self.creds = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                self.service = build('sheets', 'v4', credentials=self.creds)
            else:
                logger.error("Service Account not found.")
        except Exception as e:
            logger.error(f"Sheets Auth Error: {e}")

    def append_to_sheet(self, data: dict) -> dict:
        """
        Atomic Append to Sheet.
        Columns: Timestamp | Sender | Source | Context | Intent | Priority | Summary | Actions | WAMID | Media
        """
        if not self.service or not SPREADSHEET_ID:
            logger.error("Sheets service not ready.")
            return {"success": False}

        try:
            # Prepare Row
            # A: Timestamp
            # B: Sender (Phone)
            # C: Source (Meta/WPP)
            # D: Context (Direct/Group Name)
            # E: Intent
            # F: Priority
            # G: Summary
            # H: Action Items
            # I: Legal ID (wamid)
            # J: Media Link

            ts = data.get('timestamp')
            if isinstance(ts, (int, float)): 
                ts = datetime.fromtimestamp(ts).isoformat()
            
            values = [[
                str(ts or datetime.now()),
                data.get('sender', ''),
                data.get('source', ''),
                data.get('context', ''),
                data.get('intent', ''),
                data.get('priority', ''),
                data.get('summary', ''),
                str(data.get('action_items', '')),
                data.get('legal_id', ''),
                data.get('media_link', '')
            ]]

            body = {
                'values': values
            }

            result = self.service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='Sheet1!A:J',
                valueInputOption='USER_ENTERED', # Allows strings to remain strings
                insertDataOption='INSERT_ROWS',  # Atomic append
                body=body
            ).execute()

            logger.info(f"Row appended. Updated range: {result.get('updates').get('updatedRange')}")
            return {"success": True, "updates": result}

        except Exception as e:
            logger.error(f"Sheet Append Failed: {e}")
            return {"success": False, "error": str(e)}

# Singleton
_instance = GoogleSheetsService()
def get_drive_service():
    return _instance
