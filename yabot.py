import os
import logging
import json
import requests
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from urllib.parse import urlencode

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI')

# Хранилище токенов пользователей (в production используйте базу данных)
user_tokens = {}  # {user_id: yandex_access_token}

class YandexDiskAPI:
    """Класс для работы с API Яндекс.Диска"""
    
    BASE_URL = "https://cloud-api.yandex.net/v1/disk"
    OAUTH_URL = "https://oauth.yandex.ru/authorize"
    TOKEN_URL = "https://oauth.yandex.ru/token"
    
    def __init__(self, access_token: str = None):
        self.access_token = access_token
        self.headers = {}
        if access_token:
            self.headers = {"Authorization": f"OAuth {access_token}"}
    
    def get_auth_url(self) -> str:
        """Получение URL для авторизации"""
        params = {
            "response_type": "code",
            "client_id": YANDEX_CLIENT_ID,
            "redirect_uri": YANDEX_REDIRECT_URI
        }
        return f"{self.OAUTH_URL}?{urlencode(params)}"
    
    def get_token_by_code(self, code: str) -> Optional[str]:
        """Получение токена доступа по коду авторизации"""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": YANDEX_CLIENT_ID,
            "client_secret": YANDEX_CLIENT_SECRET,
            "redirect_uri": YANDEX_REDIRECT_URI
        }
        
        try:
            response = requests.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            token_data = response.json()
            return token_data.get("access_token")
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return None
    
    def get_files_list(self, path: str = "/", limit: int = 50) -> Optional[Dict]:
        """Получение списка файлов и папок"""
        if not self.access_token:
            return None
            
        url = f"{self.BASE_URL}/resources"
        params = {
            "path": path,
            "limit": limit,
            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.path,_embedded.items.size,_embedded.items.modified,_embedded.items.mime_type"
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting files list: {e}")
            return None
    
    def download_file(self, path: str) -> Optional[str]:
        """Получение ссылки для скачивания файла"""
        if not self.access_token:
            return None
            
        url = f"{self.BASE_URL}/resources/download"
        params = {"path": path}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json().get("href")
        except Exception as e:
            logger.error(f"Error getting download link: {e}")
            return None

def format_size(size: int) -> str:
    """Форматирование размера файла в человекочитаемый вид"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def format_file_info(item: Dict) -> str:
    """Форматирование информации о файле/папке"""
    name = item.get('name', 'Unknown')
    item_type = item.get('type', 'file')
    
    if item_type == 'dir':
        return f"📁 {name}"
    else:
        size = item.get('size', 0)
        modified = item.get('modified', '')
        if modified:
            modified_date = datetime.fromisoformat(modified.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
            return f"📄 {name}\n   📦 {format_size(size)} | 📅 {modified_date}"
        return f"📄 {name}\n   📦 {format_size(size)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    welcome_text = f"""
Привет, {user.first_name}! 👋

Я бот для работы с Яндекс.Диском. Вот что я умею:

🔐 /auth - Авторизоваться в Яндекс.Диске
📁 /list - Показать содержимое текущей папки
📂 /cd <папка> - Перейти в папку
⬆️ /up - Подняться на уровень выше
📥 /download <файл> - Скачать файл
ℹ️ /info - Информация о текущей папке
❓ /help - Помощь

Для начала работы необходимо авторизоваться через /auth
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
📚 Доступные команды:

/auth - Авторизация в Яндекс.Диске
/list - Показать содержимое текущей папки
/cd <название папки> - Перейти в указанную папку
/up - Вернуться в родительскую папку
/download <название файла> - Скачать файл
/info - Показать информацию о текущей папке
/help - Показать эту справку

💡 Примеры:
/cd Documents - перейти в папку Documents
/download photo.jpg - скачать файл photo.jpg
    """
    await update.message.reply_text(help_text)

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /auth"""
    user_id = update.effective_user.id
    
    # Проверяем, есть ли уже токен
    if user_id in user_tokens:
        await update.message.reply_text("✅ Вы уже авторизованы!")
        return
    
    # Создаем URL для авторизации
    yandex_api = YandexDiskAPI()
    auth_url = yandex_api.get_auth_url()
    
    # Отправляем сообщение с инструкцией
    message = f"""
🔐 Для авторизации перейдите по ссылке:
{auth_url}

После подтверждения вы получите код. 
Отправьте его в ответ на это сообщение.

Код выглядит примерно так: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    """
    
    await update.message.reply_text(message)
    # Сохраняем состояние ожидания кода
    context.user_data['waiting_for_auth_code'] = True

async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кода авторизации"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    # Проверяем, ожидаем ли мы код
    if not context.user_data.get('waiting_for_auth_code'):
        return
    
    # Получаем токен по коду
    yandex_api = YandexDiskAPI()
    token = yandex_api.get_token_by_code(code)
    
    if token:
        user_tokens[user_id] = token
        context.user_data['waiting_for_auth_code'] = False
        context.user_data['current_path'] = '/'  # Устанавливаем текущий путь
        
        await update.message.reply_text("✅ Авторизация успешна! Теперь вы можете использовать бота.")
        logger.info(f"User {user_id} successfully authenticated")
    else:
        await update.message.reply_text("❌ Ошибка авторизации. Попробуйте еще раз /auth")

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /list"""
    user_id = update.effective_user.id
    
    # Проверяем авторизацию
    if user_id not in user_tokens:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    # Получаем текущий путь
    current_path = context.user_data.get('current_path', '/')
    
    # Создаем API клиент
    yandex_api = YandexDiskAPI(user_tokens[user_id])
    
    # Получаем список файлов
    result = yandex_api.get_files_list(current_path)
    
    if not result or '_embedded' not in result:
        await update.message.reply_text("❌ Не удалось получить список файлов")
        return
    
    items = result['_embedded'].get('items', [])
    
    if not items:
        await update.message.reply_text(f"📂 Папка пуста: {current_path}")
        return
    
    # Форматируем вывод
    message = f"📁 **Текущая папка:** `{current_path}`\n\n"
    
    # Создаем кнопки для навигации
    keyboard = []
    
    for item in items:
        item_type = item.get('type', 'file')
        name = item.get('name', 'Unknown')
        
        if item_type == 'dir':
            keyboard.append([
                InlineKeyboardButton(f"📁 {name}", callback_data=f"open_{name}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(f"📄 {name}", callback_data=f"download_{name}")
            ])
    
    # Добавляем кнопки навигации
    nav_buttons = []
    if current_path != '/':
        nav_buttons.append(InlineKeyboardButton("⬆️ Вверх", callback_data="up"))
    nav_buttons.append(InlineKeyboardButton("🔄 Обновить", callback_data="refresh"))
    
    keyboard.append(nav_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Если сообщение длинное, отправляем с клавиатурой
    if len(items) > 20:
        await update.message.reply_text(f"📁 Найдено {len(items)} элементов. Используйте кнопки ниже:")
        await update.message.reply_text(message[:4000], parse_mode='Markdown', reply_markup=reply_markup)
    else:
        for item in items[:20]:  # Показываем первые 20 элементов
            file_info = format_file_info(item)
            await update.message.reply_text(file_info, parse_mode='Markdown')
        
        if len(items) > 20:
            await update.message.reply_text(f"... и еще {len(items) - 20} элементов")
        
        await update.message.reply_text("Используйте кнопки для навигации:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if user_id not in user_tokens:
        await query.edit_message_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    current_path = context.user_data.get('current_path', '/')
    
    if data == "refresh":
        await query.edit_message_text("🔄 Обновление...")
        await list_files(update, context)
        
    elif data == "up":
        # Поднимаемся на уровень выше
        if current_path != '/':
            parent_path = '/'.join(current_path.rstrip('/').split('/')[:-1])
            if not parent_path:
                parent_path = '/'
            context.user_data['current_path'] = parent_path
            await query.edit_message_text(f"⬆️ Переход в {parent_path}")
            await list_files(update, context)
    
    elif data.startswith("open_"):
        folder_name = data[5:]  # Убираем "open_"
        new_path = f"{current_path.rstrip('/')}/{folder_name}"
        context.user_data['current_path'] = new_path
        await query.edit_message_text(f"📂 Открыта папка: {new_path}")
        await list_files(update, context)
    
    elif data.startswith("download_"):
        file_name = data[9:]  # Убираем "download_"
        await download_file_command(update, context, file_name)

async def change_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /cd"""
    user_id = update.effective_user.id
    
    if user_id not in user_tokens:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    # Получаем имя папки из аргументов
    args = context.args
    if not args:
        await update.message.reply_text("ℹ️ Укажите название папки. Пример: /cd Documents")
        return
    
    folder_name = ' '.join(args)
    current_path = context.user_data.get('current_path', '/')
    new_path = f"{current_path.rstrip('/')}/{folder_name}"
    
    # Проверяем существование папки
    yandex_api = YandexDiskAPI(user_tokens[user_id])
    result = yandex_api.get_files_list(new_path)
    
    if result and '_embedded' in result:
        context.user_data['current_path'] = new_path
        await update.message.reply_text(f"✅ Переход в: {new_path}")
    else:
        await update.message.reply_text(f"❌ Папка '{folder_name}' не найдена")

async def up_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /up"""
    user_id = update.effective_user.id
    
    if user_id not in user_tokens:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    current_path = context.user_data.get('current_path', '/')
    
    if current_path != '/':
        parent_path = '/'.join(current_path.rstrip('/').split('/')[:-1])
        if not parent_path:
            parent_path = '/'
        context.user_data['current_path'] = parent_path
        await update.message.reply_text(f"⬆️ Переход в: {parent_path}")
    else:
        await update.message.reply_text("📍 Вы уже в корневой папке")

async def download_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE, file_name: str = None):
    """Обработчик команды /download"""
    user_id = update.effective_user.id
    
    if user_id not in user_tokens:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    # Если file_name не передан, берем из аргументов
    if not file_name:
        args = context.args
        if not args:
            await update.message.reply_text("ℹ️ Укажите название файла. Пример: /download photo.jpg")
            return
        file_name = ' '.join(args)
    
    current_path = context.user_data.get('current_path', '/')
    file_path = f"{current_path.rstrip('/')}/{file_name}"
    
    # Отправляем сообщение о начале загрузки
    status_message = await update.message.reply_text(f"⏬ Загрузка файла {file_name}...")
    
    try:
        yandex_api = YandexDiskAPI(user_tokens[user_id])
        download_url = yandex_api.download_file(file_path)
        
        if download_url:
            # Скачиваем файл
            response = requests.get(download_url, stream=True)
            response.raise_for_status()
            
            # Получаем информацию о файле
            file_info = yandex_api.get_files_list(file_path)
            
            # Отправляем файл в Telegram
            await status_message.delete()
            await update.message.reply_document(
                document=response.raw,
                filename=file_name,
                caption=f"✅ Файл '{file_name}' успешно загружен"
            )
        else:
            await status_message.edit_text(f"❌ Не удалось найти файл '{file_name}'")
            
    except Exception as e:
        await status_message.edit_text(f"❌ Ошибка при загрузке: {str(e)}")
        logger.error(f"Download error: {e}")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /info"""
    user_id = update.effective_user.id
    
    if user_id not in user_tokens:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return
    
    current_path = context.user_data.get('current_path', '/')
    yandex_api = YandexDiskAPI(user_tokens[user_id])
    
    result = yandex_api.get_files_list(current_path)
    
    if result:
        total_items = len(result.get('_embedded', {}).get('items', []))
        info_text = f"""
📊 **Информация о текущей папке:**

📍 **Путь:** `{current_path}`
📁 **Всего элементов:** {total_items}

Используйте /list для просмотра содержимого
        """
        await update.message.reply_text(info_text, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Не удалось получить информацию о папке")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений"""
    # Проверяем, ожидаем ли мы код авторизации
    if context.user_data.get('waiting_for_auth_code'):
        await handle_auth_code(update, context)
    else:
        await update.message.reply_text(
            "❓ Неизвестная команда. Используйте /help для списка команд"
        )

def main():
    """Запуск бота"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле")
        return
    
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("list", list_files))
    application.add_handler(CommandHandler("cd", change_directory))
    application.add_handler(CommandHandler("up", up_directory))
    application.add_handler(CommandHandler("download", download_file_command))
    application.add_handler(CommandHandler("info", info))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()