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
# Хранилище состояний авторизации
auth_states: Dict[int, bool] = {}

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
        
        logger.info(f"Запрос к API: {url}, path={path}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    logger.info(f"Ответ API: статус {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Получено {len(data.get('_embedded', {}).get('items', []))} элементов")
                        return data
                    elif response.status == 401:
                        logger.error("Токен истек или недействителен")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка получения содержимого: {response.status} - {error_text}")
                        return None
            except Exception as e:
                logger.error(f"Исключение при запросе: {e}", exc_info=True)
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
        "client_secret": CLIENT_SECRET
    }
    
    logger.info(f"Запрос токена с кодом: {auth_code[:10]}...")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    token = result.get("access_token")
                    logger.info("Токен успешно получен")
                    return token
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения токена: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при получении токена: {e}")
            return None

def format_size(size: int) -> str:
    """Форматирование размера файла"""
    if not size:
        return "0 Б"
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ТБ"

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    # Проверяем, авторизован ли пользователь
    if user_id in user_tokens:
        welcome_text = (
            f"🤖 Привет! Я бот для работы с Яндекс.Диском\n\n"
            f"✅ Вы уже авторизованы!\n\n"
            f"📁 Текущая папка:\n"
            f"`{YANDEX_FOLDER_PATH}`\n\n"
            f"Используйте команду /list для просмотра содержимого."
        )
        await message.answer(welcome_text, parse_mode="Markdown")
    else:
        # Устанавливаем флаг ожидания кода авторизации
        auth_states[user_id] = True
        
        welcome_text = (
            "🤖 Привет! Я бот для работы с Яндекс.Диском\n\n"
            "Я могу показать содержимое папки:\n"
            f"`{YANDEX_FOLDER_PATH}`\n\n"
            "🔐 Для начала работы необходимо авторизоваться в Яндексе.\n\n"
            "1️⃣ Нажмите кнопку ниже\n"
            "2️⃣ Авторизуйтесь в Яндексе\n"
            "3️⃣ Скопируйте код из адресной строки\n"
            "4️⃣ Отправьте код мне в чат\n\n"
            "⚠️ *Важно:* Код авторизации обычно состоит из букв и цифр\n"
            "и выглядит примерно так: `tdchvjlvdtb5zkhk`"
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
    
    logger.info(f"Команда /list от пользователя {user_id}")
    
    if user_id not in user_tokens:
        await message.answer(
            "⚠️ Вы не авторизованы!\n\n"
            "Используйте команду /start для авторизации."
        )
        return
    
    # Отправляем сообщение о начале загрузки
    status_msg = await message.answer(f"📂 Загружаю содержимое папки...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        contents = await disk_api.get_folder_contents(YANDEX_FOLDER_PATH)
        
        if not contents:
            await status_msg.edit_text(
                f"❌ Не удалось получить содержимое папки.\n\n"
                f"Путь: `{YANDEX_FOLDER_PATH}`\n\n"
                f"Попробуйте использовать /listroot для просмотра корневой папки",
                parse_mode="Markdown"
            )
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        if not items:
            await status_msg.edit_text("📂 Папка пуста")
            return
        
        # Удаляем сообщение о загрузке
        await status_msg.delete()
        
        # Создаем клавиатуру
        keyboard = []
        
        # Сначала папки
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                folder_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📁 {folder_name}",
                    callback_data=f"folder:{folder_path}"
                )])
        
        # Потом файлы
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📄 {file_name} ({file_size})",
                    callback_data=f"file:{file_path}"
                )])
        
        # Добавляем кнопку обновления
        keyboard.append([InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="refresh"
        )])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        # Подсчитываем статистику
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        # Отправляем сообщение с содержимым
        await message.answer(
            f"📁 *Содержимое папки:*\n"
            f"`{YANDEX_FOLDER_PATH}`\n\n"
            f"📊 *Найдено элементов:* {len(items)}\n"
            f"📁 *Папок:* {folders_count}\n"
            f"📄 *Файлов:* {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в /list: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ Произошла ошибка при загрузке: {str(e)}\n\n"
            f"Пожалуйста, попробуйте позже или используйте /checkpath для диагностики."
        )

@dp.message(Command("checkpath"))
async def cmd_check_path(message: Message):
    """Проверка существования пути на Яндекс.Диске"""
    user_id = message.from_user.id
    
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь с помощью /start")
        return
    
    status_msg = await message.answer(f"🔍 Проверяю путь: `{YANDEX_FOLDER_PATH}`", parse_mode="Markdown")
    
    disk_api = YandexDiskAPI(user_tokens[user_id])
    contents = await disk_api.get_folder_contents(YANDEX_FOLDER_PATH)
    
    if contents:
        items = contents.get("_embedded", {}).get("items", [])
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        await status_msg.edit_text(
            f"✅ Папка найдена!\n\n"
            f"📁 Путь: `{YANDEX_FOLDER_PATH}`\n"
            f"📊 Всего элементов: {len(items)}\n"
            f"📁 Папок: {folders_count}\n"
            f"📄 Файлов: {files_count}\n\n"
            f"Используйте /list для просмотра содержимого",
            parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(
            f"❌ Папка не найдена!\n\n"
            f"Проверенный путь: `{YANDEX_FOLDER_PATH}`\n\n"
            f"Возможные причины:\n"
            f"• Папка не существует\n"
            f"• Неправильный путь (проверьте регистр и пробелы)\n"
            f"• Нет прав доступа\n\n"
            f"Попробуйте использовать /listroot для просмотра корневой папки",
            parse_mode="Markdown"
        )

@dp.message(Command("listroot"))
async def cmd_list_root(message: Message):
    """Показать корневую папку Яндекс.Диска"""
    user_id = message.from_user.id
    
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь с помощью /start")
        return
    
    status_msg = await message.answer("📂 Загружаю содержимое корневой папки...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        contents = await disk_api.get_folder_contents("/")
        
        if not contents:
            await status_msg.edit_text("❌ Не удалось получить содержимое корневой папки")
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        if not items:
            await status_msg.edit_text("📂 Корневая папка пуста")
            return
        
        await status_msg.delete()
        
        # Создаем клавиатуру
        keyboard = []
        
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                folder_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📁 {folder_name}",
                    callback_data=f"folder:{folder_path}"
                )])
        
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📄 {file_name} ({file_size})",
                    callback_data=f"file:{file_path}"
                )])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        await message.answer(
            f"📁 *Корневая папка Яндекс.Диска*\n\n"
            f"📊 *Найдено элементов:* {len(items)}\n"
            f"📁 *Папок:* {folders_count}\n"
            f"📄 *Файлов:* {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в /listroot: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    """Обработчик команды /logout - выход из аккаунта"""
    user_id = message.from_user.id
    
    if user_id in user_tokens:
        del user_tokens[user_id]
        if user_id in auth_states:
            del auth_states[user_id]
        await message.answer(
            "✅ Вы успешно вышли из аккаунта Яндекс.\n"
            "Используйте /start для повторной авторизации."
        )
    else:
        await message.answer("Вы не были авторизованы.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "📚 *Доступные команды:*\n\n"
        "/start - Начать работу и авторизоваться\n"
        "/list - Показать содержимое папки\n"
        "/checkpath - Проверить существование папки\n"
        "/listroot - Показать корневую папку диска\n"
        "/logout - Выйти из аккаунта Яндекс\n"
        "/help - Показать эту справку\n\n"
        "*🔐 Как авторизоваться:*\n"
        "1️⃣ Нажмите /start\n"
        "2️⃣ Нажмите кнопку 'Авторизоваться в Яндекс'\n"
        "3️⃣ Войдите в свой аккаунт Яндекс\n"
        "4️⃣ Скопируйте код из адресной строки\n"
        "5️⃣ Отправьте этот код боту\n\n"
        "*📁 Как работать:*\n"
        "• После авторизации используйте /list\n"
        "• Нажимайте на папки для навигации\n"
        "• Нажимайте на файлы для скачивания\n"
        "• Используйте кнопку 'Обновить' для обновления\n\n"
        f"📁 *Текущая папка на диске:*\n"
        f"`{YANDEX_FOLDER_PATH}`"
    )
    
    await message.answer(help_text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("folder:"))
async def handle_folder_callback(callback: CallbackQuery):
    """Обработка нажатия на папку"""
    folder_path = callback.data[7:]  # Убираем "folder:"
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла. Используйте /start", show_alert=True)
        return
    
    await callback.answer()
    
    status_msg = await callback.message.answer(f"📂 Открываю папку...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        contents = await disk_api.get_folder_contents(folder_path)
        
        if not contents:
            await status_msg.edit_text("❌ Не удалось открыть папку")
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        # Создаем клавиатуру
        keyboard = []
        
        # Кнопка назад (если не корневая папка)
        if folder_path != "/":
            parent_path = "/".join(folder_path.split("/")[:-1]) if folder_path != "/" else "/"
            if not parent_path:
                parent_path = "/"
            keyboard.append([InlineKeyboardButton(
                text="📁 Назад",
                callback_data=f"folder:{parent_path}"
            )])
        
        # Добавляем папки
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                item_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📁 {folder_name}",
                    callback_data=f"folder:{item_path}"
                )])
        
        # Добавляем файлы
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📄 {file_name} ({file_size})",
                    callback_data=f"file:{file_path}"
                )])
        
        if not items:
            keyboard.append([InlineKeyboardButton(text="📂 Папка пуста", callback_data="empty")])
        
        # Добавляем кнопку обновления
        keyboard.append([InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=f"refresh_folder:{folder_path}"
        )])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        folder_name = folder_path.split("/")[-1] if folder_path != "/" else "Корень"
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        await status_msg.delete()
        
        await callback.message.answer(
            f"📁 *Папка:* `{folder_name}`\n"
            f"📊 *Элементов:* {len(items)}\n"
            f"📁 *Папок:* {folders_count}\n"
            f"📄 *Файлов:* {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
        # Удаляем предыдущее сообщение
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при открытии папки: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")

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
        logger.error(f"Ошибка при скачивании файла: {e}", exc_info=True)
        await status_message.edit_text(f"❌ Произошла ошибка: {str(e)}")

@dp.callback_query(F.data == "refresh")
async def handle_refresh_callback(callback: CallbackQuery):
    """Обработка обновления содержимого корневой папки"""
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла. Используйте /start", show_alert=True)
        return
    
    await callback.answer("🔄 Обновляю...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        contents = await disk_api.get_folder_contents(YANDEX_FOLDER_PATH)
        
        if not contents:
            await callback.message.edit_text("❌ Не удалось обновить содержимое папки")
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        # Создаем клавиатуру
        keyboard = []
        
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                folder_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📁 {folder_name}",
                    callback_data=f"folder:{folder_path}"
                )])
        
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📄 {file_name} ({file_size})",
                    callback_data=f"file:{file_path}"
                )])
        
        keyboard.append([InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="refresh"
        )])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        await callback.message.edit_text(
            f"📁 *Содержимое папки:*\n"
            f"`{YANDEX_FOLDER_PATH}`\n\n"
            f"📊 *Найдено элементов:* {len(items)}\n"
            f"📁 *Папок:* {folders_count}\n"
            f"📄 *Файлов:* {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Ошибка обновления: {str(e)}")

@dp.callback_query(F.data.startswith("refresh_folder:"))
async def handle_refresh_folder_callback(callback: CallbackQuery):
    """Обработка обновления содержимого папки"""
    folder_path = callback.data[15:]  # Убираем "refresh_folder:"
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла. Используйте /start", show_alert=True)
        return
    
    await callback.answer("🔄 Обновляю...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        contents = await disk_api.get_folder_contents(folder_path)
        
        if not contents:
            await callback.message.edit_text("❌ Не удалось обновить содержимое папки")
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        # Создаем клавиатуру
        keyboard = []
        
        # Кнопка назад
        if folder_path != "/":
            parent_path = "/".join(folder_path.split("/")[:-1]) if folder_path != "/" else "/"
            if not parent_path:
                parent_path = "/"
            keyboard.append([InlineKeyboardButton(
                text="📁 Назад",
                callback_data=f"folder:{parent_path}"
            )])
        
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                item_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📁 {folder_name}",
                    callback_data=f"folder:{item_path}"
                )])
        
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(
                    text=f"📄 {file_name} ({file_size})",
                    callback_data=f"file:{file_path}"
                )])
        
        if not items:
            keyboard.append([InlineKeyboardButton(text="📂 Папка пуста", callback_data="empty")])
        
        keyboard.append([InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data=f"refresh_folder:{folder_path}"
        )])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        folder_name = folder_path.split("/")[-1] if folder_path != "/" else "Корень"
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        
        await callback.message.edit_text(
            f"📁 *Папка:* `{folder_name}`\n"
            f"📊 *Элементов:* {len(items)}\n"
            f"📁 *Папок:* {folders_count}\n"
            f"📄 *Файлов:* {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении папки: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Ошибка обновления: {str(e)}")

@dp.callback_query(F.data == "empty")
async def handle_empty_callback(callback: CallbackQuery):
    """Обработка нажатия на пустую папку"""
    await callback.answer("Папка пуста", show_alert=False)

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_auth_code(message: Message):
    """Обработка кода авторизации"""
    text = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем, ожидаем ли мы код авторизации от этого пользователя
    if user_id in auth_states and auth_states[user_id]:
        # Показываем, что идет обработка
        status_msg = await message.answer("🔄 Выполняю авторизацию...")
        
        # Пытаемся получить токен
        token = await get_access_token(text)
        
        if token:
            user_tokens[user_id] = token
            # Снимаем флаг ожидания авторизации
            auth_states[user_id] = False
            
            await status_msg.edit_text(
                "✅ Авторизация успешна!\n\n"
                "Теперь вы можете использовать команду /list для просмотра содержимого папки."
            )
            
            # Показываем содержимое папки сразу после авторизации
            await cmd_list(message)
        else:
            await status_msg.edit_text(
                "❌ Ошибка авторизации.\n\n"
                "Возможные причины:\n"
                "• Неверный код подтверждения\n"
                "• Код уже был использован\n"
                "• Код истек (действует 5 минут)\n\n"
                "Попробуйте снова с помощью команды /start"
            )
    else:
        # Если пользователь не ожидает код, даем подсказку
        if user_id not in user_tokens:
            await message.answer(
                "❓ Я не понимаю эту команду.\n\n"
                "Чтобы авторизоваться:\n"
                "1. Используйте /start\n"
                "2. Нажмите кнопку авторизации\n"
                "3. Скопируйте код из адресной строки\n"
                "4. Отправьте код мне\n\n"
                "Или используйте /help для списка команд."
            )

async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")
    logger.info(f"Путь к папке на Яндекс.Диске: {YANDEX_FOLDER_PATH}")
    logger.info(f"Bot token: {BOT_TOKEN[:10]}...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
