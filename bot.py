import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import requests
from requests_oauthlib import OAuth2Session

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище токенов (в реальном приложении используйте БД)
user_tokens = {}

# OAuth2 для Яндекс
AUTHORIZATION_BASE_URL = 'https://oauth.yandex.ru/authorize'
TOKEN_URL = 'https://oauth.yandex.ru/token'
CALENDAR_API_URL = 'https://api.calendar.yandex.net/v1'

def get_yandex_oauth(user_id):
    """Создаёт OAuth2‑сессию для пользователя."""
    token = user_tokens.get(user_id)
    if token:
        return OAuth2Session(CLIENT_ID, token=token)
    else:
        return OAuth2Session(
            CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            scope=['calendar:write', 'calendar:read']
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📅 Добавить событие", callback_data="add_event")],
        [InlineKeyboardButton("👀 Просмотреть события", callback_data="view_events")],
        [InlineKeyboardButton("✏️ Редактировать событие", callback_data="edit_event")],
        [InlineKeyboardButton("🗑️ Удалить событие", callback_data="delete_event")],
        [InlineKeyboardButton("🔗 Привязать Яндекс Календарь", callback_data="auth_yandex")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Привет, {user.first_name}! Я бот для работы с Яндекс Календарём.\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def auth_yandex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс аутентификации с Яндекс."""
    query = update.callback_query
    await query.answer()
    
    yandex = get_yandex_oauth(query.from_user.id)
    authorization_url, state = yandex.authorization_url(AUTHORIZATION_BASE_URL)
    
    keyboard = [[InlineKeyboardButton("Авторизоваться", url=authorization_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "Для работы с Яндекс Календарём нужно авторизоваться:",
        reply_markup=reply_markup
    )

async def handle_oauth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает callback от Яндекс OAuth."""
    # В реальном приложении здесь должен быть веб‑сервер для приёма callback
    # Этот пример упрощён — в реальности нужно настроить вебхук
    await update.message.reply_text("Авторизация завершена! Теперь вы можете работать с календарём.")

async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавляет событие в Яндекс Календарь."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    yandex = get_yandex_oauth(user_id)
    
    if not user_tokens.get(user_id):
        await query.edit_message_text("Сначала привяжите Яндекс Календарь /start")
        return
    
    # Запрос данных у пользователя
    context.user_data['awaiting_event_data'] = True
    await query.edit_message_text(
        "Введите данные события в формате:\n"
        "Название, Дата (ГГГГ-ММ-ДД), Время (ЧЧ:ММ), Описание"
    )

async def handle_event_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод данных события."""
    if context.user_data.get('awaiting_event_data'):
        try:
            # Парсинг ввода
            parts = update.message.text.split(',')
            if len(parts) < 3:
                await update.message.reply_text("Неверный формат. Попробуйте снова.")
                return
            
            title = parts[0].strip()
            date_str = parts[1].strip()
            time_str = parts[2].strip()
            description = parts[3].strip() if len(parts) > 3 else ""
            
            # Формирование даты и времени
            event_datetime = f"{date_str}T{time_str}:00+03:00"  # UTC+3
            
            # Создание события через API Яндекс Календаря
            yandex = get_yandex_oauth(update.effective_user.id)
            event_data = {
                "summary": title,
                "description": description,
                "start": {"dateTime": event_datetime},
                "end": {"dateTime": (datetime.fromisoformat(event_datetime.replace('+03:00', '')) + timedelta(hours=1)).isoformat() + '+03:00'}
            }
            
            response = yandex.post(
                f"{CALENDAR_API_URL}/calendars/primary/events",
                json=event_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 201:
                await update.message.reply_text("Событие успешно добавлено!")
            else:
                await update.message.reply_text(f"Ошибка при добавлении: {response.status_code}")
                
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}")
        
        context.user_data['awaiting_event_data'] = False

async def view_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает события из Яндекс Календаря."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    yandex = get_yandex_oauth(user_id)
    
    if not user_tokens.get(user_id):
        await query.edit_message_text("Сначала привяжите Яндекс Календарь /start")
        return
    
    # Получение событий на ближайшие 7 дней
    now = datetime.utcnow().isoformat() + 'Z'
    week_later = (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z'
    
    response = yandex.get(
        f"{CALENDAR_API_URL}/calendars/primary/events",
        params={
            'timeMin': now,
            'timeMax': week_later,
            'singleEvents': 'true',
            'orderBy': 'startTime'
        }
    )
    
    if response.status_code == 200:
        events = response.json().get('items', [])
        if not events:
            message = "На ближайшие 7 дней событий