/**
 * WhatsApp Web.js Gateway
 * 
 * A simple gateway that connects to WhatsApp Web and forwards messages
 * to the Python agent webhook. Also provides an API for sending messages.
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const axios = require('axios');

// Configuration from environment
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:8082/webhook/wpp';
const PORT = process.env.PORT || 3000;
const SESSION_NAME = process.env.SESSION_NAME || 'default';

// Express app for API
const app = express();
app.use(express.json());

// Store client state
let clientReady = false;
let qrCodeData = null;

const fs = require('fs');
const path = require('path');

// AGGRESSIVE CLEANUP: Remove lock files before starting
const sessionDir = '/app/session';
if (fs.existsSync(sessionDir)) {
    try {
        const deleteLockFiles = (dir) => {
            const files = fs.readdirSync(dir);
            for (const file of files) {
                const fullPath = path.join(dir, file);
                if (fs.lstatSync(fullPath).isDirectory()) {
                    deleteLockFiles(fullPath);
                } else if (file === 'SingletonLock') {
                    console.log(`🧹 Creating clean slate: Removing lock file: ${fullPath}`);
                    fs.unlinkSync(fullPath);
                }
            }
        };
        deleteLockFiles(sessionDir);
    } catch (e) {
        console.error('Warning during cleanup:', e.message);
    }
}

// Initialize WhatsApp client with local auth (persists session)
const client = new Client({
    authStrategy: new LocalAuth({
        clientId: SESSION_NAME,
        dataPath: '/app/session'
    }),
    authTimeoutMs: 60000, // Wait 60s for auth
    qrMaxRetries: 10,     // Retry QR more times
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process',
            '--disable-gpu'
        ]
    }
});

// QR Code event - display in terminal
client.on('qr', (qr) => {
    console.log('QR Code received. Scan with your WhatsApp app:');
    console.log('');
    qrcode.generate(qr, { small: true });
    console.log('');
    console.log('Or visit http://localhost:' + PORT + '/qr for QR code data');
    qrCodeData = qr;
});

// Client ready event
client.on('ready', () => {
    console.log('✅ WhatsApp client is ready!');
    clientReady = true;
    qrCodeData = null;  // Clear QR once connected
});

// Authentication success
client.on('authenticated', () => {
    console.log('✅ Authentication successful!');
});

// Authentication failure
client.on('auth_failure', (msg) => {
    console.error('❌ Authentication failed:', msg);
    clientReady = false;
});

// Disconnected
client.on('disconnected', (reason) => {
    console.log('❌ Client disconnected:', reason);
    clientReady = false;
});

// Message received - forward to webhook
client.on('message', async (msg) => {
    try {
        console.log(`📩 Message from ${msg.from}: ${msg.body.substring(0, 50)}...`);

        // Get contact info
        const contact = await msg.getContact();
        const chat = await msg.getChat();

        // Build webhook payload (similar to WPPConnect format)
        const payload = {
            event: 'message',
            session: SESSION_NAME,
            data: {
                from: msg.from,
                to: msg.to,
                body: msg.body,
                type: msg.type,
                timestamp: msg.timestamp,
                isGroupMsg: chat.isGroup,
                notifyName: contact.pushname || contact.name,
                sender: {
                    id: msg.author || msg.from,
                    name: contact.pushname || contact.name
                },
                chat: {
                    id: chat.id._serialized,
                    name: chat.name
                },
                id: {
                    _serialized: msg.id._serialized
                }
            }
        };

        // Handle voice messages / audio
        if (msg.hasMedia && (msg.type === 'ptt' || msg.type === 'audio')) {
            const media = await msg.downloadMedia();
            payload.data.mediaUrl = `data:${media.mimetype};base64,${media.data}`;
            payload.data.mimetype = media.mimetype;
        }

        // Forward to webhook
        console.log(`📤 Forwarding to webhook: ${WEBHOOK_URL}`);
        await axios.post(WEBHOOK_URL, payload, {
            headers: { 'Content-Type': 'application/json' },
            timeout: 30000
        });
        console.log(`✅ Webhook forwarded successfully`);

    } catch (error) {
        console.error('❌ Error forwarding message:', error.message);
    }
});

// ============ API Endpoints ============

// Health check
app.get('/health', (req, res) => {
    res.json({
        status: clientReady ? 'connected' : 'disconnected',
        session: SESSION_NAME,
        hasQR: qrCodeData !== null
    });
});

const QRCode = require('qrcode');

// ... (existing code) ...

// Get QR code (render as HTML)
app.get('/qr', async (req, res) => {
    if (clientReady) {
        res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>WhatsApp Gateway - Connected</title>
                <meta http-equiv="refresh" content="10">
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f2f5; }
                    .card { text-align: center; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 400px; }
                    h1 { color: #008069; margin-bottom: 10px; }
                    .icon { font-size: 64px; margin-bottom: 20px; }
                    p { color: #54656f; font-size: 16px; margin: 0; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="icon">✅</div>
                    <h1>WhatsApp Connected!</h1>
                    <p>The gateway is active and ready.</p>
                </div>
            </body>
            </html>
        `);
    } else if (qrCodeData) {
        try {
            // Generate QR code as Data URL (image/png)
            const qrImage = await QRCode.toDataURL(qrCodeData);

            res.send(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>WhatsApp Gateway - Link Device</title>
                    <meta http-equiv="refresh" content="15">
                    <style>
                        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f2f5; }
                        .card { text-align: center; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 400px; }
                        h1 { color: #41525d; margin: 0 0 8px 0; font-size: 28px; font-weight: 300; }
                        .instructions { color: #54656f; font-size: 16px; line-height: 1.5; margin-bottom: 30px; }
                        .qr-container { background: white; padding: 10px; display: inline-block; border: 1px solid #e9edef; border-radius: 8px; }
                        img { display: block; width: 264px; height: 264px; }
                        .refresh-note { color: #8696a0; font-size: 14px; margin-top: 24px; }
                        ol { text-align: left; padding-left: 20px; color: #54656f; margin-bottom: 24px; }
                        li { margin-bottom: 8px; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Link with WhatsApp</h1>
                        <ol class="instructions">
                            <li>Open WhatsApp on your phone</li>
                            <li>Tap <strong>Menu</strong> or <strong>Settings</strong> and select <strong>Linked Devices</strong></li>
                            <li>Tap on <strong>Link a Device</strong></li>
                            <li>Point your phone to this screen to capture the code</li>
                        </ol>
                        <div class="qr-container">
                            <img src="${qrImage}" alt="Scan me">
                        </div>
                        <p class="refresh-note">Page auto-refreshes to keep code valid</p>
                    </div>
                </body>
                </html>
            `);
        } catch (err) {
            res.status(500).send('Error generating QR code: ' + err.message);
        }
    } else {
        res.send(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>WhatsApp Gateway - Starting</title>
                <meta http-equiv="refresh" content="3">
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f2f5; }
                    .card { text-align: center; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 400px; }
                    .loader { border: 4px solid #f3f3f3; border-top: 4px solid #008069; border-radius: 50%; width: 48px; height: 48px; animation: spin 1s linear infinite; margin: 0 auto 24px auto; }
                    h2 { color: #41525d; font-weight: 500; margin: 0; }
                    p { color: #8696a0; margin-top: 8px; }
                    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="loader"></div>
                    <h2>Initializing...</h2>
                    <p>Connecting to WhatsApp servers</p>
                </div>
            </body>
            </html>
        `);
    }
});

// Send text message
app.post('/send-message', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp client not ready' });
    }

    const { phone, message } = req.body;
    if (!phone || !message) {
        return res.status(400).json({ error: 'phone and message are required' });
    }

    try {
        // Format phone number
        let chatId = phone;
        if (!phone.includes('@')) {
            chatId = phone.replace(/[^0-9]/g, '') + '@c.us';
        }

        const result = await client.sendMessage(chatId, message);
        console.log(`📤 Message sent to ${phone}`);
        res.json({ status: 'success', messageId: result.id._serialized });
    } catch (error) {
        console.error('Error sending message:', error);
        res.status(500).json({ error: error.message });
    }
});

// Send message to group
app.post('/send-group-message', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp client not ready' });
    }

    const { groupId, message } = req.body;
    if (!groupId || !message) {
        return res.status(400).json({ error: 'groupId and message are required' });
    }

    try {
        const result = await client.sendMessage(groupId, message);
        console.log(`📤 Message sent to group ${groupId}`);
        res.json({ status: 'success', messageId: result.id._serialized });
    } catch (error) {
        console.error('Error sending group message:', error);
        res.status(500).json({ error: error.message });
    }
});

// Get connection status
app.get('/status', (req, res) => {
    res.json({
        connected: clientReady,
        session: SESSION_NAME
    });
});

// Start Express server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`🚀 WPP Gateway API running on port ${PORT}`);
    console.log(`📡 Webhook URL: ${WEBHOOK_URL}`);
    console.log('');
});

// Initialize WhatsApp client
console.log('🔄 Initializing WhatsApp client...');
client.initialize();
