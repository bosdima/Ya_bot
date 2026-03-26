import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_config():
    """Test if configuration is loaded correctly"""
    load_dotenv()
    
    bot_token = os.getenv('TG_BOT_TOKEN')
    client_id = os.getenv('YANDEX_CLIENT_ID')
    client_secret = os.getenv('YANDEX_CLIENT_SECRET')
    target_path = os.getenv('YANDEX_TARGET_PATH')
    
    print("=" * 50)
    print("Configuration Test")
    print("=" * 50)
    print(f"Bot Token: {'✓ Present' if bot_token else '✗ Missing'} ({bot_token[:10] if bot_token else 'None'}...)")
    print(f"Client ID: {'✓ Present' if client_id else '✗ Missing'} ({client_id[:10] if client_id else 'None'}...)")
    print(f"Client Secret: {'✓ Present' if client_secret else '✗ Missing'}")
    print(f"Target Path: {'✓ Present' if target_path else '✗ Missing'} ({target_path})")
    print("=" * 50)
    
    if not bot_token:
        print("ERROR: TG_BOT_TOKEN is missing in .env file!")
    if not client_id:
        print("ERROR: YANDEX_CLIENT_ID is missing in .env file!")
    if not client_secret:
        print("ERROR: YANDEX_CLIENT_SECRET is missing in .env file!")
    
    return all([bot_token, client_id, client_secret])

if __name__ == '__main__':
    test_config()