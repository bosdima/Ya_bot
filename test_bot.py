#!/usr/bin/env python3
"""
MyUved Bot v6.00 - Telegram бот для уведомлений
с синхронизацией Яндекс Календаря через официальное API (yandex-calendar)
"""

import asyncio
import json
import os
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode
from io import BytesIO
from logging.handlers import RotatingFileHandler

import pytz
import aiohttp
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputFile
)
from aiogram.utils import executor
from dotenv import load_dotenv
from yandex_calendar import Calendar
from yandex_calendar.exceptions import YandexCalendarError

# ========== НАСТРОЙКИ ==========
log_file = 'bot_debug.log'
max_log_size = 100 * 1024  # 100 КБ

file_handler = RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=2, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)

# Версия
BOT_VERSION = "6.00"
BOT_VERSION_DATE = "11.04.2026"

# Загрузка .env
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'https://oauth.yandex.ru/verification_code')

if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET]):
    logger.error("Missing required environment variables!")
    exit(1)

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Файлы данных
DATA_FILE = 'notifications.json'
CONFIG_FILE = 'config.json'
CALENDAR_SYNC_FILE = 'calendar_sync.json'
TOKEN_FILE = 'yandex_token.json'

# Глобальные переменные
notifications: Dict = {}
config: Dict = {}
calendar_sync: Dict = {}
notifications_enabled = True

# Константы
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
YANDEX_OAUTH_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"

TIMEZONES = {
    'Москва (UTC+3)': 'Europe/Moscow',
    'Калининград (UTC+2)': 'Europe/Kaliningrad',
    'Екатеринбург (UTC+5)': 'Asia/Yekaterinburg',
    'Новосибирск (UTC+7)': 'Asia/Novosibirsk',
    'Владивосток (UTC+10)': 'Asia/Vladivostok',
}

WEEKDAYS_BUTTONS = [("Пн", 0), ("Вт", 1), ("Ср", 2), ("Чт", 3), ("Пт", 4), ("Сб", 5), ("Вс", 6)]
WEEKDAYS_NAMES = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_current_time():
    tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
    return datetime.now(tz)


def parse_date(date_str: str) -> Optional[datetime]:
    date_str = date_str.strip()
    now = get_current_time()
    current_year = now.year
    tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
    
    # ДД.ММ.ГГГГ ЧЧ:ММ
    match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s+(\d{1,2}):(\d{2})$', date_str)
    if match:
        day, month, year, hour, minute = match.groups()
        year = int(year)
        if year < 100:
            year = 2000 + year
        try:
            return tz.localize(datetime(year, int(month), int(day), int(hour), int(minute)))
        except:
            return None
    
    # ДД.ММ ЧЧ:ММ
    match = re.match(r'^(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})$', date_str)
    if match:
        day, month, hour, minute = match.groups()
        year = current_year
        try:
            result = tz.localize(datetime(year, int(month), int(day), int(hour), int(minute)))
            if result < now:
                result = tz.localize(datetime(year + 1, int(month), int(day), int(hour), int(minute)))
            return result
        except:
            return None
    
    # ДД.ММ
    match = re.match(r'^(\d{1,2})\.(\d{1,2})$', date_str)
    if match:
        day, month = match.groups()
        try:
            result = tz.localize(datetime(current_year, int(month), int(day), now.hour, now.minute))
            if result < now:
                result = tz.localize(datetime(current_year + 1, int(month), int(day), now.hour, now.minute))
            return result
        except:
            return None
    
    return None


def get_next_weekday(target_weekdays: List[int], hour: int, minute: int, from_date: datetime = None) -> Optional[datetime]:
    now = from_date or get_current_time()
    tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
    
    if now.weekday() in target_weekdays:
        today_trigger = tz.localize(datetime(now.year, now.month, now.day, hour, minute))
        if today_trigger > now:
            return today_trigger
    
    for i in range(1, 15):
        next_date = now + timedelta(days=i)
        if next_date.weekday() in target_weekdays:
            return tz.localize(datetime(next_date.year, next_date.month, next_date.day, hour, minute))
    
    return None


def load_token() -> Optional[str]:
    """Загружает токен Яндекса"""
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


def save_token(token: str):
    """Сохраняет токен"""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'access_token': token, 'created_at': datetime.now().isoformat()}, f)
    
    # Обновляем .env
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


# ========== YANDEX CALENDAR API (официальная библиотека) ==========

class YandexCalendarAPI:
    """Работа с Яндекс Календарём через официальную библиотеку"""
    
    def __init__(self, token: str):
        self.token = token
        try:
            self.calendar = Calendar(access_token=token)
            self.is_ready = True
        except Exception as e:
            logger.error(f"Calendar init error: {e}")
            self.is_ready = False
            self.calendar = None
    
    async def test_connection(self) -> tuple:
        """Проверка соединения"""
        if not self.is_ready:
            return False, "Calendar not initialized"
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.calendar.events_list(
                    calendar_id='primary',
                    params={'timeMin': datetime.now().isoformat() + 'Z', 'maxResults': 1}
                )
            )
            return True, "OK"
        except YandexCalendarError as e:
            if '401' in str(e):
                return False, "Token expired"
            elif '403' in str(e):
                return False, "No permissions"
            else:
                return False, str(e)[:100]
        except Exception as e:
            return False, str(e)[:100]
    
    async def get_calendars(self) -> List[Dict]:
        """Получение списка календарей"""
        if not self.is_ready:
            return []
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.calendar.calendars_list)
            return result.get('items', [])
        except Exception as e:
            logger.error(f"Get calendars error: {e}")
            return []
    
    async def create_event(self, summary: str, start_time: datetime, 
                           end_time: datetime = None, description: str = "") -> Optional[str]:
        """Создание события"""
        if not self.is_ready:
            return None
        
        try:
            if end_time is None:
                end_time = start_time + timedelta(hours=1)
            
            tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
            if start_time.tzinfo is None:
                start_time = tz.localize(start_time)
            if end_time.tzinfo is None:
                end_time = tz.localize(end_time)
            
            event_data = {
                'summary': summary[:255],
                'description': description[:1000],
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': config.get('timezone', 'Europe/Moscow')
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': config.get('timezone', 'Europe/Moscow')
                }
            }
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.calendar.events_insert(calendar_id='primary', event=event_data)
            )
            
            event_id = result.get('id')
            logger.info(f"Created calendar event: {summary} (ID: {event_id})")
            return event_id
            
        except Exception as e:
            logger.error(f"Create event error: {e}")
            return None
    
    async def delete_event(self, event_id: str) -> bool:
        """Удаление события"""
        if not self.is_ready:
            return False
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.calendar.events_delete(calendar_id='primary', event_id=event_id)
            )
            logger.info(f"Deleted calendar event: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Delete event error: {e}")
            return False


# ========== YANDEX DISK API ==========

class YandexDiskAPI:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"OAuth {token}"}
    
    async def check_access(self) -> tuple:
        try:
            url = f"{YANDEX_API_BASE}/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=10) as resp:
                    if resp.status == 200:
                        return True, "OK"
                    else:
                        return False, f"Status {resp.status}"
        except Exception as e:
            return False, str(e)


# ========== FSM СОСТОЯНИЯ ==========

class AuthStates(StatesGroup):
    waiting_for_code = State()


class NotificationStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_time_type = State()
    waiting_for_hours = State()
    waiting_for_days = State()
    waiting_for_specific_date = State()
    waiting_for_weekdays = State()
    waiting_for_weekday_time = State()
    waiting_for_every_day_time = State()


# ========== ФУНКЦИИ ДАННЫХ ==========

def init_files():
    Path('backups').mkdir(exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                'backup_path': '/MyUved_backups',
                'max_backups': 5,
                'timezone': 'Europe/Moscow',
                'calendar_sync_enabled': False
            }, f)
    if not os.path.exists(CALENDAR_SYNC_FILE):
        with open(CALENDAR_SYNC_FILE, 'w') as f:
            json.dump({}, f)


def load_data():
    global notifications, config, calendar_sync
    with open(DATA_FILE, 'r') as f:
        notifications = json.load(f)
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    if os.path.exists(CALENDAR_SYNC_FILE):
        with open(CALENDAR_SYNC_FILE, 'r') as f:
            calendar_sync = json.load(f)


def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(notifications, f, indent=2, ensure_ascii=False)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def save_calendar_sync():
    with open(CALENDAR_SYNC_FILE, 'w') as f:
        json.dump(calendar_sync, f, indent=2, ensure_ascii=False)


async def sync_to_calendar(notif_id: str, action: str = 'create'):
    """Синхронизация с календарём"""
    if not config.get('calendar_sync_enabled', False):
        return
    
    token = load_token()
    if not token:
        return
    
    notif = notifications.get(notif_id)
    if not notif:
        return
    
    api = YandexCalendarAPI(token)
    
    if action == 'create':
        event_time = datetime.fromisoformat(notif['time'])
        event_id = await api.create_event(
            summary=notif['text'][:100],
            start_time=event_time,
            description=f"Уведомление из бота MyUved\nТекст: {notif['text']}"
        )
        if event_id:
            calendar_sync[notif_id] = {'event_id': event_id}
            save_calendar_sync()
    
    elif action == 'delete':
        sync_data = calendar_sync.get(notif_id, {})
        if sync_data.get('event_id'):
            await api.delete_event(sync_data['event_id'])
            del calendar_sync[notif_id]
            save_calendar_sync()


# ========== КЛАВИАТУРА ==========

def get_main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("➕ Добавить"), KeyboardButton("📋 Список"))
    kb.add(KeyboardButton("⚙️ Настройки"))
    return kb


# ========== ОБРАБОТЧИКИ ==========

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    token = load_token()
    status = "✅ Авторизован" if token else "❌ Не авторизован"
    
    await message.reply(
        f"🤖 **MyUved Bot v{BOT_VERSION}**\n\n"
        f"📅 Календарь: {status}\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )


@dp.message_handler(lambda m: m.text == "⚙️ Настройки")
async def settings_menu(message: types.Message):
    cal_sync = "✅ Вкл" if config.get('calendar_sync_enabled') else "❌ Выкл"
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(f"📅 Синхр: {cal_sync}", callback_data="toggle_calendar"),
        InlineKeyboardButton("🔑 Авторизация", callback_data="auth_start")
    )
    kb.add(InlineKeyboardButton("🔍 Проверить календарь", callback_data="check_calendar"))
    kb.add(InlineKeyboardButton("ℹ️ Инфо", callback_data="info"))
    
    await message.reply("⚙️ **Настройки**", reply_markup=kb, parse_mode='Markdown')


@dp.callback_query_handler(lambda c: c.data == "auth_start")
async def auth_start(callback: types.CallbackQuery, state: FSMContext):
    scopes = ["calendar:read", "calendar:write", "cloud_api:disk.read", "cloud_api:disk.write", "cloud_api:disk.info"]
    auth_url = f"{YANDEX_OAUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={' '.join(scopes)}"
    
    await bot.send_message(
        callback.from_user.id,
        f"🔑 **Авторизация**\n\n"
        f"1. [Откройте ссылку]({auth_url})\n"
        f"2. Разрешите доступ\n"
        f"3. Скопируйте код из адресной строки\n"
        f"4. Отправьте код сюда\n\n"
        f"У вас 3 минуты.",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    await AuthStates.waiting_for_code.set()
    await callback.answer()


@dp.message_handler(state=AuthStates.waiting_for_code)
async def receive_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    
    # Обмен кода на токен
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    
    try:
        response = requests.post(OAUTH_TOKEN_URL, data=data, timeout=15)
        if response.status_code == 200:
            result = response.json()
            token = result.get('access_token')
            save_token(token)
            await message.reply("✅ **Авторизация успешна!**", parse_mode='Markdown')
        else:
            await message.reply(f"❌ **Ошибка авторизации**\n{response.text[:200]}", parse_mode='Markdown')
    except Exception as e:
        await message.reply(f"❌ **Ошибка:** {e}", parse_mode='Markdown')
    
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "check_calendar")
async def check_calendar(callback: types.CallbackQuery):
    token = load_token()
    if not token:
        await callback.answer("Сначала авторизуйтесь!", show_alert=True)
        return
    
    api = YandexCalendarAPI(token)
    
    if not api.is_ready:
        await callback.answer("Ошибка инициализации календаря", show_alert=True)
        return
    
    ok, msg = await api.test_connection()
    
    if ok:
        calendars = await api.get_calendars()
        if calendars:
            text = f"✅ **Найдено календарей: {len(calendars)}**\n"
            for cal in calendars[:5]:
                text += f"• {cal.get('summary', 'Без названия')}\n"
        else:
            text = "⚠️ Календари не найдены"
    else:
        text = f"❌ **Ошибка подключения**\n{msg}"
    
    await bot.send_message(callback.from_user.id, text, parse_mode='Markdown')
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "toggle_calendar")
async def toggle_calendar(callback: types.CallbackQuery):
    config['calendar_sync_enabled'] = not config.get('calendar_sync_enabled', False)
    save_data()
    status = "включена" if config['calendar_sync_enabled'] else "выключена"
    await callback.answer(f"Синхронизация {status}")
    await settings_menu(callback.message)


@dp.callback_query_handler(lambda c: c.data == "info")
async def show_info(callback: types.CallbackQuery):
    token = load_token()
    info = f"""
🤖 **MyUved Bot v{BOT_VERSION}**

📝 Уведомлений: {len(notifications)}
📅 Синхронизация: {'✅' if config.get('calendar_sync_enabled') else '❌'}
🔑 Авторизация: {'✅' if token else '❌'}
🕐 Время: {get_current_time().strftime('%d.%m.%Y %H:%M')}
"""
    await callback.message.reply(info, parse_mode='Markdown')
    await callback.answer()


@dp.message_handler(lambda m: m.text == "➕ Добавить")
async def add_notification_start(message: types.Message):
    await message.reply("✏️ **Введите текст уведомления:**", parse_mode='Markdown')
    await NotificationStates.waiting_for_text.set()


@dp.message_handler(state=NotificationStates.waiting_for_text)
async def get_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⏰ Часы", callback_data="time_hours"),
        InlineKeyboardButton("📅 Дни", callback_data="time_days"),
        InlineKeyboardButton("🗓️ Дата", callback_data="time_specific"),
        InlineKeyboardButton("🔄 Каждый день", callback_data="time_every_day"),
        InlineKeyboardButton("📆 Дни недели", callback_data="time_weekdays")
    )
    
    await message.reply("⏱️ **Когда уведомить?**", reply_markup=kb, parse_mode='Markdown')
    await NotificationStates.waiting_for_time_type.set()


@dp.callback_query_handler(lambda c: c.data.startswith('time_'), state=NotificationStates.waiting_for_time_type)
async def get_time_type(callback: types.CallbackQuery, state: FSMContext):
    time_type = callback.data.replace('time_', '')
    await state.update_data(time_type=time_type)
    
    if time_type == 'hours':
        await callback.message.reply("⌛ **Введите количество часов:**")
        await NotificationStates.waiting_for_hours.set()
    elif time_type == 'days':
        await callback.message.reply("📅 **Введите количество дней:**")
        await NotificationStates.waiting_for_days.set()
    elif time_type == 'specific':
        await callback.message.reply("🗓️ **Введите дату (ДД.ММ ЧЧ:ММ):**")
        await NotificationStates.waiting_for_specific_date.set()
    elif time_type == 'every_day':
        await callback.message.reply("⏰ **Введите время (ЧЧ:ММ):**")
        await NotificationStates.waiting_for_every_day_time.set()
    elif time_type == 'weekdays':
        kb = InlineKeyboardMarkup(row_width=3)
        for name, day in WEEKDAYS_BUTTONS:
            kb.insert(InlineKeyboardButton(name, callback_data=f"wd_{day}"))
        kb.add(InlineKeyboardButton("✅ Готово", callback_data="wd_done"))
        await state.update_data(selected_weekdays=[])
        await callback.message.reply("📅 **Выберите дни недели:**", reply_markup=kb)
        await NotificationStates.waiting_for_weekdays.set()
    
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith('wd_'), state=NotificationStates.waiting_for_weekdays)
async def select_weekday(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data.replace('wd_', ''))
    data = await state.get_data()
    selected = data.get('selected_weekdays', [])
    
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    
    await state.update_data(selected_weekdays=selected)
    
    kb = InlineKeyboardMarkup(row_width=3)
    for name, d in WEEKDAYS_BUTTONS:
        text = f"✅ {name}" if d in selected else name
        kb.insert(InlineKeyboardButton(text, callback_data=f"wd_{d}"))
    kb.add(InlineKeyboardButton("✅ Готово", callback_data="wd_done"))
    
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data == "wd_done", state=NotificationStates.waiting_for_weekdays)
async def weekdays_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get('selected_weekdays', [])
    
    if not selected:
        await callback.answer("Выберите хотя бы один день!", show_alert=True)
        return
    
    await state.update_data(weekdays_list=selected)
    await callback.message.reply("⏰ **Введите время (ЧЧ:ММ):**")
    await NotificationStates.waiting_for_weekday_time.set()
    await callback.answer()


async def save_notification(message: types.Message, state: FSMContext, notify_time: datetime):
    data = await state.get_data()
    notif_id = str(len(notifications) + 1)
    
    tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
    if notify_time.tzinfo is None:
        notify_time = tz.localize(notify_time)
    
    notifications[notif_id] = {
        'text': data['text'],
        'time': notify_time.isoformat(),
        'created': get_current_time().isoformat(),
        'notified': False,
        'repeat_type': 'no'
    }
    
    save_data()
    await sync_to_calendar(notif_id, 'create')
    
    await message.reply(
        f"✅ **Уведомление создано!**\n"
        f"📝 {data['text']}\n"
        f"⏰ {notify_time.strftime('%d.%m.%Y %H:%M')}",
        parse_mode='Markdown'
    )
    await state.finish()


@dp.message_handler(state=NotificationStates.waiting_for_hours)
async def set_hours(message: types.Message, state: FSMContext):
    try:
        hours = int(message.text)
        notify_time = get_current_time() + timedelta(hours=hours)
        await save_notification(message, state, notify_time)
    except:
        await message.reply("❌ Введите число!")


@dp.message_handler(state=NotificationStates.waiting_for_days)
async def set_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text)
        notify_time = get_current_time() + timedelta(days=days)
        await save_notification(message, state, notify_time)
    except:
        await message.reply("❌ Введите число!")


@dp.message_handler(state=NotificationStates.waiting_for_specific_date)
async def set_specific_date(message: types.Message, state: FSMContext):
    notify_time = parse_date(message.text)
    if notify_time:
        await save_notification(message, state, notify_time)
    else:
        await message.reply("❌ Неверный формат даты!")


@dp.message_handler(state=NotificationStates.waiting_for_every_day_time)
async def set_every_day(message: types.Message, state: FSMContext):
    match = re.match(r'^(\d{1,2}):(\d{2})$', message.text)
    if not match:
        await message.reply("❌ Формат: ЧЧ:ММ")
        return
    
    hour, minute = map(int, match.groups())
    data = await state.get_data()
    notif_id = str(len(notifications) + 1)
    
    now = get_current_time()
    tz = pytz.timezone(config.get('timezone', 'Europe/Moscow'))
    first_time = tz.localize(datetime(now.year, now.month, now.day, hour, minute))
    if first_time <= now:
        first_time += timedelta(days=1)
    
    notifications[notif_id] = {
        'text': data['text'],
        'time': first_time.isoformat(),
        'created': now.isoformat(),
        'notified': False,
        'repeat_type': 'every_day',
        'repeat_hour': hour,
        'repeat_minute': minute,
        'last_trigger': (first_time - timedelta(days=1)).isoformat()
    }
    
    save_data()
    await sync_to_calendar(notif_id, 'create')
    await message.reply(f"✅ **Ежедневное уведомление создано!**\n⏰ {hour:02d}:{minute:02d}", parse_mode='Markdown')
    await state.finish()


@dp.message_handler(state=NotificationStates.waiting_for_weekday_time)
async def set_weekday_time(message: types.Message, state: FSMContext):
    match = re.match(r'^(\d{1,2}):(\d{2})$', message.text)
    if not match:
        await message.reply("❌ Формат: ЧЧ:ММ")
        return
    
    hour, minute = map(int, match.groups())
    data = await state.get_data()
    weekdays = data.get('weekdays_list', [])
    notif_id = str(len(notifications) + 1)
    
    first_time = get_next_weekday(weekdays, hour, minute)
    
    notifications[notif_id] = {
        'text': data['text'],
        'time': first_time.isoformat(),
        'created': get_current_time().isoformat(),
        'notified': False,
        'repeat_type': 'weekdays',
        'repeat_hour': hour,
        'repeat_minute': minute,
        'weekdays_list': weekdays,
        'last_trigger': (first_time - timedelta(days=7)).isoformat()
    }
    
    save_data()
    await sync_to_calendar(notif_id, 'create')
    
    days_names = [WEEKDAYS_NAMES[d] for d in sorted(weekdays)]
    await message.reply(
        f"✅ **Уведомление создано!**\n"
        f"📆 {', '.join(days_names)} в {hour:02d}:{minute:02d}",
        parse_mode='Markdown'
    )
    await state.finish()


@dp.message_handler(lambda m: m.text == "📋 Список")
async def list_notifications(message: types.Message):
    if not notifications:
        await message.reply("📭 Нет уведомлений")
        return
    
    for notif_id, notif in notifications.items():
        if notif.get('repeat_type', 'no') != 'no':
            text = f"🔄 **{notif['text']}**\n"
            if notif.get('repeat_type') == 'every_day':
                text += f"⏰ Каждый день в {notif['repeat_hour']:02d}:{notif['repeat_minute']:02d}"
            elif notif.get('repeat_type') == 'weekdays':
                days = [WEEKDAYS_NAMES[d] for d in notif.get('weekdays_list', [])]
                text += f"📆 {', '.join(days)} в {notif['repeat_hour']:02d}:{notif['repeat_minute']:02d}"
        else:
            notify_time = datetime.fromisoformat(notif['time'])
            text = f"⏳ **{notif['text']}**\n⏰ {notify_time.strftime('%d.%m.%Y %H:%M')}"
        
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"del_{notif_id}")
        )
        await message.reply(text, reply_markup=kb, parse_mode='Markdown')


@dp.callback_query_handler(lambda c: c.data.startswith('del_'))
async def delete_notification(callback: types.CallbackQuery):
    notif_id = callback.data.replace('del_', '')
    if notif_id in notifications:
        await sync_to_calendar(notif_id, 'delete')
        del notifications[notif_id]
        save_data()
        await callback.message.edit_text("✅ Удалено")
    await callback.answer()


async def check_notifications_task():
    """Фоновая проверка уведомлений"""
    while True:
        now = get_current_time()
        
        for notif_id, notif in list(notifications.items()):
            repeat_type = notif.get('repeat_type', 'no')
            
            if repeat_type == 'no':
                notify_time = datetime.fromisoformat(notif['time'])
                if now >= notify_time and not notif.get('notified'):
                    await bot.send_message(ADMIN_ID, f"🔔 **НАПОМИНАНИЕ**\n\n📝 {notif['text']}")
                    notifications[notif_id]['notified'] = True
                    save_data()
            
            elif repeat_type == 'every_day':
                hour = notif['repeat_hour']
                minute = notif['repeat_minute']
                last_trigger = datetime.fromisoformat(notif.get('last_trigger', '2000-01-01T00:00:00'))
                
                if now.hour == hour and now.minute == minute and last_trigger.date() < now.date():
                    await bot.send_message(ADMIN_ID, f"🔔 **ЕЖЕДНЕВНОЕ НАПОМИНАНИЕ**\n\n📝 {notif['text']}")
                    notifications[notif_id]['last_trigger'] = now.isoformat()
                    save_data()
            
            elif repeat_type == 'weekdays':
                hour = notif['repeat_hour']
                minute = notif['repeat_minute']
                weekdays = notif.get('weekdays_list', [])
                last_trigger = datetime.fromisoformat(notif.get('last_trigger', '2000-01-01T00:00:00'))
                
                if (now.weekday() in weekdays and now.hour == hour and now.minute == minute 
                    and last_trigger.date() < now.date()):
                    await bot.send_message(ADMIN_ID, f"🔔 **НАПОМИНАНИЕ ПО ДНЯМ**\n\n📝 {notif['text']}")
                    notifications[notif_id]['last_trigger'] = now.isoformat()
                    save_data()
        
        await asyncio.sleep(30)


async def on_startup(dp):
    init_files()
    load_data()
    
    logger.info(f"MyUved Bot v{BOT_VERSION} started")
    logger.info(f"Admin ID: {ADMIN_ID}")
    
    token = load_token()
    if token:
        logger.info("Yandex token loaded")
        api = YandexCalendarAPI(token)
        if api.is_ready:
            ok, msg = await api.test_connection()
            if ok:
                logger.info("Calendar API connection: OK")
            else:
                logger.warning(f"Calendar API connection: {msg}")
    else:
        logger.warning("No Yandex token")
    
    asyncio.create_task(check_notifications_task())


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)