# 📖 B2B Operations Manager - User Guide

## 1. Daily Operations (Business Workflow)

### 🆕 Onboarding a New Client
When you sign a new client or want to allow a new number to interact with the bot:
1.  Open the **Dashboard** (e.g., `http://localhost:8082`).
2.  Find the **"Add Client"** section.
3.  Enter their **Name** (e.g., "Cafe Rothschild") and **Phone Number** (e.g., `97250...`).
4.  Click **Add**.
    *   *Effect:* They are instantly whitelisted. The bot will now reply to them.

### 💬 Handling Messages
*   **The Bot is Autonomous**: You don't need to do anything for standard messages.
*   **The Flow**:
    1.  Client sends message (Text/Voice) ->
    2.  Bot Identifies Intent (Order, Inquiry, Urgent, etc.) ->
    3.  Bot Log row to **Google Sheets** ->
    4.  Bot Replies to Client on WhatsApp.
*   **Your Job**: Monitor the **Google Sheet**. This is your "Inbox" of sorted tasks.

### 🛑 Managing Incidents (Loop/Spam)
If a client or bot goes crazy:
1.  Go to **Dashboard**.
2.  **Remove Client** from the list (using the delete button or editing `clients.json`).
3.  The bot immediately stops responding to them.

---

## 2. Technical Deployment (Going "Real World")

Currently, the bot lives on your computer. If you close your laptop, **the bot dies**.

### Option A: The "Dedicated Laptop" (Free/Easy)
*   **Setup**: Leave this computer on 24/7, connected to power and internet.
*   **Pros**: Free, no new setup.
*   **Cons**: Can't move laptop, power outages stop the bot.

### Option B: Cloud VPS (Recommended for Production)
*   **Setup**: Rent a small Linux server (Ubuntu) on DigitalOcean, Hetzner, or AWS Lightsail ($5-10/month).
*   **Steps**:
    1.  Install Docker & Docker Compose on the server.
    2.  Copy your project files (via Git).
    3.  Run `docker-compose up -d`.
    4.  Scan QR code (view logs via SSH).
*   **Pros**: 24/7 Uptime, professional, independent of your phone/laptop.

### ⚠️ Important: WhatsApp Linked Device
*   WhatsApp Web allows **4 linked devices**.
*   This bot counts as **1 device**.
*   It works even if your main phone is offline (for up to 14 days), but check the connection status in the Dashboard regularly.

## 3. Maintenance
*   **Session Relogin**: Every few weeks/months, WhatsApp might log you out.
    *   *Symptom*: Dashboard says "Disconnected".
    *   *Fix*: Restart container, Scan QR again.
*   **Updates**: To add features, edit code locally, push to Git, and `git pull` on your server.
