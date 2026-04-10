#!/usr/bin/env python3
"""
Тестовый бот с авторизацией в Яндексе и проверкой CalDAV
(исправленная версия - без tokeninfo для новых токенов)
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

# Файл для хранения токена
TOKEN_FILE = 'yandex_token.json'


class Colors:
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


def load_token() -> str:
    """Загружает токен"""
    token = os.getenv('YANDEX_TOKEN')
    if token and len(token) > 30:
        return token
    
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return data.get('access_token')
        except:
            pass
    
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
                elif resp.status == 401:
                    print_error("Disk access: 401 Unauthorized")
                    return False
                else:
                    print_error(f"Disk access error: {resp.status}")
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
                    print_error("CalDAV: 401 Unauthorized")
                    print_info("  Check token permissions (calendar:read, calendar:write)")
                    return False
                else:
                    print_error(f"CalDAV status: {resp.status}")
                    text = await resp.text()
                    if 'html' in text.lower():
                        print_error("  Server returned HTML instead of XML")
                    return False
                    
        except Exception as e:
            print_error(f"Error: {e}")
            return False


async def test_create_event(token: str, email: str):
    """Тест создания события в календаре"""
    print_header("TEST CREATE EVENT")
    
    if not email:
        print_warning("Email not specified")
        return False
    
    import uuid
    from datetime import timedelta
    import pytz
    
    auth_string = f"{email}:{token}"
    encoded = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "text/calendar; charset=utf-8"
    }
    
    # Создаем событие на завтра
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)
    start_time = now + timedelta(days=1)
    start_time = start_time.replace(hour=15, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(hours=1)
    
    event_uid = f"{uuid.uuid4()}@test"
    
    start_utc = start_time.astimezone(pytz.UTC)
    end_utc = end_time.astimezone(pytz.UTC)
    
    start_str = start_utc.strftime('%Y%m%dT%H%M%SZ')
    end_str = end_utc.strftime('%Y%m%dT%H%M%SZ')
    now_str = datetime.now(pytz.UTC).strftime('%Y%m%dT%H%M%SZ')
    
    ical_data = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test Bot//RU
BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{now_str}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:[TEST] CalDAV Event
DESCRIPTION:Test event from diagnostic bot
END:VEVENT
END:VCALENDAR"""
    
    url = f"https://caldav.yandex.ru/default/{event_uid}.ics"
    
    print_info(f"Creating test event...")
    print_info(f"  Time: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%H:%M')}")
    
    async with aiohttp.ClientSession() as session:
        try:
            # Создаем событие
            async with session.put(url, headers=headers, data=ical_data.encode('utf-8'), timeout=15) as resp:
                if resp.status in [201, 204]:
                    print_success(f"Event created! (status {resp.status})")
                    print_success(f"  ID: {event_uid}")
                    
                    # Удаляем тестовое событие
                    print_info("Deleting test event...")
                    async with session.delete(url, headers=headers, timeout=15) as del_resp:
                        if del_resp.status in [200, 204]:
                            print_success("Event deleted")
                        else:
                            print_warning(f"Could not delete: {del_resp.status}")
                    
                    return True
                else:
                    print_error(f"Create error: {resp.status}")
                    text = await resp.text()
                    print_info(f"Response: {text[:200]}")
                    return False
                    
        except Exception as e:
            print_error(f"Error: {e}")
            return False


async def main():
    print_header("YANDEX CALDAV TEST")
    print_info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Загружаем токен
    token = load_token()
    
    if not token:
        print_error("Token not found!")
        print_info("Add YANDEX_TOKEN to .env file")
        return
    
    print_header("TOKEN FOUND")
    print_info(f"Token: {token[:20]}...{token[-10:]}")
    print_info(f"Length: {len(token)} chars")
    
    if token.startswith('y0_') or token.startswith('y1_'):
        print_success("Format: new (y0_/y1_) - OK")
    elif token.startswith('AQAAAA'):
        print_success("Format: old (AQAAAA) - OK")
    
    # Проверяем Диск
    disk_ok = await test_disk_access(token)
    
    # Проверяем CalDAV
    caldav_ok = await test_caldav_access(token, YANDEX_EMAIL)
    
    # Если CalDAV работает, пробуем создать событие
    if caldav_ok:
        await test_create_event(token, YANDEX_EMAIL)
    
    # Итоги
    print_header("SUMMARY")
    
    if disk_ok:
        print_success("Yandex Disk: OK")
    else:
        print_error("Yandex Disk: FAIL")
    
    if caldav_ok:
        print_success("CalDAV: OK")
        print_success("\n[SUCCESS] CalDAV is working!")
        print_success("You can now use the full bot with calendar sync!")
    else:
        print_error("CalDAV: FAIL")
        print_info("\nChecklist:")
        print_info("  1. Token has calendar:read and calendar:write permissions")
        print_info("  2. Email is correct: " + YANDEX_EMAIL)
        print_info("  3. You have at least one calendar at calendar.yandex.ru")
    
    print_header("DONE")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print_error(f"Critical error: {e}")
        import traceback
        traceback.print_exc()