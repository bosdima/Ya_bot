import os
import logging
import requests
import re
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
        self.file_size = None
        
    def extract_public_key(self):
        """Извлечение публичного ключа из ссылки"""
        try:
            # Поддерживаем разные форматы ссылок Яндекс.Диска
            patterns = [
                r'/d/([A-Za-z0-9_-]+)',  # Для disk.yandex.ru/d/...
                r's/([A-Za-z0-9_-]+)',   # Для disk.yandex.ru/s/...
                r'public\?key=([A-Za-z0-9_-]+)'  # Для публичных ссылок
            ]
            
            for pattern in patterns:
                match = re.search(pattern, self.url)
                if match:
                    return match.group(1)
            
            # Если ссылка в формате https://disk.yandex.ru/d/QWN9WPzTY9JqTw
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
                logger.error("Не удалось извлечь публичный ключ")
                return False
            
            logger.info(f"Публичный ключ: {public_key}")
            
            # API Яндекс.Диска для публичных ресурсов
            api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
            params = {
                'public_key': public_key
            }
            
            response = requests.get(api_url, params=params, timeout=30)
            logger.info(f"Статус ответа API: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Данные API: {data}")
                
                if 'name' in data:
                    self.file_name = data['name']
                    if 'size' in data:
                        self.file_size = data['size']
                    
                    # Получаем ссылку для скачивания
                    download_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
                    download_params = {
                        'public_key': public_key
                    }
                    
                    download_response = requests.get(download_url, params=download_params, timeout=30)
                    
                    if download_response.status_code == 200:
                        download_data = download_response.json()
                        self.direct_link = download_data.get('href')
                        logger.info(f"Получена ссылка для скачивания")
                        return True
                    else:
                        logger.error(f"Ошибка получения ссылки для скачивания: {download_response.status_code}")
                        return False
                        
            elif response.status_code == 404:
                logger.error("Файл не найден на Яндекс.Диске")
                return False
            else:
                logger.error(f"Ошибка API Яндекс.Диска: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Сетевая ошибка при получении информации о файле: {e}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при получении информации о файле: {e}")
            return False
    
    def download_file(self, save_path):
        """Скачивание файла"""
        try:
            if not self.direct_link:
                logger.error("Нет прямой ссылки для скачивания")
                return None
            
            logger.info(f"Начинаю скачивание файла: {self.file_name}")
            
            # Скачиваем файл с таймаутом
            response = requests.get(self.direct_link, stream=True, timeout=60)
            
            if response.status_code == 200:
                file_path = Path(save_path) / self.file_name
                
                # Скачиваем файл частями
                with open(file_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            logger.info(f"Скачано: {downloaded} байт")
                
                logger.info(f"Файл успешно скачан: {file_path}")
                return file_path
            else:
                logger.error(f"Ошибка при скачивании: {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Сетевая ошибка при скачивании файла: {e}")
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
        
        try:
            await update.message.reply_text(
                welcome_text, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка в start: {e}")
            await update.message.reply_text("❌ Произошла ошибка при запуске")
    
    async def check_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка доступности файла"""
        message = await update.message.reply_text("🔄 Проверяю доступность файла на Яндекс.Диске...")
        
        try:
            if self.downloader.get_file_info():
                size_mb = self.downloader.file_size / (1024 * 1024) if self.downloader.file_size else 0
                file_info = f"""
✅ *Файл доступен!*

📄 *Имя файла:* `{self.downloader.file_name}`
📊 *Размер:* {size_mb:.2f} MB
📁 *Статус:* Готов к скачиванию

Для скачивания используйте команду `/download` или нажмите кнопку ниже.
                """
                keyboard = [[InlineKeyboardButton("📥 Скачать файл", callback_data="download")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.edit_text(
                    file_info, 
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    "❌ *Файл не найден или недоступен!*\n"
                    "Проверьте ссылку и попробуйте снова.\n\n"
                    f"Текущая ссылка: `{self.disk_url}`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Ошибка в check_file: {e}")
            await message.edit_text("❌ Произошла ошибка при проверке файла")
    
    async def download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скачивание и отправка файла"""
        message = await update.message.reply_text("🔄 Проверяю доступность файла...")
        
        try:
            if not self.downloader.get_file_info():
                await message.edit_text("❌ Файл не найден или недоступен!")
                return
            
            await message.edit_text(f"📥 Начинаю скачивание файла `{self.downloader.file_name}`...", parse_mode='Markdown')
            
            # Создаем временную директорию для скачивания
            temp_dir = Path("temp")
            temp_dir.mkdir(exist_ok=True)
            
            # Скачиваем файл
            file_path = self.downloader.download_file(temp_dir)
            
            if file_path and file_path.exists():
                await message.edit_text("📤 Отправляю файл в Telegram...")
                
                try:
                    # Проверяем размер файла (Telegram ограничение 50MB)
                    file_size = file_path.stat().st_size
                    if file_size > 50 * 1024 * 1024:  # 50 MB
                        await message.edit_text("❌ Файл слишком большой для отправки в Telegram (максимум 50MB)")
                        file_path.unlink()
                        return
                    
                    # Отправляем файл
                    with open(file_path, 'rb') as f:
                        await update.message.reply_document(
                            document=f,
                            filename=self.downloader.file_name,
                            caption=f"✅ Файл `{self.downloader.file_name}` успешно скачан!"
                        )
                    
                    # Удаляем временный файл
                    file_path.unlink()
                    await message.delete()  # Удаляем сообщение о процессе
                    
                except Exception as e:
                    logger.error(f"Ошибка при отправке файла: {e}")
                    await message.edit_text(f"❌ Ошибка при отправке файла: {str(e)}")
                    if file_path.exists():
                        file_path.unlink()
            else:
                await message.edit_text("❌ Не удалось скачать файл!")
                
        except Exception as e:
            logger.error(f"Ошибка в download_file: {e}")
            await message.edit_text(f"❌ Произошла ошибка: {str(e)}")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data == "check":
                # Создаем фейковое сообщение для check_file
                class FakeUpdate:
                    def __init__(self, message):
                        self.message = message
                
                fake_update = FakeUpdate(query.message)
                await self.check_file(fake_update, context)
                
            elif query.data == "download":
                fake_update = FakeUpdate(query.message)
                await self.download_file(fake_update, context)
                
        except Exception as e:
            logger.error(f"Ошибка в button_handler: {e}")
            await query.message.reply_text("❌ Произошла ошибка при обработке кнопки")
    
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
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        except:
            pass
    
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
