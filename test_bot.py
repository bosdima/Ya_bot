#!/usr/bin/env python3
"""
Тестовый бот с авторизацией в Яндексе и проверкой CalDAV
"""

import asyncio
import json
import os
import logging
import base64
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'https://oauth.yandex.ru/verification_code')
YANDEX_EMAIL = os.getenv('YANDEX_EMAIL', '')

# URL для OAuth
OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"

# Файл для хранения токена
TOKEN_FILE = 'yandex_token.json'


class Colors:
    """Цвета для консоли"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE} {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")


def print_success(text: str):
    print(f"{Colors.GREEN}[OK] {text}{Colors.END}")


def print_error(text: str):
    print(f"{Colors.RED}[ERROR] {text}{Colors.END}")


def print_info(text: str):
    print(f"{Colors.CYAN}[INFO] {text}{Colors.END}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.END}")


def save_token(token: str):
    """Сохраняет токен в файл и .env"""
    # В JSON файл
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'access_token': token, 'created_at': datetime.now().isoformat()}, f)
    
    # В .env файл
    env_lines = []
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            env_lines = f.readlines()
    
    token_found = False
    for i, line in enumerate(env_lines):
        if line.startswith('YANDEX_TOKEN='):
            env_lines[i] = f'YANDEX_TOKEN={token}\n'
            token_found = True
            break
    
    if not token_found:
        env_lines.append(f'\nYANDEX_TOKEN={token}\n')
    
    with open('.env', 'w') as f:
        f.writelines(env_lines)
    
    print_success(f"Token saved to {TOKEN_FILE} and .env")


def load_token() -> str:
    """Загружает токен из файла или .env"""
    # Из JSON файла
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                token = data.get('access_token')
                if token and len(token) > 30:
                    return token
        except:
            pass
    
    # Из .env
    token = os.getenv('YANDEX_TOKEN')
    if token and len(token) > 30:
        return token
    
    return None


def get_auth_url() -> str:
    """Формирует URL для авторизации"""
    scopes = [
        "cloud_api:disk.read",
        "cloud_api:disk.write",
        "cloud_api:disk.info",
        "calendar:read",
        "calendar:write",
    ]
    
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(scopes),
        "force_confirm": "yes",
    }
    
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> str:
    """Обменивает код авторизации на токен"""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(OAUTH_TOKEN_URL, data=data, timeout=15) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get('access_token')
                else:
                    text = await resp.text()
                    print_error(f"Code exchange error: {resp.status}")
                    print_info(f"Response: {text[:200]}")
                    return None
        except Exception as e:
            print_error(f"Error: {e}")
            return None


async def test_token_info(token: str):
    """Проверяет информацию о токене"""
    print_header("TOKEN INFORMATION")
    
    print_info(f"Token: {token[:20]}...{token[-10:]}")
    print_info(f"Length: {len(token)} chars")
    
    if token.startswith('y0_') or token.startswith('y1_'):
        print_success("Format: new (y0_/y1_)")
    elif token.startswith('AQAAAA'):
        print_success("Format: old (AQAAAA)")
    else:
        print_warning(f"Format: unknown (starts with {token[:10]}...)")
    
    url = "https://oauth.yandex.ru/tokeninfo"
    params = {"oauth_token": token}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print_success("Token info received:")
                    
                    scope = data.get('scope', '')
                    if scope:
                        scopes = scope.split()
                        print_info(f"Permissions ({len(scopes)}):")
                        
                        has_calendar = False
                        has_disk = False
                        
                        for s in scopes:
                            if 'calendar' in s:
                                print_success(f"  [OK] {s}")
                                has_calendar = True
                            elif 'disk' in s:
                                print_success(f"  [OK] {s}")
                                has_disk = True
                            else:
                                print_info(f"  [*] {s}")
                        
                        if has_calendar:
                            print_success("\n[OK] Calendar permissions: YES")
                        else:
                            print_error("\n[ERROR] Calendar permissions: NO")
                            
                        if has_disk:
                            print_success("[OK] Disk permissions: YES")
                        else:
                            print_warning("[WARN] Disk permissions: NO")
                    
                    return data
                else:
                    print_warning(f"Could not get token info: {resp.status}")
                    return None
        except Exception as e:
            print_error(f"Error: {e}")
            return None


async def test_disk_access(token: str):
    """Проверяет доступ к Яндекс.Диску"""
    print_header("YANDEX DISK ACCESS")
    
    headers = {"Authorization": f"OAuth {token}"}
    url = "https://cloud-api.yandex.net/v1/disk"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print_success("Disk accessible!")
                    print_info(f"  User: {data.get('user', {}).get('display_name', 'N/A')}")
                    used = int(data.get('used_space', 0))
                    total = int(data.get('total_space', 0))
                    print_info(f"  Used: {used // (1024**3)} GB / {total // (1024**3)} GB")
                    return True
                else:
                    print_error(f"Access error: {resp.status}")
                    return False
        except Exception as e:
            print_error(f"Error: {e}")
            return False


async def test_caldav_access(token: str, email: str):
    """Проверяет доступ к CalDAV"""
    print_header("CalDAV ACCESS")
    
    if not email:
        print_warning("Email not specified")
        return False
    
    print_info(f"Email: {email}")
    
    auth_string = f"{email}:{token}"
    encoded = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": "1"
    }
    
    body = '''<?xml version="1.0" encoding="utf-8"?>
<propfind xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <prop>
    <displayname/>
    <resourcetype/>
  </prop>
</propfind>'''
    
    url = "https://caldav.yandex.ru/"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request("PROPFIND", url, headers=headers, data=body.encode('utf-8'), timeout=15) as resp:
                print_info(f"Status: {resp.status}")
                
                if resp.status == 207:
                    print_success("CalDAV WORKS!")
                    
                    text = await resp.text()
                    import xml.etree.ElementTree as ET
                    
                    try:
                        root = ET.fromstring(text)
                        namespaces = {'D': 'DAV:', 'C': 'urn:ietf:params:xml:ns:caldav'}
                        
                        calendars = []
                        for response in root.findall('.//D:response', namespaces):
                            href = response.find('.//D:href', namespaces)
                            displayname = response.find('.//D:displayname', namespaces)
                            resourcetype = response.find('.//D:resourcetype', namespaces)
                            
                            if resourcetype is not None:
                                calendar_tag = resourcetype.find('.//C:calendar', namespaces)
                                if calendar_tag is not None and href is not None:
                                    name = displayname.text if displayname is not None else 'Unnamed'
                                    calendars.append({'path': href.text, 'name': name})
                        
                        if calendars:
                            print_success(f"Found calendars: {len(calendars)}")
                            for cal in calendars:
                                print_info(f"  [CAL] {cal['name']}: {cal['path']}")
                        else:
                            print_warning("No calendars found")
                    except Exception as e:
                        print_warning(f"Parse error: {e}")
                    
                    return True
                    
                elif resp.status == 401:
                    print_error("Authorization error 401")
                    print_info("  Check token permissions and email")
                    return False
                else:
                    print_error(f"Status: {resp.status}")
                    return False
                    
        except Exception as e:
            print_error(f"Error: {e}")
            return False


async def process_authorization_code(code: str):
    """Обрабатывает код авторизации"""
    print_header("EXCHANGING CODE FOR TOKEN")
    print_info("Exchanging code...")
    
    token = await exchange_code_for_token(code)
    
    if not token:
        print_error("Failed to get token!")
        return None
    
    print_success("Token received!")
    print_info(f"Token: {token[:20]}...{token[-10:]}")
    print_info(f"Length: {len(token)} chars")
    
    # Сохраняем токен
    save_token(token)
    
    # Проверяем токен
    await test_token_info(token)
    
    # Проверяем Диск
    await test_disk_access(token)
    
    # Проверяем CalDAV
    await test_caldav_access(token, YANDEX_EMAIL)
    
    return token


async def main():
    print_header("YANDEX AUTH TEST BOT")
    print_info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_info(f"ADMIN_ID: {ADMIN_ID}")
    print_info(f"CLIENT_ID: {CLIENT_ID[:20]}...")
    
    # Проверяем наличие токена
    existing_token = load_token()
    
    if existing_token:
        print_header("EXISTING TOKEN FOUND")
        print_info(f"Token: {existing_token[:20]}...{existing_token[-10:]}")
        
        # Проверяем токен
        token_info = await test_token_info(existing_token)
        
        if token_info:
            await test_disk_access(existing_token)
            await test_caldav_access(existing_token, YANDEX_EMAIL)
            
            print_header("STATUS")
            print_success("Token is valid! Bot ready to work.")
        else:
            print_warning("Token invalid. New authorization needed.")
            existing_token = None
    
    if not existing_token:
        print_header("AUTHORIZATION REQUIRED")
        print_info("To get a token:")
        print_info("1. Open this link in browser:")
        
        auth_url = get_auth_url()
        print(f"\n{Colors.BOLD}{auth_url}{Colors.END}\n")
        
        print_info("2. Login to Yandex and allow access")
        print_info("3. After redirect, copy code from address bar")
        print_info("   (everything after 'code=' until '&' or end)")
        print_info("4. Paste code here:")
        
        try:
            code = input(f"\n{Colors.BOLD}Authorization code: {Colors.END}").strip()
            
            if code:
                await process_authorization_code(code)
            else:
                print_error("No code entered!")
        except EOFError:
            print_error("Cannot read input (non-interactive mode)")
            print_info("Please add YANDEX_TOKEN manually to .env file")
            print_info("Get token from: https://oauth.yandex.ru/authorize?response_type=token&client_id=" + CLIENT_ID)
    
    print_header("DONE")
    print_success("Test completed!")
    print_info("If CalDAV works, you can run the full bot.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print_error(f"Critical error: {e}")
        import traceback
        traceback.print_exc()