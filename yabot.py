import os
import logging
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram import F

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Получение переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')
YANDEX_FOLDER_PATH = os.getenv('YANDEX_FOLDER_PATH')

# Проверка наличия всех необходимых переменных
required_vars = [BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, YANDEX_FOLDER_PATH]
if not all(required_vars):
    logger.error("Не все переменные окружения заданы!")
    exit(1)

# URL для Яндекс.Диск API
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
YANDEX_OAUTH_URL = "https://oauth.yandex.ru/authorize"

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище токенов пользователей (в реальном проекте используйте БД)
user_tokens: Dict[int, str] = {}

class YandexDiskAPI:
    """Класс для работы с Яндекс.Диск API"""
    
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"OAuth {token}",
            "Content-Type": "application/json"
        }
    
    async def get_folder_contents(self, path: str) -> Optional[Dict[str, Any]]:
        """Получение содержимого папки"""
        url = f"{YANDEX_API_BASE}/resources"
        params = {
            "path": path,
            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.path,_embedded.items.size,_embedded.items.modified"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка получения содержимого: {response.status} - {error_text}")
                        return None
            except Exception as e:
                logger.error(f"Исключение при запросе: {e}")
                return None
    
    async def get_download_link(self, path: str) -> Optional[str]:
        """Получение ссылки для скачивания файла"""
        url = f"{YANDEX_API_BASE}/resources/download"
        params = {"path": path}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("href")
                    else:
                        logger.error(f"Ошибка получения ссылки: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Исключение при получении ссылки: {e}")
                return None
    
    async def download_file(self, download_url: str) -> Optional[bytes]:
        """Скачивание файла по ссылке"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(download_url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Ошибка скачивания файла: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Исключение при скачивании: {e}")
                return None

def get_auth_url() -> str:
    """Получение URL для авторизации в Яндекс"""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI
    }
    return f"{YANDEX_OAUTH_URL}?{urlencode(params)}"

async def get_access_token(auth_code: str) -> Optional[str]:
    """Получение access token по коду авторизации"""
    url = "https://oauth.yandex.ru/token"
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("access_token")
                else:
                    logger.error(f"Ошибка получения токена: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при получении токена: {e}")
            return None

def format_size(size: int) -> str:
    """Форматирование размера файла"""
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ТБ"

def create_items_keyboard(items: list, path: str, is_root: bool = False) -> InlineKeyboardMarkup:
    """Создание клавиатуры с файлами и папками"""
    keyboard = []
    
    # Кнопка "Назад" если не в корневой папке
    if not is_root:
        parent_path = "/".join(path.split("/")[:-1]) if path else ""
        back_button = InlineKeyboardButton(
            text="📁 Назад",
            callback_data=f"folder:{parent_path if parent_path else '/'}"
        )
        keyboard.append([back_button])
    
    # Сортировка: сначала папки, потом файлы
    folders = [item for item in items if item['type'] == 'dir']
    files = [item for item in items if item['type'] == 'file']
    
    # Добавляем папки
    for folder in folders:
        folder_name = folder['name']
        folder_path = folder['path']
        keyboard.append([
            InlineKeyboardButton(
                text=f"📁 {folder_name}",
                callback_data=f"folder:{folder_path}"
            )
        ])
    
    # Добавляем файлы
    for file in files:
        file_name = file['name']
        file_size = format_size(file.get('size', 0))
        keyboard.append([
            InlineKeyboardButton(
                text=f"📄 {file_name} ({file_size})",
                callback_data=f"file:{file['path']}"
            )
        ])
    
    if not items:
        keyboard.append([InlineKeyboardButton(text="📂 Папка пуста", callback_data="empty")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    welcome_text = (
        "🤖 Привет! Я бот для работы с Яндекс.Диском\n\n"
        "Я могу показать содержимое папки:\n"
        f"`{YANDEX_FOLDER_PATH}`\n\n"
        "🔐 Для начала работы необходимо авторизоваться в Яндексе."
    )
    
    auth_button = InlineKeyboardButton(
        text="🔑 Авторизоваться в Яндекс",
        url=get_auth_url()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[auth_button]])
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    """Обработчик команды /list - показать содержимое папки"""
    user_id = message.from_user.id
    
    if user_id not in user_tokens:
        await message.answer(
            "⚠️ Вы не авторизованы!\n"
            "Используйте команду /start для авторизации."
        )
        return
    
    await show_folder_contents(message, YANDEX_FOLDER_PATH, is_root=True)

async def show_folder_contents(message: Message, folder_path: str, is_root: bool = False):
    """Показать содержимое папки"""
    user_id = message.from_user.id
    token = user_tokens[user_id]
    
    disk_api = YandexDiskAPI(token)
    contents = await disk_api.get_folder_contents(folder_path)
    
    if not contents:
        await message.answer("❌ Ошибка получения содержимого папки")
        return
    
    items = contents.get("_embedded", {}).get("items", [])
    
    if not items:
        await message.answer("📂 Папка пуста")
        return
    
    keyboard = create_items_keyboard(items, folder_path, is_root)
    folder_name = folder_path.split("/")[-1] if folder_path else "Корень"
    
    await message.answer(
        f"📁 Содержимое папки: *{folder_name}*\n"
        f"Всего элементов: {len(items)}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("folder:"))
async def handle_folder_callback(callback: CallbackQuery):
    """Обработка нажатия на папку"""
    folder_path = callback.data[7:]  # Убираем "folder:"
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла. Используйте /start", show_alert=True)
        return
    
    await callback.answer()
    
    # Отправляем новое сообщение с содержимым папки
    await show_folder_contents(callback.message, folder_path)
    
    # Удаляем предыдущее сообщение с клавиатурой
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

@dp.callback_query(F.data.startswith("file:"))
async def handle_file_callback(callback: CallbackQuery):
    """Обработка нажатия на файл"""
    file_path = callback.data[5:]  # Убираем "file:"
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла. Используйте /start", show_alert=True)
        return
    
    await callback.answer("⏬ Начинаю скачивание...")
    
    # Отправляем сообщение о начале загрузки
    status_message = await callback.message.answer(f"📥 Скачиваю файл...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        
        # Получаем ссылку на скачивание
        download_url = await disk_api.get_download_link(file_path)
        
        if not download_url:
            await status_message.edit_text("❌ Не удалось получить ссылку для скачивания")
            return
        
        # Скачиваем файл
        file_data = await disk_api.download_file(download_url)
        
        if not file_data:
            await status_message.edit_text("❌ Ошибка при скачивании файла")
            return
        
        # Получаем имя файла из пути
        file_name = file_path.split("/")[-1]
        
        # Отправляем файл пользователю
        await callback.message.answer_document(
            types.BufferedInputFile(file_data, filename=file_name),
            caption=f"✅ Файл *{file_name}* успешно загружен!",
            parse_mode="Markdown"
        )
        
        # Удаляем сообщение о статусе
        await status_message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка при скачивании файла: {e}")
        await status_message.edit_text(f"❌ Произошла ошибка: {str(e)}")

@dp.callback_query(F.data == "empty")
async def handle_empty_callback(callback: CallbackQuery):
    """Обработка нажатия на пустую папку"""
    await callback.answer("Папка пуста", show_alert=False)

@dp.message(F.text)
async def handle_auth_code(message: Message):
    """Обработка кода авторизации"""
    text = message.text.strip()
    
    # Проверяем, не является ли сообщение кодом авторизации
    if len(text) > 20 and not text.startswith("/"):
        user_id = message.from_user.id
        
        # Пытаемся получить токен
        token = await get_access_token(text)
        
        if token:
            user_tokens[user_id] = token
            await message.answer(
                "✅ Авторизация успешна!\n\n"
                "Теперь вы можете использовать команду /list для просмотра содержимого папки."
            )
        else:
            await message.answer(
                "❌ Ошибка авторизации. Проверьте код и попробуйте снова.\n"
                "Используйте команду /start для повторной авторизации."
            )
    else:
        # Игнорируем другие сообщения
        pass

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "📚 *Доступные команды:*\n\n"
        "/start - Начать работу и авторизоваться\n"
        "/list - Показать содержимое папки\n"
        "/help - Показать эту справку\n\n"
        "*Как работать:*\n"
        "1. Нажмите /start и перейдите по ссылке для авторизации\n"
        "2. Скопируйте код из адресной строки после авторизации\n"
        "3. Отправьте код боту\n"
        "4. Используйте /list для просмотра файлов и папок\n"
        "5. Нажимайте на файлы для скачивания\n\n"
        f"📁 *Путь на диске:* `{YANDEX_FOLDER_PATH}`"
    )
    
    await message.answer(help_text, parse_mode="Markdown")

async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())