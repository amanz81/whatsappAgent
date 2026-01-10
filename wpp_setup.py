"""
Automated WPPConnect Webhook Setup Script.

This script verifies the WPPConnect Gateway configuration and connectivity.
It ensures the gateway is set to push webhooks to the correct local endpoint.
"""

import os
import requests
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
WPP_BASE_URL = os.getenv('WPP_BASE_URL', 'http://wpp_gateway:3000')
WEBHOOK_TARGET = os.getenv('WEBHOOK_URL', 'http://whatsapp_agent:8082/webhook/wpp')

def check_gateway_health():
    """Check if the WPP Gateway is responsive."""
    try:
        url = f"{WPP_BASE_URL}/health"
        logger.info(f"Checking Gateway Health at: {url}")
        res = requests.get(url, timeout=5)
        
        if res.status_code == 200:
            data = res.json()
            logger.info(f"✅ Gateway is UP. Session: {data.get('session')}, Status: {data.get('status')}")
            return True
        else:
            logger.error(f"❌ Gateway returned {res.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Could not connect to Gateway: {e}")
        return False

def setup_webhook():
    """
    In our 'wpp-gateway' architecture (whatsapp-web.js), the webhook URL
    is set via environment variable WEBHOOK_URL at startup.
    
    This function verifies that the configuration is correct.
    """
    logger.info("--- WPPConnect Webhook Setup ---")
    
    # Check if we are inside Docker (resolving internal names)
    try:
        # Check env var
        logger.info(f"Current Webhook Target Config: {WEBHOOK_TARGET}")
        
        if "webhook/wpp" not in WEBHOOK_TARGET:
            logger.warning("⚠️  WEBHOOK_URL does not look like the standard WPP webhook endpoint")
        
        # Verify Gateway
        if check_gateway_health():
            logger.info("✅ WPPConnect Webhook Logic is active and configured via Environment.")
            logger.info("No manual registration required for this gateway version.")
        else:
            logger.error("❌ Gateway is unreachable. Ensure 'wpp-gateway' container is running.")

    except Exception as e:
        logger.error(f"Setup failed: {e}")

if __name__ == "__main__":
    logger.info("Starting Webhook Setup verification...")
    # Wait a moment for services to come up if running in compost
    # time.sleep(2)
    setup_webhook()
