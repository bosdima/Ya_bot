#!/usr/bin/env python3
"""
Тест прямого доступа к календарю через секретный токен
"""

import asyncio
import json
import os
import base64
import uuid
from datetime import datetime, timedelta
import aiohttp
import pytz
from dotenv import load_dotenv

load_dotenv()

YANDEX_TOKEN = os.getenv('YANDEX_TOKEN')
YANDEX_EMAIL = os.getenv('YANDEX_EMAIL', '')
CALENDAR_TOKEN = "d5f61f1bef8fd8e2da7c45c9b5099702dea76d7b"  # Ваш секретный токен

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_success(msg): print(f"{Colors.GREEN}[OK] {msg}{Colors.END}")
def print_error(msg): print(f"{Colors.RED}[ERROR] {msg}{Colors.END}")
def print_info(msg): print(f"{Colors.CYAN}[INFO] {msg}{Colors.END}")
def print_header(msg): print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*50}{Colors.END}\n{Colors.BOLD}{msg}{Colors.END}\n{Colors.BOLD}{Colors.BLUE}{'='*50}{Colors.END}")


async def test_direct_calendar_access():
    """Прямой доступ к календарю через секретный токен"""
    print_header("ТЕСТ ПРЯМОГО ДОСТУПА К КАЛЕНДАРЮ")
    
    if not YANDEX_TOKEN:
        print_error("YANDEX_TOKEN not found!")
        return False
    
    print_info(f"Email: {YANDEX_EMAIL}")
    print_info(f"Calendar token: {CALENDAR_TOKEN[:20]}...")
    
    # Basic Auth
    auth = base64.b64encode(f"{YANDEX_EMAIL}:{YANDEX_TOKEN}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "text/calendar; charset=utf-8"
    }
    
    # Создаем тестовое событие
    tz = pytz.timezone('Europe/Moscow')
    start_time = datetime.now(tz) + timedelta(hours=1)
    start_time = start_time.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(hours=1)
    
    event_uid = f"{uuid.uuid4()}@test"
    
    start_utc = start_time.astimezone(pytz.UTC)
    end_utc = end_time.astimezone(pytz.UTC)
    
    ical = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//RU
BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{datetime.now(pytz.UTC).strftime('%Y%m%dT%H%M%SZ')}
DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:[ТЕСТ] Прямой доступ к календарю
DESCRIPTION:Проверка через секретный токен
END:VEVENT
END:VCALENDAR"""
    
    # Пробуем разные пути
    paths_to_try = [
        f"/calendars/{CALENDAR_TOKEN}/",
        f"/{CALENDAR_TOKEN}/",
        "/default/",
        "/",
        "/calendars/default/",
        "/calendars/primary/",
    ]
    
    async with aiohttp.ClientSession() as session:
        for path in paths_to_try:
            url = f"https://caldav.yandex.ru{path}{event_uid}.ics"
            print_info(f"\nTrying: PUT {url}")
            
            try:
                async with session.put(url, headers=headers, data=ical.encode(), timeout=15) as resp:
                    if resp.status in [201, 204]:
                        print_success(f"SUCCESS! Path: {path}")
                        print_success(f"Event created! ID: {event_uid}")
                        
                        # Удаляем тестовое событие
                        async with session.delete(url, headers=headers, timeout=15) as del_resp:
                            if del_resp.status in [200, 204]:
                                print_success("Test event deleted")
                            else:
                                print_info(f"Delete status: {del_resp.status}")
                        
                        return path
                    else:
                        print_info(f"Status: {resp.status}")
                        if resp.status == 404:
                            print_info("  -> Path not found")
                        elif resp.status == 401:
                            print_error("  -> Unauthorized")
                            return None
                        elif resp.status == 403:
                            print_error("  -> Forbidden")
                        else:
                            text = await resp.text()
                            if text:
                                print_info(f"  Response: {text[:100]}")
            except Exception as e:
                print_error(f"Error: {e}")
    
    return None


async def test_propfind_calendars():
    """PROPFIND запрос для получения списка календарей"""
    print_header("PROPFIND CALENDARS")
    
    if not YANDEX_TOKEN:
        print_error("YANDEX_TOKEN not found!")
        return
    
    auth = base64.b64encode(f"{YANDEX_EMAIL}:{YANDEX_TOKEN}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": "1"
    }
    
    body = '''<?xml version="1.0" encoding="utf-8"?>
<propfind xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <prop>
    <displayname/>
    <resourcetype/>
    <C:calendar-description/>
    <D:current-user-principal/>
  </prop>
</propfind>'''
    
    urls = [
        "https://caldav.yandex.ru/",
        f"https://caldav.yandex.ru/calendars/{CALENDAR_TOKEN}/",
        "https://caldav.yandex.ru/calendars/",
        "https://caldav.yandex.ru/principals/",
    ]
    
    async with aiohttp.ClientSession() as session:
        for url in urls:
            print_info(f"\nPROPFIND {url}")
            try:
                async with session.request("PROPFIND", url, headers=headers, data=body.encode(), timeout=15) as resp:
                    print_info(f"Status: {resp.status}")
                    
                    if resp.status == 207:
                        text = await resp.text()
                        print_success("Got 207 Multi-Status")
                        
                        # Парсим ответ
                        import xml.etree.ElementTree as ET
                        try:
                            root = ET.fromstring(text)
                            ns = {'D': 'DAV:', 'C': 'urn:ietf:params:xml:ns:caldav'}
                            
                            for resp_elem in root.findall('.//D:response', ns):
                                href = resp_elem.find('.//D:href', ns)
                                displayname = resp_elem.find('.//D:displayname', ns)
                                
                                if href is not None:
                                    name = displayname.text if displayname is not None else 'N/A'
                                    print_info(f"  Found: {href.text} ({name})")
                        except:
                            print_info(f"  Response: {text[:300]}")
                    else:
                        print_info(f"  Status: {resp.status}")
            except Exception as e:
                print_error(f"  Error: {e}")


async def main():
    print_header("YANDEX CALENDAR DIRECT ACCESS TEST")
    
    # Тест 1: PROPFIND для поиска календарей
    await test_propfind_calendars()
    
    # Тест 2: Прямое создание события
    working_path = await test_direct_calendar_access()
    
    print_header("RESULT")
    if working_path:
        print_success(f"Working path found: {working_path}")
        print_success("\nAdd to .env file:")
        print_success(f"CALENDAR_PATH={working_path}")
        print_success("\nOr use calendar token directly in bot:")
        print_success(f"CALENDAR_TOKEN={CALENDAR_TOKEN}")
    else:
        print_error("No working path found")
        print_info("\nTry:")
        print_info("1. Check if calendar exists at calendar.yandex.ru")
        print_info("2. Create a new calendar and set a color")
        print_info("3. Get new token with ALL permissions")


if __name__ == "__main__":
    asyncio.run(main())