import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

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

class YandexCalendarAPI:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.calendar.yandex.net/v1"

    def _make_request(self, method, endpoint, **kwargs):
        headers = {
            'Authorization': f'OAuth {self.access_token}',
            'Content-Type': 'application/json'
        }
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=headers, **kwargs)
        return response.json() if response.status_code == 200 else None

    def get_events(self, start_date=None, end_date=None):
        params = {}
        if start_date:
            params['start'] = start_date
        if end_date:
            params['end'] = end_date
        return self._make_request('GET', '/events', params=params)

    def create_event(self, summary, start_time, end_time, description=None):
        data = {
            'summary': summary,
            'start': {'dateTime': start_time},
            'end': {'dateTime': end_time}
        }
        if description:
            data['description'] = description
        return self._make_request('POST', '/events', json=data)

    def update_event(self, event_id, summary=None, start_time=None, end_time=None, description=None):
        data = {}
        if summary:
            data['summary'] = summary
        if start_time:
            data['start'] = {'dateTime': start_time}
        if end_time:
            data['end'] = {'dateTime': end_time}
        if description:
            data['description'] = description
        return self._make_request('PATCH', f'/events/{event_id}', json=data)

    def delete_event(self, event_id):
        return self._make_request('DELETE', f'/events/{event_id}')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("У вас нет доступа к этому боту.")
        return

    keyboard = [
        [InlineKeyboardButton("Добавить заметку", callback_data="add_event")],
        [InlineKeyboardButton("Просмотреть заметки", callback_data="view_events")],
        [InlineKeyboardButton("Редактировать заметку", callback_data="edit_event")],
        [InlineKeyboardButton("Удалить заметку", callback_data="delete_event")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("У вас нет доступа.")
        return

    data = query.data
    if data == "add_event":
        context.user_data['state'] = 'awaiting_summary'
        await query.edit_message_text(
            "Введите заголовок заметки:"
        )
    elif data == "view_events":
        await show_events(query, context)
    elif data == "edit_event":
        context.user_data['state'] = 'awaiting_edit_id'
        await query.edit_message_text(
            "Введите ID заметки для редактирования:"
        )
    elif data == "delete_event":
        context.user_data['state'] = 'awaiting_delete_id'
        await query.edit_message_text(
            "Введите ID заметки для удаления:"
        )

async def show_events(query, context):
    # Здесь должен быть код для получения событий из календаря
    # Для примера показываем заглушку
    events = [
        {"id": "1", "summary": "Встреча с командой", "start": "2024-01-15T10:00:00"},
        {"id": "2", "summary": "Планерка", "start": "2024-01-16T14:00:00"}
    ]

    if not events:
        await query.edit_message_text("Заметок не найдено.")
        return

    message = "Ваши заметки:\n\n"
    for event in events:
        message += f"ID: {event['id']}\n"
        message += f"Заголовок: {event['summary']}\n"
        message += f"Дата: {event['start']}\n\n"

    await query.edit_message_text(message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    state = context.user_data.get('state')
    text = update.message.text

    if state == 'awaiting_summary':
        context.user_data['event_summary'] = text
        context.user_data['state'] = 'awaiting_start_time'
        await update.message.reply_text(
            "Введите дату и время начала (формат: ГГГГ-ММ-ДД ЧЧ:ММ):"
        )
    elif state == 'awaiting_start_time':
        try:
            start_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            context.user_data['event_start'] = start_time.isoformat()
            context.user_data['state'] = 'awaiting_end_time'
            await update.message.reply_text(
                "Введите дату и время окончания (формат: ГГГГ-ММ-ДД ЧЧ:ММ):"
            )
        except ValueError:
            await update.message.reply_text(
                "Неверный формат даты. Попробуйте снова:"
            )
    elif state == 'awaiting_end_time':
        try:
            end_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            summary = context.user_data['event_summary']
            start_time = context.user_data['event_start']

            # Здесь должен быть код для создания события в календаре
            # Для