import os
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена и данных из .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
YANDEX_FOLDER_URL = os.getenv('YANDEX_FOLDER_URL')
YANDEX_FOLDER_PASSWORD = os.getenv('YANDEX_FOLDER_PASSWORD')

class YandexDiskParser:
    def __init__(self, folder_url, password):
        self.folder_url = folder_url
        self.password = password
        self.session = requests.Session()
        
    def get_public_key(self):
        """Получение публичного ключа от папки"""
        try:
            # Парсим URL для получения ID папки
            parsed_url = urlparse(self.folder_url)
            path_parts = parsed_url.path.split('/')
            
            if 'd' in path_parts:
                folder_id = path_parts[path_parts.index('d') + 1]
                return folder_id
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении ключа: {e}")
            return None
    
    def get_folder_contents(self):
        """Получение содержимого папки с Яндекс.Диска"""
        try:
            folder_id = self.get_public_key()
            if not folder_id:
                return []
            
            # Формируем URL для API Яндекс.Диска
            api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={self.folder_url}&limit=100"
            
            response = self.session.get(api_url)
            
            if response.status_code == 200:
                data = response.json()
                files = []
                
                if 'items' in data:
                    for item in data['items']:
                        files.append({
                            'name': item.get('name'),
                            'type': item.get('type'),
                            'size': item.get('size'),
                            'modified': item.get('modified'),
                            'path': item.get('path'),
                            'download_url': item.get('file')
                        })
                
                return files
            else:
                # Пробуем альтернативный метод через парсинг HTML
                return self.get_folder_contents_html()
                
        except Exception as e:
            logger.error(f"Ошибка при получении содержимого папки: {e}")
            return []
    
    def get_folder_contents_html(self):
        """Альтернативный метод получения содержимого папки через HTML парсинг"""
        try:
            # Добавляем пароль в параметры запроса
            params = {'p': self.password}
            response = self.session.get(self.folder_url, params=params)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                files = []
                
                # Ищем элементы с файлами (это может потребовать корректировки в зависимости от структуры страницы)
                file_elements = soup.find_all('div', class_='listing-item')
                
                for element in file_elements:
                    name_elem = element.find('div', class_='listing-item__name')
                    if name_elem:
                        files.append({
                            'name': name_elem.text.strip(),
                            'type': 'file',
                            'size': 0,
                            'modified': '',
                            'path': '',
                            'download_url': ''
                        })
                
                return files
            return []
        except Exception as e:
            logger.error(f"Ошибка при HTML парсинге: {e}")
            return []

    def download_file(self, file_path):
        """Скачивание файла"""
        try:
            # Формируем URL для скачивания файла
            download_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={self.folder_url}&path={file_path}"
            
            response = self.session.get(download_url)
            
            if response.status_code == 200:
                data = response.json()
                if 'href' in data:
                    file_response = self.session.get(data['href'])
                    return file_response.content
            return None
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла: {e}")
            return None

class TelegramBot:
    def __init__(self, token, yandex_parser):
        self.token = token
        self.yandex_parser = yandex_parser
        self.application = Application.builder().token(token).build()
        
    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("list", self.list_files_command))
        self.application.add_handler(CommandHandler("update", self.update_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_message = (
            "🤖 *Добро пожаловать в бот для работы с Яндекс.Диском!*\n\n"
            "📁 *Доступные команды:*\n"
            "/list - показать содержимое папки\n"
            "/update - обновить список файлов\n"
            "/help - показать справку\n\n"
            "Выберите действие:"
        )
        
        keyboard = [
            [InlineKeyboardButton("📂 Показать файлы", callback_data="list_files")],
            [InlineKeyboardButton("🔄 Обновить список", callback_data="update_files")],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = (
            "📖 *Справка по использованию бота:*\n\n"
            "📁 *Основные команды:*\n"
            "/list - показывает все файлы в папке Яндекс.Диска\n"
            "/update - обновляет список файлов\n\n"
            "📄 *Как это работает:*\n"
            "1. Бот подключается к вашей папке на Яндекс.Диске\n"
            "2. Показывает список всех файлов\n"
            "3. Вы можете скачать любой файл, нажав на кнопку\n\n"
            "🔒 *Безопасность:*\n"
            "Все данные хранятся локально и не передаются третьим лицам"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def list_files_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /list - показать содержимое папки"""
        await self.show_files(update, context)
    
    async def update_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /update - обновить список файлов"""
        await update.message.reply_text("🔄 Обновляю список файлов...")
        files = self.yandex_parser.get_folder_contents()
        
        if files:
            context.user_data['cached_files'] = files
            await update.message.reply_text(f"✅ Обновлено! Найдено {len(files)} файлов")
            await self.show_files(update, context)
        else:
            await update.message.reply_text("❌ Не удалось получить список файлов. Проверьте ссылку и пароль.")
    
    async def show_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список файлов"""
        # Проверяем, есть ли кэшированные файлы
        if 'cached_files' not in context.user_data:
            await update.message.reply_text("🔄 Получаю список файлов...")
            context.user_data['cached_files'] = self.yandex_parser.get_folder_contents()
        
        files = context.user_data.get('cached_files', [])
        
        if not files:
            await update.message.reply_text("❌ В папке нет файлов или не удалось получить доступ.")
            return
        
        # Создаем клавиатуру с файлами
        keyboard = []
        for i, file in enumerate(files[:20]):  # Ограничиваем 20 файлами для удобства
            file_name = file['name'][:30] + "..." if len(file['name']) > 30 else file['name']
            keyboard.append([InlineKeyboardButton(f"📄 {file_name}", callback_data=f"file_{i}")])
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="refresh")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        file_count = len(files)
        message = f"📂 *Содержимое папки* (всего файлов: {file_count})\n\n"
        
        if file_count > 20:
            message += f"*Показаны первые 20 файлов из {file_count}*\n\n"
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "list_files":
            await self.show_files_callback(query, context)
        elif query.data == "update_files":
            await self.update_files_callback(query, context)
        elif query.data == "refresh":
            await self.refresh_files_callback(query, context)
        elif query.data == "help":
            await self.help_callback(query, context)
        elif query.data.startswith("file_"):
            await self.handle_file_selection(query, context)
    
    async def show_files_callback(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Показать файлы в callback режиме"""
        if 'cached_files' not in context.user_data:
            await query.edit_message_text("🔄 Получаю список файлов...")
            context.user_data['cached_files'] = self.yandex_parser.get_folder_contents()
        
        files = context.user_data.get('cached_files', [])
        
        if not files:
            await query.edit_message_text("❌ В папке нет файлов или не удалось получить доступ.")
            return
        
        keyboard = []
        for i, file in enumerate(files[:20]):
            file_name = file['name'][:30] + "..." if len(file['name']) > 30 else file['name']
            keyboard.append([InlineKeyboardButton(f"📄 {file_name}", callback_data=f"file_{i}")])
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="refresh")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"📂 *Содержимое папки* (всего файлов: {len(files)})\n\n"
        if len(files) > 20:
            message += f"*Показаны первые 20 файлов из {len(files)}*\n\n"
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def update_files_callback(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Обновить список файлов в callback режиме"""
        await query.edit_message_text("🔄 Обновляю список файлов...")
        files = self.yandex_parser.get_folder_contents()
        
        if files:
            context.user_data['cached_files'] = files
            await query.edit_message_text(f"✅ Обновлено! Найдено {len(files)} файлов")
            await self.show_files_callback(query, context)
        else:
            await query.edit_message_text("❌ Не удалось получить список файлов. Проверьте ссылку и пароль.")
    
    async def refresh_files_callback(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Обновить список файлов"""
        await self.update_files_callback(query, context)
    
    async def help_callback(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Показать помощь в callback режиме"""
        help_text = (
            "📖 *Справка:*\n\n"
            "📁 *Доступные действия:*\n"
            "• Нажмите на файл для получения информации\n"
            "• Используйте кнопку обновления для синхронизации\n\n"
            "🔧 *Команды:*\n"
            "/start - начать работу\n"
            "/list - показать файлы\n"
            "/update - обновить список"
        )
        await query.edit_message_text(help_text, parse_mode='Markdown')
    
    async def handle_file_selection(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора файла"""
        file_index = int(query.data.split('_')[1])
        files = context.user_data.get('cached_files', [])
        
        if 0 <= file_index < len(files):
            file_info = files[file_index]
            
            info_text = (
                f"📄 *Информация о файле:*\n\n"
                f"*Имя:* {file_info['name']}\n"
                f"*Тип:* {file_info['type']}\n"
            )
            
            if file_info.get('size'):
                size_kb = file_info['size'] / 1024
                if size_kb < 1024:
                    info_text += f"*Размер:* {size_kb:.2f} KB\n"
                else:
                    info_text += f"*Размер:* {size_kb/1024:.2f} MB\n"
            
            if file_info.get('modified'):
                info_text += f"*Изменен:* {file_info['modified'][:10]}\n"
            
            keyboard = [[InlineKeyboardButton("🔙 Назад к списку", callback_data="list_files")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик обычных сообщений"""
        await update.message.reply_text(
            "Используйте команды:\n/start - начать\n/list - показать файлы\n/update - обновить\n/help - помощь"
        )
    
    def run(self):
        """Запуск бота"""
        self.setup_handlers()
        logger.info("Бот запущен и готов к работе")
        self.application.run_polling()

def main():
    """Главная функция"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден в .env файле")
        return
    
    if not YANDEX_FOLDER_URL or not YANDEX_FOLDER_PASSWORD:
        logger.error("Данные Яндекс.Диска не найдены в .env файле")
        return
    
    # Создаем парсер Яндекс.Диска
    yandex_parser = YandexDiskParser(YANDEX_FOLDER_URL, YANDEX_FOLDER_PASSWORD)
    
    # Создаем и запускаем бота
    bot = TelegramBot(BOT_TOKEN, yandex_parser)
    bot.run()

if __name__ == '__main__':
    main()