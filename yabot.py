import os
import logging
import asyncio
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv
import yadisk
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration from .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
YANDEX_FOLDER_PATH = os.getenv('YANDEX_FOLDER_PATH')

# Global variable to store user tokens
user_tokens: Dict[int, str] = {}

class YandexDiskClient:
    """Wrapper for Yandex.Disk API operations"""
    
    def __init__(self, access_token: str = None):
        self.y = yadisk.YaDisk(token=access_token) if access_token else None
    
    def is_authenticated(self) -> bool:
        return self.y is not None and self.y.check_token()
    
    def get_auth_url(self) -> str:
        """Generate OAuth authorization URL"""
        auth_url = yadisk.YaDisk.get_code_url(
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI
        )
        return auth_url
    
    def get_token_from_code(self, code: str) -> Optional[str]:
        """Exchange authorization code for access token"""
        try:
            token = yadisk.YaDisk.get_token(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                code=code,
                redirect_uri=REDIRECT_URI
            )
            return token
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return None
    
    def set_token(self, token: str):
        """Set access token for the client"""
        self.y = yadisk.YaDisk(token=token)
    
    async def list_folder_contents(self, path: str) -> Tuple[list, list]:
        """List contents of a folder"""
        files = []
        folders = []
        
        try:
            items = self.y.listdir(path)
            for item in items:
                if item.is_file():
                    files.append({
                        'name': item.name,
                        'path': item.path,
                        'size': item.size,
                        'type': 'file'
                    })
                elif item.is_dir():
                    folders.append({
                        'name': item.name,
                        'path': item.path,
                        'type': 'dir'
                    })
        except Exception as e:
            logger.error(f"Error listing folder {path}: {e}")
            raise
        
        return sorted(folders, key=lambda x: x['name']), sorted(files, key=lambda x: x['name'])
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from Yandex.Disk"""
        try:
            # Get download link
            download_link = self.y.get_download_link(file_path)
            
            # Download file content
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(download_link) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        raise Exception(f"Failed to download file: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error downloading file {file_path}: {e}")
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when /start is issued"""
    user_id = update.effective_user.id
    
    # Check if user is authenticated
    if user_id not in user_tokens:
        yandex_client = YandexDiskClient()
        auth_url = yandex_client.get_auth_url()
        
        message = (
            "🤖 *Добро пожаловать в бот Яндекс.Диска!*\n\n"
            "Для работы с вашими файлами необходимо авторизоваться.\n\n"
            f"🔗 [Нажмите для авторизации]({auth_url})\n\n"
            "После авторизации вы получите код. Отправьте его мне командой:\n"
            "`/auth КОД`"
        )
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text(
            "✅ Вы уже авторизованы!\n"
            "Используйте команду /list для просмотра файлов."
        )

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle OAuth authorization code"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "❌ Пожалуйста, укажите код авторизации.\n"
            "Пример: `/auth ваш_код`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    code = context.args[0]
    
    # Exchange code for token
    yandex_client = YandexDiskClient()
    token = yandex_client.get_token_from_code(code)
    
    if token:
        user_tokens[user_id] = token
        await update.message.reply_text(
            "✅ Авторизация успешна!\n"
            "Теперь вы можете использовать команду /list для просмотра файлов."
        )
        logger.info(f"User {user_id} authenticated successfully")
    else:
        await update.message.reply_text(
            "❌ Ошибка авторизации. Проверьте код и попробуйте снова."
        )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List files and folders in the specified Yandex.Disk folder"""
    user_id = update.effective_user.id
    
    # Check authentication
    if user_id not in user_tokens:
        await update.message.reply_text(
            "❌ Вы не авторизованы. Используйте /start для получения инструкций."
        )
        return
    
    # Initialize Yandex.Disk client
    yandex_client = YandexDiskClient(user_tokens[user_id])
    
    if not yandex_client.is_authenticated():
        await update.message.reply_text(
            "❌ Ошибка авторизации. Пожалуйста, выполните /start заново."
        )
        del user_tokens[user_id]
        return
    
    await update.message.reply_text("📂 Загружаю список файлов и папок...")
    
    try:
        folders, files = await yandex_client.list_folder_contents(YANDEX_FOLDER_PATH)
        
        if not folders and not files:
            await update.message.reply_text("📁 Папка пуста.")
            return
        
        # Create keyboard
        keyboard = []
        
        # Add folders
        for folder in folders:
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {folder['name']}",
                    callback_data=f"folder_{folder['path']}"
                )
            ])
        
        # Add files
        for file in files:
            # Format file size
            size_mb = file['size'] / (1024 * 1024)
            size_str = f" ({size_mb:.1f} MB)" if size_mb < 1000 else f" ({size_mb/1024:.1f} GB)"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📄 {file['name']}{size_str}",
                    callback_data=f"file_{file['path']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📂 *Содержимое папки:*\n`{YANDEX_FOLDER_PATH}`\n\n"
            f"📁 Папок: {len(folders)}\n"
            f"📄 Файлов: {len(files)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при получении списка файлов: {str(e)}"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # Check authentication
    if user_id not in user_tokens:
        await query.edit_message_text(
            "❌ Вы не авторизованы. Используйте /start для получения инструкций."
        )
        return
    
    # Parse callback data
    if data.startswith("file_"):
        # Handle file download
        file_path = data[5:]  # Remove "file_" prefix
        await download_file_handler(query, user_id, file_path)
    
    elif data.startswith("folder_"):
        # Handle folder navigation
        folder_path = data[7:]  # Remove "folder_" prefix
        await navigate_to_folder(query, user_id, folder_path)

async def download_file_handler(query, user_id: int, file_path: str):
    """Download and send file to user"""
    await query.edit_message_text(f"📥 Скачиваю файл...")
    
    yandex_client = YandexDiskClient(user_tokens[user_id])
    
    if not yandex_client.is_authenticated():
        await query.edit_message_text(
            "❌ Ошибка авторизации. Пожалуйста, выполните /start заново."
        )
        del user_tokens[user_id]
        return
    
    try:
        # Download file
        file_content = await yandex_client.download_file(file_path)
        
        # Get filename from path
        filename = file_path.split('/')[-1]
        
        # Send file to user
        await query.message.reply_document(
            document=file_content,
            filename=filename,
            caption=f"✅ Файл *{filename}* успешно загружен!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await query.edit_message_text(
            f"✅ Файл *{filename}* успешно отправлен!",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при скачивании файла: {str(e)}"
        )

async def navigate_to_folder(query, user_id: int, folder_path: str):
    """Navigate to a subfolder"""
    await query.edit_message_text(f"📂 Открываю папку...")
    
    yandex_client = YandexDiskClient(user_tokens[user_id])
    
    if not yandex_client.is_authenticated():
        await query.edit_message_text(
            "❌ Ошибка авторизации. Пожалуйста, выполните /start заново."
        )
        del user_tokens[user_id]
        return
    
    try:
        folders, files = await yandex_client.list_folder_contents(folder_path)
        
        if not folders and not files:
            await query.edit_message_text("📁 Папка пуста.")
            return
        
        # Create keyboard
        keyboard = []
        
        # Add back button
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data=f"back_{folder_path}")
        ])
        
        # Add folders
        for folder in folders:
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {folder['name']}",
                    callback_data=f"folder_{folder['path']}"
                )
            ])
        
        # Add files
        for file in files:
            size_mb = file['size'] / (1024 * 1024)
            size_str = f" ({size_mb:.1f} MB)" if size_mb < 1000 else f" ({size_mb/1024:.1f} GB)"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📄 {file['name']}{size_str}",
                    callback_data=f"file_{file['path']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get folder display name
        folder_display = folder_path.split('/')[-1] if folder_path != YANDEX_FOLDER_PATH else "Корневая папка"
        
        await query.edit_message_text(
            f"📂 *Папка:* `{folder_display}`\n\n"
            f"📁 Папок: {len(folders)}\n"
            f"📄 Файлов: {len(files)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error navigating to folder: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при открытии папки: {str(e)}"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message"""
    help_text = """
🤖 *Доступные команды:*

/start - Начать работу и получить инструкцию по авторизации
/auth [код] - Ввести код авторизации после получения
/list - Показать содержимое папки на Яндекс.Диске
/help - Показать это сообщение

*Как авторизоваться:*
1. Используйте /start для получения ссылки
2. Перейдите по ссылке и авторизуйтесь
3. Скопируйте полученный код
4. Отправьте команду /auth [код]

*Навигация:*
- Нажимайте на папки 📁 для перехода
- Нажимайте на файлы 📄 для скачивания
- Используйте кнопку "Назад" для возврата
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auth", auth))
    application.add_handler(CommandHandler("list", list_files))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()