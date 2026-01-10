"""
WhatsApp Web.js Gateway Client

Handles sending messages via the whatsapp-web.js gateway.
Supports both private messages and group messages.
"""

import logging
import os
import requests

logger = logging.getLogger(__name__)

# WPP Gateway Configuration
WPP_BASE_URL = os.getenv('WPP_BASE_URL', 'http://localhost:3000')
WPP_SESSION = os.getenv('WPP_SESSION', 'default')


def send_wpp_message(recipient: str, text: str) -> bool:
    """
    Send a text message via WPP Gateway.
    
    Args:
        recipient: Phone number (972xxx) or full JID (972xxx@c.us or group@g.us)
        text: Message content
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Determine if it's a group message
        is_group = '@g.us' in recipient
        
        if is_group:
            # Use group endpoint
            url = f"{WPP_BASE_URL}/send-group-message"
            payload = {
                "groupId": recipient,
                "message": text
            }
        else:
            # Use regular message endpoint
            url = f"{WPP_BASE_URL}/send-message"
            
            # Clean up recipient format
            phone = recipient
            if '@' in phone:
                phone = phone.split('@')[0]
            
            payload = {
                "phone": phone,
                "message": text
            }
        
        logger.info(f"WPP: Sending message to {recipient}")
        
        response = requests.post(
            url, 
            json=payload, 
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status') == 'success':
                logger.info(f"WPP: Reply sent to {recipient}")
                return True
            else:
                logger.warning(f"WPP: Unexpected response: {result}")
                return False
        elif response.status_code == 503:
            logger.error("WPP: Gateway not connected to WhatsApp. Scan QR code first.")
            return False
        else:
            logger.error(f"WPP: Failed to send reply: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        logger.error(f"WPP: Cannot connect to gateway at {WPP_BASE_URL}")
        return False
    except Exception as e:
        logger.error(f"WPP: Error sending message: {e}")
        return False


def send_wpp_image(recipient: str, image_url: str, caption: str = "") -> bool:
    """
    Send an image via WPP Gateway.
    
    Note: Image sending is not yet implemented in the gateway.
    For now, sends caption as text only.
    
    Args:
        recipient: Phone number or JID
        image_url: URL of the image to send
        caption: Optional caption
    
    Returns:
        bool: True if successful
    """
    # For now, just send the caption with a note about the image
    message = caption if caption else "📷 [Image]"
    if image_url and not caption:
        message = f"📷 Image: {image_url}"
    
    return send_wpp_message(recipient, message)


def get_wpp_session_status() -> dict:
    """
    Check the status of the WPP Gateway connection.
    
    Returns:
        dict: Session status info with 'connected' boolean
    """
    try:
        url = f"{WPP_BASE_URL}/status"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"connected": False, "error": response.text}
            
    except Exception as e:
        return {"connected": False, "error": str(e)}


def get_wpp_qr_code() -> dict:
    """
    Get QR code data for WhatsApp pairing.
    
    Returns:
        dict: Contains 'status' and optionally 'qr' data
    """
    try:
        url = f"{WPP_BASE_URL}/qr"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": response.text}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
