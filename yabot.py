import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv
import yadisk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI')
YANDEX_TARGET_PATH = os.getenv('YANDEX_TARGET_PATH')

# Хранилище токенов пользователей (в реальном приложении используйте БД)
user_tokens: Dict[int, str] = {}

class YandexDiskClient:
    """Клиент для работы с Яндекс.Диском"""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.y = None
        self._init_client()
    
    def _init_client(self):
        """Инициализация клиента Яндекс.Диска"""
        if self.user_id in user_tokens:
            self.y = yadisk.YaDisk(
                id=YANDEX_CLIENT_ID,
                secret=YANDEX_CLIENT_SECRET,
                token=user_tokens[self.user_id]
            )
    
    def is_authenticated(self) -> bool:
        """Проверка аутентификации"""
        return self.y is not None and self.y.check_token()
    
    def get_auth_url(self) -> str:
        """Получение URL для авторизации"""
        return yadisk.YaDisk.get_code_url(
            client_id=YANDEX_CLIENT_ID,
            redirect_uri=YANDEX_REDIRECT_URI
        )
    
    def set_token(self, code: str) -> bool:
        """Установка токена по коду авторизации"""
        try:
            # Получение токена по коду
            response = yadisk.YaDisk.get_token(
                client_id=YANDEX_CLIENT_ID,
                client_secret=YANDEX_CLIENT_SECRET,
                code=code,
                redirect_uri=YANDEX_REDIRECT_URI
            )
            token = response.get('access_token')
            if token:
                user_tokens[self.user_id] = token
                self._init_client()
                return True
            return False
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return False
    
    def list_files_and_folders(self, path: str = None) -> Tuple[list, str]:
        """Получение списка файлов и папок"""
        if not self.is_authenticated():
            return [], "Не авторизован"
        
        target_path = path or YANDEX_TARGET_PATH
        try:
            items = []
            # Получаем содержимое папки
            for item in self.y.listdir(target_path):
                item_type = "📁" if item.type == 'dir' else "📄"
                items.append({
                    'name': item.name,
                    'path': item.path,
                    'type': 'dir' if item.type == 'dir' else 'file',
                    'size': item.size if hasattr(item, 'size') else None,
                    'display': f"{item_type} {item.name}"
                })
            return items, ""
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return [], f"Ошибка при получении списка: {str(e)}"
    
    async def download_file(self, file_path: str, file_name: str) -> Optional[bytes]:
        """Скачивание файла"""
        if not self.is_authenticated():
            return None
        
        try:
            # Получаем ссылку для скачивания
            download_url = self.y.get_download_link(file_path)
            
            # Скачиваем файл
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Error downloading file: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error downloading file {file_path}: {e}")
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🔐 Авторизоваться в Яндекс.Диске", callback_data="auth")],
        [InlineKeyboardButton("📂 Показать файлы и папки", callback_data="list_files")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 *Бот для работы с Яндекс.Диском*\n\n"
        "Я помогу вам просматривать и скачивать файлы из указанной папки на Яндекс.Диске.\n\n"
        f"📁 *Целевая папка:* `{YANDEX_TARGET_PATH}`\n\n"
        "Для начала работы необходимо авторизоваться.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "auth":
        await auth_yandex(update, context)
    
    elif data == "list_files":
        await list_files(update, context)
    
    elif data == "help":
        await help_command(update, context)
    
    elif data.startswith("download_"):
        await download_file(update, context)
    
    elif data.startswith("folder_"):
        await navigate_folder(update, context)

async def auth_yandex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Авторизация в Яндекс.Диске"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    yandex_client = YandexDiskClient(user_id)
    auth_url = yandex_client.get_auth_url()
    
    message = (
        "🔐 *Авторизация в Яндекс.Диске*\n\n"
        "1. Перейдите по ссылке ниже\n"
        "2. Войдите в свой аккаунт Яндекс\n"
        "3. Разрешите доступ приложению\n"
        "4. Скопируйте полученный код\n"
        f"5. Отправьте код в этот чат\n\n"
        f"[Ссылка для авторизации]({auth_url})"
    )
    
    await query.edit_message_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )
    
    # Сохраняем состояние ожидания кода
    context.user_data['awaiting_auth_code'] = True

async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кода авторизации"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    if context.user_data.get('awaiting_auth_code'):
        yandex_client = YandexDiskClient(user_id)
        
        if yandex_client.set_token(code):
            await update.message.reply_text(
                "✅ *Авторизация успешна!*\n\n"
                "Теперь вы можете просматривать файлы и папки.",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['awaiting_auth_code'] = False
            
            # Показываем список файлов
            await list_files_after_auth(update, context)
        else:
            await update.message.reply_text(
                "❌ *Ошибка авторизации*\n\n"
                "Неверный код. Попробуйте снова с помощью /start",
                parse_mode=ParseMode.MARKDOWN
            )

async def list_files_after_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка файлов после авторизации"""
    user_id = update.effective_user.id
    yandex_client = YandexDiskClient(user_id)
    
    if not yandex_client.is_authenticated():
        await update.message.reply_text("❌ Необходимо авторизоваться")
        return
    
    items, error = yandex_client.list_files_and_folders()
    
    if error:
        await update.message.reply_text(f"❌ {error}")
        return
    
    if not items:
        await update.message.reply_text("📂 Папка пуста")
        return
    
    # Создаем клавиатуру с файлами и папками
    keyboard = []
    for item in items:
        callback_data = f"folder_{item['path']}" if item['type'] == 'dir' else f"download_{item['path']}"
        keyboard.append([InlineKeyboardButton(item['display'], callback_data=callback_data)])
    
    # Добавляем кнопку "Наверх"
    keyboard.append([InlineKeyboardButton("⬆️ Наверх", callback_data="list_files")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📂 *Содержимое папки:*\n`{YANDEX_TARGET_PATH}`\n\n"
        "Нажмите на папку для входа или на файл для скачивания:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка файлов и папок"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    yandex_client = YandexDiskClient(user_id)
    
    if not yandex_client.is_authenticated():
        await query.edit_message_text(
            "❌ *Необходимо авторизоваться*\n\n"
            "Используйте кнопку авторизации в главном меню",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    items, error = yandex_client.list_files_and_folders()
    
    if error:
        await query.edit_message_text(f"❌ {error}")
        return
    
    if not items:
        await query.edit_message_text("📂 Папка пуста")
        return
    
    # Создаем клавиатуру с файлами и папками
    keyboard = []
    for item in items:
        callback_data = f"folder_{item['path']}" if item['type'] == 'dir' else f"download_{item['path']}"
        keyboard.append([InlineKeyboardButton(item['display'], callback_data=callback_data)])
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📂 *Содержимое папки:*\n`{YANDEX_TARGET_PATH}`\n\n"
        "Нажмите на папку для входа или на файл для скачивания:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def navigate_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по папкам"""
    query = update.callback_query
    user_id = update.effective_user.id
    folder_path = query.data.replace("folder_", "")
    
    yandex_client = YandexDiskClient(user_id)
    
    if not yandex_client.is_authenticated():
        await query.edit_message_text("❌ Необходимо авторизоваться")
        return
    
    items, error = yandex_client.list_files_and_folders(folder_path)
    
    if error:
        await query.edit_message_text(f"❌ {error}")
        return
    
    if not items:
        await query.edit_message_text("📂 Папка пуста")
        return
    
    # Создаем клавиатуру с файлами и папками
    keyboard = []
    for item in items:
        callback_data = f"folder_{item['path']}" if item['type'] == 'dir' else f"download_{item['path']}"
        keyboard.append([InlineKeyboardButton(item['display'], callback_data=callback_data)])
    
    # Добавляем кнопки навигации
    keyboard.append([InlineKeyboardButton("⬆️ На уровень выше", callback_data="list_files")])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📂 *Содержимое папки:*\n`{folder_path}`\n\n"
        "Нажмите на папку для входа или на файл для скачивания:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скачивание и отправка файла"""
    query = update.callback_query
    user_id = update.effective_user.id
    file_path = query.data.replace("download_", "")
    
    await query.edit_message_text("⏳ Скачиваю файл...")
    
    yandex_client = YandexDiskClient(user_id)
    
    if not yandex_client.is_authenticated():
        await query.edit_message_text("❌ Необходимо авторизоваться")
        return
    
    # Получаем имя файла из пути
    file_name = file_path.split('/')[-1]
    
    # Скачиваем файл
    file_data = await yandex_client.download_file(file_path, file_name)
    
    if file_data:
        try:
            # Отправляем файл
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_data,
                filename=file_name,
                caption=f"✅ Файл *{file_name}* успешно загружен!",
                parse_mode=ParseMode.MARKDOWN
            )
            await query.edit_message_text("✅ Файл отправлен!")
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            await query.edit_message_text(f"❌ Ошибка при отправке файла: {str(e)}")
    else:
        await query.edit_message_text("❌ Ошибка при скачивании файла")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    query = update.callback_query
    
    help_text = (
        "📚 *Помощь по боту*\n\n"
        "*Возможности:*\n"
        "• Просмотр файлов и папок на Яндекс.Диске\n"
        "• Навигация по папкам\n"
        "• Скачивание файлов в Telegram\n\n"
        "*Как использовать:*\n"
        "1. Авторизуйтесь через кнопку\n"
        "2. Получите код подтверждения\n"
        "3. Отправьте код в чат\n"
        "4. Просматривайте и скачивайте файлы\n\n"
        "*Команды:*\n"
        "/start - Главное меню\n"
        "/help - Эта справка"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("🔐 Авторизоваться в Яндекс.Диске", callback_data="auth")],
        [InlineKeyboardButton("📂 Показать файлы и папки", callback_data="list_files")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🤖 *Главное меню*\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in .env file")
        return
    
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern="^(auth|list_files|help|download_|folder_|back_to_menu)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code))
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()