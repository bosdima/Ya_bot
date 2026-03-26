import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import yadisk

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена и ссылки из .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
YANDEX_DISK_LINK = os.getenv('YANDEX_DISK_LINK')

# Инициализация Яндекс.Диска
y = yadisk.YaDisk()

class YandexDiskBot:
    def __init__(self):
        self.public_key = None
        self.file_info = None
        
    def extract_public_key(self, disk_link):
        """Извлечение публичного ключа из ссылки Яндекс.Диска"""
        try:
            # Извлекаем ID из ссылки
            if '/d/' in disk_link:
                file_id = disk_link.split('/d/')[1].split('/')[0]
                return file_id
            return None
        except Exception as e:
            logger.error(f"Ошибка при извлечении ключа: {e}")
            return None
    
    def check_file_availability(self):
        """Проверка доступности файла"""
        try:
            self.public_key = self.extract_public_key(YANDEX_DISK_LINK)
            if not self.public_key:
                return False, "Не удалось извлечь идентификатор файла"
            
            # Получаем информацию о публичном ресурсе
            public_resources = y.get_public_resources(self.public_key)
            
            if public_resources:
                self.file_info = public_resources
                return True, "Файл доступен"
            else:
                return False, "Файл не найден или недоступен"
                
        except Exception as e:
            logger.error(f"Ошибка при проверке файла: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def get_download_link(self):
        """Получение прямой ссылки для скачивания"""
        try:
            # Получаем информацию о файле
            resource_info = y.get_public_resources(self.public_key)
            
            if resource_info and 'file' in resource_info:
                # Получаем ссылку на скачивание
                download_url = y.get_download_link(resource_info['file'])
                return download_url
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении ссылки: {e}")
            return None

# Создаем экземпляр бота
yandex_bot = YandexDiskBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    welcome_text = f"""
Привет, {user.first_name}! 👋

Я бот для работы с файлами на Яндекс.Диске.

📁 Доступные команды:
/status - Проверить доступность файла
/download - Скачать файл
/help - Помощь

Файл настроен: {YANDEX_DISK_LINK}
"""
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
📚 Помощь по использованию бота:

1️⃣ /status - Проверить, доступен ли файл на Яндекс.Диске
2️⃣ /download - Начать скачивание файла
3️⃣ /start - Показать приветственное сообщение

📌 Примечания:
- Файл должен быть доступен по публичной ссылке
- Размер файла ограничен возможностями Telegram (до 50 МБ)
- При проблемах с доступом проверьте настройки файла на Яндекс.Диске
"""
    await update.message.reply_text(help_text)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса файла"""
    await update.message.reply_text("🔍 Проверяю доступность файла...")
    
    available, message = yandex_bot.check_file_availability()
    
    if available:
        status_text = f"""
✅ {message}

📊 Информация о файле:
"""
        if yandex_bot.file_info:
            if 'name' in yandex_bot.file_info:
                status_text += f"📄 Имя: {yandex_bot.file_info['name']}\n"
            if 'size' in yandex_bot.file_info:
                size_mb = yandex_bot.file_info['size'] / (1024 * 1024)
                status_text += f"💾 Размер: {size_mb:.2f} MB\n"
        
        keyboard = [[InlineKeyboardButton("📥 Скачать файл", callback_data='download')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(status_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"❌ {message}")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скачивание файла"""
    await update.message.reply_text("📥 Подготавливаю файл к скачиванию...")
    
    # Проверяем доступность файла
    available, message = yandex_bot.check_file_availability()
    
    if not available:
        await update.message.reply_text(f"❌ {message}")
        return
    
    # Получаем прямую ссылку
    download_url = yandex_bot.get_download_link()
    
    if not download_url:
        await update.message.reply_text("❌ Не удалось получить ссылку для скачивания")
        return
    
    try:
        await update.message.reply_text("⬇️ Начинаю загрузку файла...")
        
        # Скачиваем файл
        response = requests.get(download_url, stream=True)
        
        if response.status_code == 200:
            # Получаем имя файла из информации
            filename = yandex_bot.file_info.get('name', 'file') if yandex_bot.file_info else 'file'
            
            # Сохраняем временный файл
            temp_file = f"temp_{filename}"
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Отправляем файл в Telegram
            await update.message.reply_text("📤 Отправляю файл в Telegram...")
            
            with open(temp_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=f"📁 Файл: {filename}"
                )
            
            # Удаляем временный файл
            os.remove(temp_file)
            
            await update.message.reply_text("✅ Файл успешно отправлен!")
        else:
            await update.message.reply_text(f"❌ Ошибка при скачивании: HTTP {response.status_code}")
            
    except Exception as e:
        logger.error(f"Ошибка при скачивании: {e}")
        await update.message.reply_text(f"❌ Ошибка при скачивании файла: {str(e)}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'download':
        await download(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик обычных сообщений"""
    await update.message.reply_text(
        "Используйте команды:\n"
        "/start - Начать\n"
        "/status - Проверить файл\n"
        "/download - Скачать файл\n"
        "/help - Помощь"
    )

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("download", download))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    print(f"📁 Яндекс.Диск ссылка: {YANDEX_DISK_LINK}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()