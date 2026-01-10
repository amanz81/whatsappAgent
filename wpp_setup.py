"""
Automated WPPConnect Server Setup Script.

Verifies the official WPPConnect Server configuration.
"""

import os
import requests
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
WPP_BASE_URL = os.getenv('WPP_BASE_URL', 'http://wppconnect:21465')
SESSION = os.getenv('WPP_SESSION', 'default')
SECRET_KEY = os.getenv('WPP_SECRET_KEY')

def check_health():
    """Check WPPConnect Server info."""
    try:
        # Official server doesn't have a simple /health root usually, 
        # but /api/{session}/check-connection-session or similar.
        # Or just checking if port is open.
        # We'll try to generate a token or get status.
        
        # Try version endpoint if available or status
        url = f"{WPP_BASE_URL}/api/{SESSION}/status-session"
        headers = {"Authorization": f"Bearer {SECRET_KEY}"}
        
        logger.info(f"Checking Session Status at: {url}")
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data = res.json()
            logger.info(f"✅ Server is UP. Response: {data}")
            return True
        elif res.status_code == 401:
            logger.error("❌ Unauthorized. Check SECRET_KEY.")
            return False
        else:
            logger.warning(f"⚠️ Server returned {res.status_code}. It might be starting up.")
            return False

    except Exception as e:
        logger.error(f"❌ Connection Failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("--- WPPConnect Server Verification ---")
    if check_health():
        logger.info("✅ WPPConnect Server is Online and Reachable.")
    else:
        logger.warning("⚠️ Could not verify WPPConnect availability.")
