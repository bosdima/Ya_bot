import os
import logging
import requests
import re
import json
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
        self.file_name = "bot_dca.py"
        self.direct_link = None
        self.file_size = None
        
    def get_direct_link_from_page(self):
        """Получение прямой ссылки через парсинг страницы"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Получаем страницу
            response = requests.get(self.url, headers=headers, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # Ищем ссылку на скачивание в HTML
            html = response.text
            
            # Поиск имени файла
            name_patterns = [
                r'<meta property="og:title" content="([^"]+)"',
                r'<title>([^<]+) — Яндекс\.Диск</title>',
                r'"name":"([^"]+\.py)"',
                r'class="resources-container__title"[^>]*>([^<]+)'
            ]
            
            for pattern in name_patterns:
                match = re.search(pattern, html)
                if match and '.py' in match.group(1):
                    self.file_name = match.group(1).strip()
                    logger.info(f"Найдено имя файла: {self.file_name}")
                    break
            
            # Поиск ссылки на скачивание
            link_patterns = [
                r'https://downloader\.disk\.yandex\.ru/disk/[^\s"\'<>]+',
                r'https://[^\s"\'<>]+\.yandex\.net/[^\s"\'<>]+\.py[^\s"\'<>]*',
                r'"file":"([^"]+)"',
                r'data-url="([^"]+)"',
                r'href="(https://[^"]+\.py[^"]*)"'
            ]
            
            for pattern in link_patterns:
                matches = re.findall(pattern, html)
                for match in matches:
                    if 'downloader' in match or 'yandex' in match:
                        self.direct_link = match
                        logger.info(f"Найдена ссылка на скачивание: {self.direct_link}")
                        return True
            
            # Альтернативный метод - использование API Яндекс.Диска через другой эндпоинт
            return self.get_file_via_api_v2()
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге страницы: {e}")
            return self.get_file_via_api_v2()
    
    def get_file_via_api_v2(self):
        """Альтернативный метод через API Яндекс.Диска v2"""
        try:
            # Извлекаем ID из ссылки
            file_id = None
            if '/d/' in self.url:
                file_id = self.url.split('/d/')[1].split('?')[0]
            elif '/s/' in self.url:
                file_id = self.url.split('/s/')[1].split('?')[0]
            
            if not file_id:
                logger.error("Не удалось извлечь ID файла")
                return False
            
            # Используем публичное API Яндекс.Диска
            api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={file_id}"
            
            response = requests.get(api_url, timeout=30)
            logger.info(f"API ответ: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if 'name' in data:
                    self.file_name = data['name']
                
                # Получаем ссылку для скачивания
                download_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={file_id}"
                download_response = requests.get(download_url, timeout=30)
                
                if download_response.status_code == 200:
                    download_data = download_response.json()
                    self.direct_link = download_data.get('href')
                    if self.direct_link:
                        logger.info(f"Получена ссылка через API v2")
                        return True
                        
            return False
            
        except Exception as e:
            logger.error(f"Ошибка в API v2: {e}")
            return False
    
    def get_file_info(self):
        """Получение информации о файле"""
        try:
            return self.get_direct_link_from_page()
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
            logger.info(f"Ссылка для скачивания: {self.direct_link}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*'
            }
            
            # Скачиваем файл с таймаутом
            response = requests.get(self.direct_link, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                file_path = Path(save_path) / self.file_name
                
                # Скачиваем файл частями
                with open(file_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded % 102400 == 0:  # Каждые 100KB
                                logger.info(f"Скачано: {downloaded} байт")
                
                logger.info(f"Файл успешно скачан: {file_path}")
                return file_path
            else:
                logger.error(f"Ошибка при скачивании: {response.status_code}")
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

📁 *Файл:* `bot_dca.py`

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
            # Проверяем доступность файла
            if self.downloader.get_file_info():
                file_info = f"""
✅ *Файл доступен!*

📄 *Имя файла:* `{self.downloader.file_name}`
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
                    "Проверьте, что файл доступен по ссылке и попробуйте снова.\n\n"
                    f"Ссылка: `{self.disk_url}`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Ошибка в check_file: {e}")
            await message.edit_text(f"❌ Произошла ошибка при проверке: {str(e)}")
    
    async def download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Скачивание и отправка файла"""
        message = await update.message.reply_text("🔄 Проверяю доступность файла...")
        
        try:
            # Получаем информацию о файле
            if not self.downloader.get_file_info():
                await message.edit_text("❌ Файл не найден или недоступен!")
                return
            
            await message.edit_text(f"📥 Начинаю скачивание файла `{self.downloader.file_name}`...", parse_mode='Markdown')
            
            # Создаем временную директорию
            temp_dir = Path("temp")
            temp_dir.mkdir(exist_ok=True)
            
            # Скачиваем файл
            file_path = self.downloader.download_file(temp_dir)
            
            if file_path and file_path.exists():
                await message.edit_text("📤 Отправляю файл в Telegram...")
                
                try:
                    # Проверяем размер файла
                    file_size = file_path.stat().st_size
                    if file_size > 50 * 1024 * 1024:
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
                    await message.delete()
                    
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
            # Создаем фейковое сообщение
            class FakeMessage:
                def __init__(self, real_message):
                    self.real_message = real_message
                    self.chat = real_message.chat
                
                async def reply_text(self, *args, **kwargs):
                    return await self.real_message.reply_text(*args, **kwargs)
                
                async def edit_text(self, *args, **kwargs):
                    return await self.real_message.edit_text(*args, **kwargs)
                
                async def delete(self):
                    return await self.real_message.delete()
            
            class FakeUpdate:
                def __init__(self, message):
                    self.message = FakeMessage(message)
            
            fake_update = FakeUpdate(query.message)
            
            if query.data == "check":
                await self.check_file(fake_update, context)
            elif query.data == "download":
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

🔍 *Информация:*
Бот скачивает файл `bot_dca.py` с Яндекс.Диска и отправляет его в Telegram.
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
        application = Application.builder().token(self.token).build()
        
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("check", self.check_file))
        application.add_handler(CommandHandler("download", self.download_file))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CallbackQueryHandler(self.button_handler))
        application.add_error_handler(self.error_handler)
        
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
    
    bot = TelegramBot(BOT_TOKEN, YANDEX_DISK_URL)
    bot.run()

if __name__ == "__main__":
    main()
