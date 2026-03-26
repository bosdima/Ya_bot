import os
import logging
import requests
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
YANDEX_DISK_URL = os.getenv('YANDEX_DISK_URL')

class YandexDiskDownloader:
    """Класс для работы с Яндекс.Диском"""
    
    def __init__(self, url):
        self.url = url
        self.file_name = None
        self.direct_link = None
        
    def extract_public_key(self):
        """Извлечение публичного ключа из ссылки"""
        try:
            # Извлекаем ID файла из ссылки
            if '/d/' in self.url:
                file_id = self.url.split('/d/')[1].split('?')[0]
                return file_id
            return None
        except Exception as e:
            logger.error(f"Ошибка при извлечении ключа: {e}")
            return None
    
    def get_file_info(self):
        """Получение информации о файле с Яндекс.Диска"""
        try:
            public_key = self.extract_public_key()
            if not public_key:
                return False
            
            # API Яндекс.Диска для публичных ресурсов
            api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={public_key}"
            
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                if 'name' in data:
                    self.file_name = data['name']
                    self.direct_link = self.get_download_link(public_key)
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при получении информации о файле: {e}")
            return False
    
    def get_download_link(self, public_key):
        """Получение прямой ссылки для скачивания"""
        try:
            api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={public_key}"
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                return data.get('href')
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении ссылки для скачивания: {e}")
            return None
    
    def download_file(self, save_path):
        """Скачивание файла"""
        try:
            if not self.direct_link:
                return None
            
            response = requests.get(self.direct_link, stream=True)
            if response.status_code == 200:
                file_path = Path(save_path) / self.file_name
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                return file_path
            return None
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла: {e}")
            return None

class TelegramBot:
    """Класс для управления Telegram ботом"""
    
    def __init__(self, token, disk_url):
        self.token = token
        self.disk_url = disk_url
        self.downloader = YandexDiskDownloader(disk_url)
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_text = """
🤖 *Привет! Я бот для скачивания файлов с Яндекс.Диска*

📁 *Доступный файл:* `bot_dca.py`

🔍 Для проверки доступности файла используйте команду:
`/check`

📥 Для скачивания файла используйте команду:
`/download`

Или нажмите на кнопки ниже 👇
        """
        
        keyboard = [
            [InlineKeyboardButton("🔍 Проверить файл", callback_data="check")],
            [InlineKeyboardButton("📥 Скачать файл", callback_data="download")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def check_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка доступности файла"""
        await update.message.reply_text("🔄 Проверяю доступность файла на Яндекс.Диске...")
        
        if self.downloader.get_file_info():
            file_info = f"""
✅ *Файл доступен!*

📄 *Имя файла:* `{self.downloader.file_name}`
📊 *Статус:* Готов к скачиванию

Для скачивания используйте команду `/download` или нажмите кнопку ниже.
            """
            keyboard = [[InlineKeyboardButton("📥 Скачать файл", callback_data="download")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                file_info, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "❌ *Файл не найден или недоступен!*\n"
                "Проверьте ссылку и попробуйте снова.",
                parse_mode='Markdown'
            )
    
    async def download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скачивание и отправка файла"""
        await update.message.reply_text("🔄 Проверяю доступность файла...")
        
        if not self.downloader.get_file_info():
            await update.message.reply_text("❌ Файл не найден или недоступен!")
            return
        
        await update.message.reply_text(f"📥 Начинаю скачивание файла `{self.downloader.file_name}`...", parse_mode='Markdown')
        
        # Создаем временную директорию для скачивания
        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)
        
        # Скачиваем файл
        file_path = self.downloader.download_file(temp_dir)
        
        if file_path and file_path.exists():
            await update.message.reply_text("📤 Отправляю файл в Telegram...")
            
            try:
                # Отправляем файл
                with open(file_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=self.downloader.file_name,
                        caption=f"✅ Файл `{self.downloader.file_name}` успешно скачан!"
                    )
                
                # Удаляем временный файл
                file_path.unlink()
                
            except Exception as e:
                logger.error(f"Ошибка при отправке файла: {e}")
                await update.message.reply_text(f"❌ Ошибка при отправке файла: {str(e)}")
        else:
            await update.message.reply_text("❌ Не удалось скачать файл!")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "check":
            await self.check_file(update, context)
        elif query.data == "download":
            await self.download_file(update, context)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = """
📚 *Доступные команды:*

/start - Запустить бота
/check - Проверить доступность файла
/download - Скачать файл
/help - Показать это сообщение

🔍 *Информация о файле:*
Файл `bot_dca.py` находится на Яндекс.Диске и доступен для скачивания.
        """
        
        keyboard = [
            [InlineKeyboardButton("🔍 Проверить файл", callback_data="check")],
            [InlineKeyboardButton("📥 Скачать файл", callback_data="download")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            help_text, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Ошибка: {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
    
    def run(self):
        """Запуск бота"""
        # Создаем приложение
        application = Application.builder().token(self.token).build()
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("check", self.check_file))
        application.add_handler(CommandHandler("download", self.download_file))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Добавляем обработчик ошибок
        application.add_error_handler(self.error_handler)
        
        # Запускаем бота
        print("🤖 Бот запущен и готов к работе!")
        print(f"📁 Ссылка на Яндекс.Диск: {self.disk_url}")
        print("Нажмите Ctrl+C для остановки")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Главная функция"""
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не найден в файле .env")
        return
    
    if not YANDEX_DISK_URL:
        print("❌ Ошибка: YANDEX_DISK_URL не найден в файле .env")
        return
    
    # Создаем и запускаем бота
    bot = TelegramBot(BOT_TOKEN, YANDEX_DISK_URL)
    bot.run()

if __name__ == "__main__":
    main()