# WhatsApp Voice Notes Agent

AI-powered WhatsApp assistant that transcribes voice notes and text messages, extracts actionable intelligence, and saves everything to a searchable Google Sheet.

## Features

- 🎙️ **Voice Note Transcription** - Automatically transcribes voice messages (multi-language support)
- 📝 **Text Message Processing** - Save text notes with "keepAI" trigger
- 🧠 **AI Analysis** - Extracts summaries, action items, deadlines, and shopping lists
- 📊 **Google Sheets Integration** - All notes saved to a searchable spreadsheet
- ✅ **Instant Confirmation** - User receives summary via WhatsApp

## Architecture

```
WhatsApp → Meta Cloud API → Webhook Server → Gemini AI → Google Sheets
                                    ↓
                           WhatsApp Confirmation
```

## Setup

### Prerequisites

- Docker & Docker Compose
- Google Cloud Project with Vertex AI enabled
- Meta WhatsApp Business API account
- Google Service Account with Sheets API access

### Configuration

1. **Service Account**: Create `service-account.json` with Google Cloud credentials
2. **Environment Variables** in `docker-compose.yml`:
   - `SPREADSHEET_ID` - Your Google Sheet ID
   - Set Meta API token in `webhook_server.py`

### Running

```bash
docker-compose up -d
```

### Expose Webhook (Development)

```bash
ngrok http 8082
```

Configure the ngrok URL in Meta's WhatsApp API settings.

## Usage

### Voice Notes
Simply send a voice note to the WhatsApp Business number. The agent will:
1. Transcribe the audio
2. Extract action items, deadlines, shopping lists
3. Save to Google Sheets
4. Send confirmation back

### Text Messages
Include "keepAI" anywhere in your message:
```
keepAI remember to buy milk and call mom tomorrow
```

## Files

| File | Purpose |
|------|---------|
| `webhook_server.py` | Main FastAPI application |
| `google_drive_service.py` | Google Sheets integration |
| `docker-compose.yml` | Container orchestration |
| `Dockerfile` | Python container build |
| `requirements.txt` | Python dependencies |

## License

Private - All rights reserved
