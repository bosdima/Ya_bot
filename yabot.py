import os
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import urllib.parse

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class YandexDiskAPI:
    """Class for interacting with Yandex Disk REST API"""
    
    def __init__(self):
        self.client_id = os.getenv('YANDEX_CLIENT_ID')
        self.client_secret = os.getenv('YANDEX_CLIENT_SECRET')
        self.redirect_uri = os.getenv('YANDEX_REDIRECT_URI')
        self.base_url = "https://cloud-api.yandex.net/v1/disk"
        self.auth_url = "https://oauth.yandex.ru/authorize"
        self.token_url = "https://oauth.yandex.ru/token"
        self.access_token = None
        
    def get_auth_link(self) -> str:
        """Generate authorization link for Yandex OAuth"""
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri
        }
        return f"{self.auth_url}?{urllib.parse.urlencode(params)}"
    
    def set_access_token(self, token: str):
        """Set access token for API calls"""
        self.access_token = token
        
    def get_token_from_code(self, code: str) -> Optional[str]:
        """Exchange authorization code for access token"""
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri
        }
        
        try:
            response = requests.post(self.token_url, data=data)
            if response.status_code == 200:
                token_data = response.json()
                return token_data.get('access_token')
            else:
                logger.error(f"Failed to get token: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return None
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Yandex Disk API"""
        if not self.access_token:
            logger.error("No access token available")
            return None
            
        headers = {
            'Authorization': f'OAuth {self.access_token}'
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/{endpoint}",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error making request: {e}")
            return None
    
    def get_files_and_folders(self, path: str) -> Optional[List[Dict]]:
        """Get list of files and folders at specified path"""
        params = {
            'path': path,
            'limit': 100,
            'fields': '_embedded.items.name,_embedded.items.type,_embedded.items.path,_embedded.items.size,_embedded.items.modified'
        }
        
        data = self._make_request("resources", params)
        
        if data and '_embedded' in data and 'items' in data['_embedded']:
            return data['_embedded']['items']
        return None
    
    def get_file_download_link(self, path: str) -> Optional[str]:
        """Get download link for a file"""
        params = {'path': path}
        data = self._make_request("resources/download", params)
        
        if data and 'href' in data:
            return data['href']
        return None
    
    def download_file(self, download_url: str) -> Optional[bytes]:
        """Download file from URL"""
        try:
            response = requests.get(download_url, stream=True)
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Failed to download file: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None

class YandexDiskBot:
    """Main bot class"""
    
    def __init__(self):
        self.bot_token = os.getenv('TG_BOT_TOKEN')
        self.target_path = os.getenv('YANDEX_TARGET_PATH', '')
        self.max_file_size_mb = int(os.getenv('MAX_FILE_SIZE_MB', 50))
        self.max_file_size_bytes = self.max_file_size_mb * 1024 * 1024
        self.yandex = YandexDiskAPI()
        
        # Store user sessions (in production, use database)
        self.user_tokens = {}
        self.user_current_paths = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        
        welcome_text = (
            "👋 *Добро пожаловать в бот для работы с Яндекс.Диском!*\n\n"
            "Я помогу вам просматривать файлы и папки на Яндекс.Диске и скачивать их.\n\n"
            "🔐 *Для начала работы необходимо авторизоваться:*\n"
            f"[Нажмите здесь для авторизации]({self.yandex.get_auth_link()})\n\n"
            "После авторизации вы получите код. Отправьте его мне командой:\n"
            "`/auth <код>`\n\n"
            "📁 *Доступные команды:*\n"
            "/start - Показать это сообщение\n"
            "/auth <код> - Авторизоваться в Яндекс.Диске\n"
            "/list - Показать содержимое текущей папки\n"
            "/download <имя_файла> - Скачать файл\n"
            "/cd <папка> - Перейти в папку\n"
            "/cd .. - Вернуться на уровень вверх\n"
            "/pwd - Показать текущий путь\n"
            "/logout - Выйти из аккаунта"
        )
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    async def auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /auth command to set access token"""
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(
                "❌ *Ошибка:* Пожалуйста, укажите код авторизации.\n"
                "Пример: `/auth your_code_here`",
                parse_mode='Markdown'
            )
            return
        
        code = context.args[0]
        
        # Get token from code
        token = self.yandex.get_token_from_code(code)
        
        if token:
            # Store token for user
            self.user_tokens[user_id] = token
            self.user_current_paths[user_id] = self.target_path
            
            # Set token for API
            self.yandex.set_access_token(token)
            
            await update.message.reply_text(
                "✅ *Авторизация успешна!*\n\n"
                f"Текущая папка: `{self.target_path}`\n"
                "Используйте `/list` для просмотра содержимого.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *Ошибка авторизации:* Не удалось получить токен.\n"
                "Пожалуйста, проверьте код и попробуйте снова.",
                parse_mode='Markdown'
            )
    
    async def list_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command to show files and folders"""
        user_id = update.effective_user.id
        
        # Check authentication
        if user_id not in self.user_tokens:
            await update.message.reply_text(
                "🔐 *Необходима авторизация*\n"
                "Используйте `/start` для получения инструкций по авторизации.",
                parse_mode='Markdown'
            )
            return
        
        # Set token for current user
        self.yandex.set_access_token(self.user_tokens[user_id])
        
        current_path = self.user_current_paths.get(user_id, self.target_path)
        
        # Send "loading" message
        loading_msg = await update.message.reply_text("⏳ Загрузка содержимого папки...")
        
        # Get files and folders
        items = self.yandex.get_files_and_folders(current_path)
        
        if items is None:
            await loading_msg.edit_text(
                "❌ *Ошибка:* Не удалось получить содержимое папки.\n"
                "Проверьте путь и доступ к Яндекс.Диску.",
                parse_mode='Markdown'
            )
            return
        
        if not items:
            await loading_msg.edit_text("📂 *Папка пуста*", parse_mode='Markdown')
            return
        
        # Prepare message
        message_parts = [f"📁 *Содержимое папки:*\n`{current_path}`\n"]
        
        folders = []
        files = []
        
        for item in items:
            name = item.get('name', 'unknown')
            item_type = item.get('type', 'file')
            size = item.get('size', 0)
            
            if item_type == 'dir':
                folders.append(f"📁 `{name}/`")
            else:
                size_mb = size / (1024 * 1024)
                size_display = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb/1024:.2f} GB"
                files.append(f"📄 `{name}` ({size_display})")
        
        if folders:
            message_parts.append("\n📂 *Папки:*")
            message_parts.extend(folders[:50])  # Limit to 50 items
        
        if files:
            message_parts.append("\n📄 *Файлы:*")
            message_parts.extend(files[:50])
        
        if len(items) > 50:
            message_parts.append(f"\n*...и еще {len(items) - 50} элементов*")
        
        # Create inline keyboard for navigation
        keyboard = []
        
        # Add folder buttons for first 20 folders
        for folder in folders[:20]:
            folder_name = folder.split('`')[1].rstrip('/')
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {folder_name}",
                    callback_data=f"cd_{folder_name}"
                )
            ])
        
        # Add download buttons for files
        for file in files[:20]:
            file_name = file.split('`')[1].split(' ')[0]
            keyboard.append([
                InlineKeyboardButton(
                    f"📥 {file_name[:30]}",
                    callback_data=f"download_{file_name}"
                )
            ])
        
        # Add navigation buttons
        nav_buttons = []
        if current_path != '/':
            nav_buttons.append(InlineKeyboardButton("⬆️ На уровень вверх", callback_data="cd_.."))
        nav_buttons.append(InlineKeyboardButton("🔄 Обновить", callback_data="refresh"))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        # Update message
        await loading_msg.edit_text(
            "\n".join(message_parts),
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle file download"""
        user_id = update.effective_user.id
        
        # Check authentication
        if user_id not in self.user_tokens:
            await update.message.reply_text(
                "🔐 *Необходима авторизация*\n"
                "Используйте `/start` для получения инструкций.",
                parse_mode='Markdown'
            )
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ *Ошибка:* Укажите имя файла для скачивания.\n"
                "Пример: `/download filename.txt`",
                parse_mode='Markdown'
            )
            return
        
        file_name = ' '.join(context.args)
        current_path = self.user_current_paths.get(user_id, self.target_path)
        file_path = f"{current_path}/{file_name}"
        
        # Set token
        self.yandex.set_access_token(self.user_tokens[user_id])
        
        # Get download link
        download_link = self.yandex.get_file_download_link(file_path)
        
        if not download_link:
            await update.message.reply_text(
                f"❌ *Ошибка:* Не удалось найти файл `{file_name}`",
                parse_mode='Markdown'
            )
            return
        
        # Send "downloading" message
        status_msg = await update.message.reply_text(f"⏳ Скачивание файла `{file_name}`...", parse_mode='Markdown')
        
        # Download file
        file_content = self.yandex.download_file(download_link)
        
        if file_content:
            # Check file size
            if len(file_content) > self.max_file_size_bytes:
                await status_msg.edit_text(
                    f"⚠️ *Файл слишком большой*\n"
                    f"Размер: {len(file_content) / (1024 * 1024):.2f} MB\n"
                    f"Максимальный размер: {self.max_file_size_mb} MB\n\n"
                    f"Попробуйте скачать через Яндекс.Диск:\n{download_link}",
                    parse_mode='Markdown'
                )
                return
            
            # Send file to Telegram
            try:
                await update.message.reply_document(
                    document=file_content,
                    filename=file_name,
                    caption=f"✅ Файл `{file_name}` успешно скачан!",
                    parse_mode='Markdown'
                )
                
                await status_msg.delete()
            except Exception as e:
                await status_msg.edit_text(
                    f"❌ *Ошибка отправки:* {str(e)}\n"
                    f"Файл может быть слишком большим для Telegram.",
                    parse_mode='Markdown'
                )
        else:
            await status_msg.edit_text(
                f"❌ *Ошибка:* Не удалось скачать файл `{file_name}`",
                parse_mode='Markdown'
            )
    
    async def change_directory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cd command to change directory"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_tokens:
            await update.message.reply_text(
                "🔐 *Необходима авторизация*",
                parse_mode='Markdown'
            )
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ *Ошибка:* Укажите папку для перехода.\n"
                "Пример: `/cd папка` или `/cd ..`",
                parse_mode='Markdown'
            )
            return
        
        folder = context.args[0]
        current_path = self.user_current_paths.get(user_id, self.target_path)
        
        if folder == '..':
            # Go up one level
            new_path = '/'.join(current_path.split('/')[:-1])
            if not new_path:
                new_path = '/'
        else:
            new_path = f"{current_path}/{folder}" if current_path != '/' else f"/{folder}"
        
        # Check if new path exists
        self.yandex.set_access_token(self.user_tokens[user_id])
        items = self.yandex.get_files_and_folders(new_path)
        
        if items is None:
            await update.message.reply_text(
                f"❌ *Ошибка:* Папка `{folder}` не существует или недоступна.",
                parse_mode='Markdown'
            )
            return
        
        self.user_current_paths[user_id] = new_path
        
        await update.message.reply_text(
            f"✅ *Перешли в папку:*\n`{new_path}`\n\n"
            "Используйте `/list` для просмотра содержимого.",
            parse_mode='Markdown'
        )
    
    async def show_current_path(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pwd command to show current path"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_tokens:
            await update.message.reply_text(
                "🔐 *Необходима авторизация*",
                parse_mode='Markdown'
            )
            return
        
        current_path = self.user_current_paths.get(user_id, self.target_path)
        
        await update.message.reply_text(
            f"📍 *Текущий путь:*\n`{current_path}`",
            parse_mode='Markdown'
        )
    
    async def logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /logout command"""
        user_id = update.effective_user.id
        
        if user_id in self.user_tokens:
            del self.user_tokens[user_id]
        
        if user_id in self.user_current_paths:
            del self.user_current_paths[user_id]
        
        await update.message.reply_text(
            "👋 *Вы вышли из аккаунта Яндекс.Диска*\n\n"
            "Для повторной авторизации используйте `/start`",
            parse_mode='Markdown'
        )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data.startswith('cd_'):
            # Change directory
            folder = data[3:]
            if folder == '..':
                # Go up
                current_path = self.user_current_paths.get(user_id, self.target_path)
                new_path = '/'.join(current_path.split('/')[:-1])
                if not new_path:
                    new_path = '/'
                self.user_current_paths[user_id] = new_path
            else:
                # Enter folder
                current_path = self.user_current_paths.get(user_id, self.target_path)
                new_path = f"{current_path}/{folder}" if current_path != '/' else f"/{folder}"
                self.user_current_paths[user_id] = new_path
            
            # Refresh the list
            await self.show_list_inline(query, user_id)
        
        elif data.startswith('download_'):
            # Download file
            file_name = data[9:]
            current_path = self.user_current_paths.get(user_id, self.target_path)
            file_path = f"{current_path}/{file_name}"
            
            # Set token
            self.yandex.set_access_token(self.user_tokens[user_id])
            
            # Get download link
            download_link = self.yandex.get_file_download_link(file_path)
            
            if download_link:
                # Download and send file
                await query.message.reply_text(f"⏳ Скачивание `{file_name}`...", parse_mode='Markdown')
                file_content = self.yandex.download_file(download_link)
                
                if file_content:
                    if len(file_content) > self.max_file_size_bytes:
                        await query.message.reply_text(
                            f"⚠️ *Файл слишком большой*\nМаксимум: {self.max_file_size_mb} MB",
                            parse_mode='Markdown'
                        )
                    else:
                        await query.message.reply_document(
                            document=file_content,
                            filename=file_name
                        )
                else:
                    await query.message.reply_text("❌ Ошибка скачивания")
            else:
                await query.message.reply_text(f"❌ Не удалось найти файл `{file_name}`", parse_mode='Markdown')
        
        elif data == 'refresh':
            # Refresh current directory
            await self.show_list_inline(query, user_id)
    
    async def show_list_inline(self, query, user_id):
        """Show file list in inline mode"""
        self.yandex.set_access_token(self.user_tokens[user_id])
        current_path = self.user_current_paths.get(user_id, self.target_path)
        
        items = self.yandex.get_files_and_folders(current_path)
        
        if not items:
            await query.message.edit_text("📂 *Папка пуста или недоступна*", parse_mode='Markdown')
            return
        
        message_parts = [f"📁 *Содержимое:*\n`{current_path}`\n"]
        
        folders = []
        files = []
        
        for item in items:
            name = item.get('name', 'unknown')
            item_type = item.get('type', 'file')
            
            if item_type == 'dir':
                folders.append(f"📁 `{name}/`")
            else:
                size = item.get('size', 0)
                size_mb = size / (1024 * 1024)
                size_display = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb/1024:.2f} GB"
                files.append(f"📄 `{name}` ({size_display})")
        
        if folders:
            message_parts.append("\n📂 *Папки:*")
            message_parts.extend(folders[:30])
        
        if files:
            message_parts.append("\n📄 *Файлы:*")
            message_parts.extend(files[:30])
        
        # Create keyboard
        keyboard = []
        for folder in folders[:20]:
            folder_name = folder.split('`')[1].rstrip('/')
            keyboard.append([InlineKeyboardButton(f"📁 {folder_name}", callback_data=f"cd_{folder_name}")])
        
        for file in files[:15]:
            file_name = file.split('`')[1].split(' ')[0]
            keyboard.append([InlineKeyboardButton(f"📥 {file_name[:25]}", callback_data=f"download_{file_name}")])
        
        nav_buttons = []
        if current_path != '/':
            nav_buttons.append(InlineKeyboardButton("⬆️ Наверх", callback_data="cd_.."))
        nav_buttons.append(InlineKeyboardButton("🔄 Обновить", callback_data="refresh"))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await query.message.edit_text(
            "\n".join(message_parts),
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    def run(self):
        """Run the bot"""
        application = Application.builder().token(self.bot_token).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("auth", self.auth))
        application.add_handler(CommandHandler("list", self.list_files))
        application.add_handler(CommandHandler("download", self.download_file))
        application.add_handler(CommandHandler("cd", self.change_directory))
        application.add_handler(CommandHandler("pwd", self.show_current_path))
        application.add_handler(CommandHandler("logout", self.logout))
        
        # Add callback query handler for inline buttons
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Start the bot
        print("🤖 Bot is starting...")
        application.run_polling()

if __name__ == '__main__':
    bot = YandexDiskBot()
    bot.run()