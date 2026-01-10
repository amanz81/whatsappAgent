"""
WPPConnect Session Helper

Run this script to generate a token and start a WPPConnect session.
Then visit the QR code URL provided.
"""
import requests
import time

WPP_URL = "http://localhost:21465"
SECRET_KEY = "THISISMYSECURETOKEN"
SESSION = "default"

def main():
    print("=" * 50)
    print("WPPConnect Session Setup")
    print("=" * 50)
    
    # Step 1: Generate Token
    print("\n1. Generating token...")
    token_url = f"{WPP_URL}/api/{SESSION}/{SECRET_KEY}/generate-token"
    resp = requests.post(token_url)
    if resp.status_code != 200 and resp.status_code != 201:
        print(f"   ERROR: {resp.status_code} - {resp.text}")
        return
    
    data = resp.json()
    token = data.get('full') or data.get('token')
    print(f"   Token: {token[:50]}...")
    
    # Step 2: Start Session
    print("\n2. Starting session...")
    session_url = f"{WPP_URL}/api/{SESSION}/start-session"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {"waitQrCode": False}
    
    resp = requests.post(session_url, json=body, headers=headers)
    print(f"   Response: {resp.status_code}")
    print(f"   {resp.text[:500]}")
    
    # Wait for session to initialize
    print("\n3. Waiting for session to initialize...")
    time.sleep(3)
    
    # Step 3: Get QR Code URL
    print("\n4. QR Code URL:")
    qr_url = f"{WPP_URL}/api/{SESSION}/qrcode-session"
    print(f"   Open in browser: {qr_url}")
    
    # Try to get status
    print("\n5. Checking session status...")
    status_url = f"{WPP_URL}/api/{SESSION}/status-session"
    resp = requests.get(status_url, headers=headers)
    print(f"   Status: {resp.text[:200]}")
    
    print("\n" + "=" * 50)
    print("Next steps:")
    print("1. Open the QR code URL in your browser")
    print("2. Scan with your WhatsApp app (Settings > Linked Devices)")
    print("=" * 50)

if __name__ == "__main__":
    main()
