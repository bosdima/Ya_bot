import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlencode
from datetime import datetime
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
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
DEFAULT_YANDEX_FOLDER_PATH = os.getenv('YANDEX_FOLDER_PATH', '/')

# Проверка наличия всех необходимых переменных
if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    logger.error("Не все переменные окружения заданы!")
    exit(1)

# URL для Яндекс.Диск API
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
YANDEX_OAUTH_URL = "https://oauth.yandex.ru/authorize"

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Файл для хранения настроек пользователей
SETTINGS_FILE = "user_settings.json"

# Хранилище токенов пользователей
user_tokens: Dict[int, str] = {}
# Хранилище состояний авторизации
auth_states: Dict[int, bool] = {}
# Хранилище настроек пользователей
user_settings: Dict[int, Dict[str, Any]] = {}
# Хранилище задач мониторинга
monitoring_tasks: Dict[int, asyncio.Task] = {}


def load_settings():
    """Загрузка настроек из файла"""
    global user_settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Конвертируем ключи из строк в int
                user_settings = {int(k): v for k, v in data.items()}
            logger.info(f"Загружены настройки для {len(user_settings)} пользователей")
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
            user_settings = {}
    else:
        user_settings = {}


def save_settings():
    """Сохранение настроек в файл"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_settings, f, ensure_ascii=False, indent=2)
        logger.info("Настройки сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")


def export_settings(user_id: int) -> str:
    """Экспорт настроек пользователя в JSON строку"""
    settings = user_settings.get(user_id, {})
    export_data = {
        "user_id": user_id,
        "folder_path": settings.get("folder_path", DEFAULT_YANDEX_FOLDER_PATH),
        "check_interval_minutes": settings.get("check_interval_minutes", 60),
        "auto_check_enabled": settings.get("auto_check_enabled", True),
        "last_check": settings.get("last_check", None)
    }
    return json.dumps(export_data, ensure_ascii=False, indent=2)


def import_settings(user_id: int, settings_json: str) -> bool:
    """Импорт настроек пользователя из JSON строки"""
    try:
        data = json.loads(settings_json)
        if user_id not in user_settings:
            user_settings[user_id] = {}
        
        if "folder_path" in data:
            user_settings[user_id]["folder_path"] = data["folder_path"]
        if "check_interval_minutes" in data:
            user_settings[user_id]["check_interval_minutes"] = data["check_interval_minutes"]
        if "auto_check_enabled" in data:
            user_settings[user_id]["auto_check_enabled"] = data["auto_check_enabled"]
        
        save_settings()
        return True
    except Exception as e:
        logger.error(f"Ошибка импорта настроек: {e}")
        return False


def get_user_folder_path(user_id: int) -> str:
    """Получить путь к папке для пользователя"""
    return user_settings.get(user_id, {}).get("folder_path", DEFAULT_YANDEX_FOLDER_PATH)


def get_user_interval(user_id: int) -> int:
    """Получить интервал проверки для пользователя (в минутах)"""
    return user_settings.get(user_id, {}).get("check_interval_minutes", 60)


def get_auto_check_enabled(user_id: int) -> bool:
    """Получить статус автопроверки для пользователя"""
    return user_settings.get(user_id, {}).get("auto_check_enabled", True)


def set_user_folder_path(user_id: int, path: str):
    """Установить путь к папке для пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id]["folder_path"] = path
    save_settings()


def set_user_interval(user_id: int, minutes: int):
    """Установить интервал проверки для пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id]["check_interval_minutes"] = minutes
    save_settings()


def set_auto_check_enabled(user_id: int, enabled: bool):
    """Установить статус автопроверки для пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id]["auto_check_enabled"] = enabled
    save_settings()
    
    # Если автопроверка выключена, останавливаем мониторинг
    if not enabled and user_id in monitoring_tasks:
        if not monitoring_tasks[user_id].done():
            monitoring_tasks[user_id].cancel()
            logger.info(f"Мониторинг остановлен для пользователя {user_id}")
    # Если включена - запускаем
    elif enabled and user_id in user_tokens:
        asyncio.create_task(start_monitoring(user_id))


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Получить основную клавиатуру с кнопками"""
    buttons = [
        [KeyboardButton(text="📁 Показать папку")],
        [KeyboardButton(text="📂 Показать корень")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🔍 Тест сейчас")],
        [KeyboardButton(text="🚪 Выйти"), KeyboardButton(text="❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_settings_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Получить клавиатуру настроек с учетом статуса автопроверки"""
    auto_check_enabled = get_auto_check_enabled(user_id)
    
    if auto_check_enabled:
        auto_check_button = "✅ Автопроверка включена"
    else:
        auto_check_button = "❌ Автопроверка выключена"
    
    buttons = [
        [KeyboardButton(text="📁 Указать путь к папке")],
        [KeyboardButton(text="⏱️ Указать интервал проверки (мин)")],
        [KeyboardButton(text=auto_check_button)],
        [KeyboardButton(text="📤 Экспорт настроек")],
        [KeyboardButton(text="📥 Импорт настроек")],
        [KeyboardButton(text="◀️ Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


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
                        data = await response.json()
                        return data
                    elif response.status == 401:
                        logger.error("Токен истек или недействителен")
                        return None
                    else:
                        logger.error(f"Ошибка: {response.status}")
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
    if not size:
        return "0 Б"
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ТБ"


async def check_folder_and_notify(user_id: int):
    """Проверка папки и отправка уведомления"""
    # Проверяем, включена ли автопроверка
    if not get_auto_check_enabled(user_id):
        logger.info(f"Автопроверка выключена для пользователя {user_id}, пропускаем проверку")
        return
    
    token = user_tokens.get(user_id)
    if not token:
        return
    
    folder_path = get_user_folder_path(user_id)
    
    try:
        disk_api = YandexDiskAPI(token)
        contents = await disk_api.get_folder_contents(folder_path)
        
        if contents:
            items = contents.get("_embedded", {}).get("items", [])
            folders_count = len([i for i in items if i.get('type') == 'dir'])
            files_count = len([i for i in items if i.get('type') == 'file'])
            
            await bot.send_message(
                user_id,
                f"📊 *Результат проверки* ({datetime.now().strftime('%H:%M:%S')})\n\n"
                f"📁 Папка: `{folder_path}`\n"
                f"📊 Элементов: {len(items)}\n"
                f"📁 Папок: {folders_count}\n"
                f"📄 Файлов: {files_count}",
                parse_mode="Markdown"
            )
            
            # Обновляем время последней проверки
            if user_id not in user_settings:
                user_settings[user_id] = {}
            user_settings[user_id]["last_check"] = datetime.now().isoformat()
            save_settings()
            
    except Exception as e:
        logger.error(f"Ошибка при проверке: {e}")


async def start_monitoring(user_id: int):
    """Запуск периодического мониторинга"""
    # Проверяем, включена ли автопроверка
    if not get_auto_check_enabled(user_id):
        logger.info(f"Автопроверка выключена для пользователя {user_id}, мониторинг не запускается")
        return
    
    # Останавливаем существующую задачу
    if user_id in monitoring_tasks and not monitoring_tasks[user_id].done():
        monitoring_tasks[user_id].cancel()
    
    async def monitor():
        while True:
            # Проверяем статус автопроверки перед каждой итерацией
            if not get_auto_check_enabled(user_id):
                logger.info(f"Автопроверка выключена для пользователя {user_id}, мониторинг остановлен")
                break
            
            interval_minutes = get_user_interval(user_id)
            await asyncio.sleep(interval_minutes * 60)
            await check_folder_and_notify(user_id)
    
    monitoring_tasks[user_id] = asyncio.create_task(monitor())
    logger.info(f"Запущен мониторинг для пользователя {user_id} с интервалом {get_user_interval(user_id)} мин")


async def show_folder(message: Message, folder_path: str, edit_mode: bool = False):
    """Показать содержимое папки"""
    user_id = message.from_user.id
    token = user_tokens.get(user_id)
    
    if not token:
        await message.answer("⚠️ Вы не авторизованы! Используйте /start")
        return
    
    await message.answer("📂 Загружаю содержимое папки...")
    
    try:
        disk_api = YandexDiskAPI(token)
        contents = await disk_api.get_folder_contents(folder_path)
        
        if not contents:
            await message.answer(f"❌ Не удалось получить содержимое папки.\n\nПуть: `{folder_path}`")
            return
        
        items = contents.get("_embedded", {}).get("items", [])
        
        if not items:
            await message.answer("📂 Папка пуста")
            return
        
        keyboard = []
        
        if folder_path != "/":
            parent_path = "/".join(folder_path.split("/")[:-1]) or "/"
            keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"folder:{parent_path}")])
        
        for item in items:
            if item.get('type') == 'dir':
                folder_name = item.get('name', 'Без названия')
                folder_path_item = item.get('path', '')
                keyboard.append([InlineKeyboardButton(text=f"📁 {folder_name}", callback_data=f"folder:{folder_path_item}")])
        
        for item in items:
            if item.get('type') == 'file':
                file_name = item.get('name', 'Без названия')
                file_size = format_size(item.get('size', 0))
                file_path = item.get('path', '')
                keyboard.append([InlineKeyboardButton(text=f"📄 {file_name} ({file_size})", callback_data=f"file:{file_path}")])
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh:{folder_path}")])
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        folders_count = len([i for i in items if i.get('type') == 'dir'])
        files_count = len([i for i in items if i.get('type') == 'file'])
        folder_display = folder_path.split("/")[-1] if folder_path != "/" else "Корень"
        
        await message.answer(
            f"📁 *{folder_display}*\n\n"
            f"📊 Всего: {len(items)} элементов\n"
            f"📁 Папок: {folders_count}\n"
            f"📄 Файлов: {files_count}",
            reply_markup=inline_kb,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")


# Обработчики текстовых кнопок
@dp.message(F.text == "📁 Показать папку")
async def button_show_folder(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    await show_folder(message, get_user_folder_path(user_id))


@dp.message(F.text == "📂 Показать корень")
async def button_show_root(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    await show_folder(message, "/")


@dp.message(F.text == "⚙️ Настройки")
async def button_settings(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    folder_path = get_user_folder_path(user_id)
    interval = get_user_interval(user_id)
    auto_check_status = "✅ Включена" if get_auto_check_enabled(user_id) else "❌ Выключена"
    
    await message.answer(
        f"⚙️ *Настройки*\n\n"
        f"📁 Папка: `{folder_path}`\n"
        f"⏱️ Интервал: {interval} мин.\n"
        f"🔄 Автопроверка: {auto_check_status}\n\n"
        f"Выберите действие:",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(user_id)
    )


@dp.message(F.text == "🔍 Тест сейчас")
async def button_test_now(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    await message.answer("🔍 Выполняю проверку...")
    await check_folder_and_notify(user_id)


@dp.message(F.text == "🚪 Выйти")
async def button_logout(message: Message):
    await cmd_logout(message)


@dp.message(F.text == "❓ Помощь")
async def button_help(message: Message):
    await cmd_help(message)


@dp.message(F.text == "◀️ Назад")
async def button_back(message: Message):
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())


@dp.message(F.text == "📁 Указать путь к папке")
async def button_set_folder_path(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    auth_states[user_id] = "waiting_folder_path"
    await message.answer(
        "📁 Введите путь к папке на Яндекс.Диске\n\n"
        "Примеры:\n"
        "`/` - корень\n"
        "`/Documents` - папка Documents\n"
        "`/Photos/2024` - вложенная папка\n\n"
        "Отправьте путь:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="◀️ Отмена")]], resize_keyboard=True)
    )


@dp.message(F.text == "⏱️ Указать интервал проверки (мин)")
async def button_set_interval(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    auth_states[user_id] = "waiting_interval"
    await message.answer(
        "⏱️ Введите интервал проверки в минутах\n\n"
        "Примеры: 30, 60, 120\n\n"
        "Отправьте число:",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="◀️ Отмена")]], resize_keyboard=True)
    )


@dp.message(F.text == "✅ Автопроверка включена")
@dp.message(F.text == "❌ Автопроверка выключена")
async def button_toggle_auto_check(message: Message):
    """Переключение статуса автопроверки"""
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    current_status = get_auto_check_enabled(user_id)
    new_status = not current_status
    
    set_auto_check_enabled(user_id, new_status)
    
    if new_status:
        await message.answer("✅ Автопроверка ВКЛЮЧЕНА")
        # Запускаем мониторинг
        await start_monitoring(user_id)
    else:
        await message.answer("❌ Автопроверка ВЫКЛЮЧЕНА")
        # Останавливаем мониторинг, если он запущен
        if user_id in monitoring_tasks and not monitoring_tasks[user_id].done():
            monitoring_tasks[user_id].cancel()
            logger.info(f"Мониторинг остановлен для пользователя {user_id}")
    
    # Обновляем клавиатуру настроек
    await button_settings(message)


@dp.message(F.text == "📤 Экспорт настроек")
async def button_export_settings(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    settings_json = export_settings(user_id)
    # Сохраняем в файл и отправляем
    filename = f"settings_{user_id}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(settings_json)
    
    with open(filename, 'rb') as f:
        await message.answer_document(
            types.BufferedInputFile(f.read(), filename=filename),
            caption="📤 Ваши настройки"
        )
    
    os.remove(filename)


@dp.message(F.text == "📥 Импорт настроек")
async def button_import_settings(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    
    auth_states[user_id] = "waiting_import_file"
    await message.answer(
        "📥 Отправьте JSON файл с настройками (экспортированный ранее)",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="◀️ Отмена")]], resize_keyboard=True)
    )


@dp.message(F.text == "◀️ Отмена")
async def button_cancel(message: Message):
    user_id = message.from_user.id
    if user_id in auth_states:
        del auth_states[user_id]
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard())


# Основные команды
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    if user_id in user_tokens:
        await message.answer(
            f"✅ Вы уже авторизованы!\n\n"
            f"📁 Папка: `{get_user_folder_path(user_id)}`\n"
            f"⏱️ Интервал: {get_user_interval(user_id)} мин.\n"
            f"🔄 Автопроверка: {'✅ Включена' if get_auto_check_enabled(user_id) else '❌ Выключена'}\n\n"
            f"Используйте кнопки ниже:",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    else:
        auth_states[user_id] = True
        
        welcome_text = (
            "🤖 *Бот для Яндекс.Диска*\n\n"
            "🔐 *Авторизация:*\n"
            "1️⃣ Нажмите кнопку ниже\n"
            "2️⃣ Войдите в аккаунт\n"
            "3️⃣ Скопируйте код из URL\n"
            "4️⃣ Отправьте код сюда"
        )
        
        auth_button = InlineKeyboardButton(text="🔑 Авторизоваться", url=get_auth_url())
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[auth_button]])
        
        await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")


@dp.message(Command("list"))
async def cmd_list(message: Message):
    user_id = message.from_user.id
    if user_id not in user_tokens:
        await message.answer("⚠️ Сначала авторизуйтесь: /start")
        return
    await show_folder(message, get_user_folder_path(user_id))


@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    user_id = message.from_user.id
    
    if user_id in user_tokens:
        del user_tokens[user_id]
        if user_id in auth_states:
            del auth_states[user_id]
        if user_id in monitoring_tasks:
            monitoring_tasks[user_id].cancel()
        await message.answer("✅ Вы вышли из аккаунта.", reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.answer("Вы не были авторизованы.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📚 *Команды и кнопки:*\n\n"
        "📁 Показать папку - просмотр настроенной папки\n"
        "📂 Показать корень - просмотр корня\n"
        "⚙️ Настройки - изменение параметров\n"
        "🔍 Тест сейчас - ручная проверка\n"
        "🚪 Выйти - деавторизация\n\n"
        f"📁 *Текущая папка:* `{get_user_folder_path(message.from_user.id)}`"
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())


# Обработка кода авторизации
@dp.message(F.text & ~F.text.startswith("/") & ~F.text.startswith("◀️"))
async def handle_text_input(message: Message):
    text = message.text.strip()
    user_id = message.from_user.id
    
    # Ожидание пути к папке
    if auth_states.get(user_id) == "waiting_folder_path":
        set_user_folder_path(user_id, text)
        del auth_states[user_id]
        await message.answer(f"✅ Путь изменен на: `{text}`", parse_mode="Markdown", reply_markup=get_main_keyboard())
        return
    
    # Ожидание интервала
    if auth_states.get(user_id) == "waiting_interval":
        try:
            minutes = int(text)
            if minutes < 1:
                await message.answer("❌ Интервал должен быть больше 0")
                return
            set_user_interval(user_id, minutes)
            del auth_states[user_id]
            await message.answer(f"✅ Интервал изменен на {minutes} мин.", reply_markup=get_main_keyboard())
            
            # Перезапускаем мониторинг, если автопроверка включена
            if user_id in user_tokens and get_auto_check_enabled(user_id):
                await start_monitoring(user_id)
        except ValueError:
            await message.answer("❌ Введите целое число (минуты)")
        return
    
    # Ожидание авторизации
    if auth_states.get(user_id) is True:
        status_msg = await message.answer("🔄 Авторизация...")
        
        token = await get_access_token(text)
        
        if token:
            user_tokens[user_id] = token
            auth_states[user_id] = False
            
            # Инициализируем настройки
            if user_id not in user_settings:
                user_settings[user_id] = {}
            if "folder_path" not in user_settings[user_id]:
                user_settings[user_id]["folder_path"] = DEFAULT_YANDEX_FOLDER_PATH
            if "check_interval_minutes" not in user_settings[user_id]:
                user_settings[user_id]["check_interval_minutes"] = 60
            if "auto_check_enabled" not in user_settings[user_id]:
                user_settings[user_id]["auto_check_enabled"] = True
            save_settings()
            
            await status_msg.delete()
            await message.answer(
                "✅ *Авторизация успешна!*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            
            # Запускаем мониторинг, если автопроверка включена
            if get_auto_check_enabled(user_id):
                await start_monitoring(user_id)
            
            # Показываем папку
            await show_folder(message, get_user_folder_path(user_id))
        else:
            await status_msg.edit_text("❌ *Ошибка авторизации*\n\nПроверьте код и попробуйте снова: /start", parse_mode="Markdown")


# Обработка загруженного файла для импорта
@dp.message(F.document)
async def handle_import_file(message: Message):
    user_id = message.from_user.id
    if auth_states.get(user_id) != "waiting_import_file":
        return
    
    file = message.document
    if not file.file_name.endswith('.json'):
        await message.answer("❌ Пожалуйста, отправьте JSON файл")
        return
    
    file_id = file.file_id
    file_obj = await bot.get_file(file_id)
    file_path = file_obj.file_path
    
    # Скачиваем файл
    file_data = await bot.download_file(file_path)
    content = file_data.read().decode('utf-8')
    
    if import_settings(user_id, content):
        del auth_states[user_id]
        await message.answer("✅ Настройки успешно импортированы!", reply_markup=get_main_keyboard())
        
        # Перезапускаем мониторинг, если автопроверка включена
        if user_id in user_tokens and get_auto_check_enabled(user_id):
            await start_monitoring(user_id)
        elif user_id in user_tokens and not get_auto_check_enabled(user_id):
            # Если автопроверка выключена, останавливаем мониторинг
            if user_id in monitoring_tasks and not monitoring_tasks[user_id].done():
                monitoring_tasks[user_id].cancel()
    else:
        await message.answer("❌ Ошибка импорта настроек. Проверьте формат файла.")


# Callback обработчики
@dp.callback_query(F.data.startswith("folder:"))
async def handle_folder_callback(callback: CallbackQuery):
    folder_path = callback.data[7:]
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла", show_alert=True)
        return
    
    await callback.answer()
    await show_folder(callback.message, folder_path)
    try:
        await callback.message.delete()
    except:
        pass


@dp.callback_query(F.data.startswith("file:"))
async def handle_file_callback(callback: CallbackQuery):
    file_path = callback.data[5:]
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла", show_alert=True)
        return
    
    await callback.answer("⏬ Скачиваю...")
    status_msg = await callback.message.answer("📥 Загрузка файла...")
    
    try:
        disk_api = YandexDiskAPI(user_tokens[user_id])
        download_url = await disk_api.get_download_link(file_path)
        
        if not download_url:
            await status_msg.edit_text("❌ Не удалось получить ссылку")
            return
        
        file_data = await disk_api.download_file(download_url)
        
        if not file_data:
            await status_msg.edit_text("❌ Ошибка при скачивании")
            return
        
        file_name = file_path.split("/")[-1]
        await status_msg.delete()
        await callback.message.answer_document(
            types.BufferedInputFile(file_data, filename=file_name),
            caption=f"✅ {file_name}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")


@dp.callback_query(F.data.startswith("refresh:"))
async def handle_refresh_callback(callback: CallbackQuery):
    folder_path = callback.data[8:]
    user_id = callback.from_user.id
    
    if user_id not in user_tokens:
        await callback.answer("⚠️ Сессия истекла", show_alert=True)
        return
    
    await callback.answer("🔄 Обновляю...")
    await show_folder(callback.message, folder_path)
    try:
        await callback.message.delete()
    except:
        pass


async def main():
    """Запуск бота"""
    load_settings()
    logger.info("🚀 Запуск бота...")
    logger.info(f"📁 Папка по умолчанию: {DEFAULT_YANDEX_FOLDER_PATH}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())