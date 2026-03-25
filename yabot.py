import os
import requests
import asyncio
from datetime import datetime
from typing import Optional, List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI')
YANDEX_FOLDER_PATH = os.getenv('YANDEX_FOLDER_PATH', '/')

# Хранилище для OAuth токенов пользователей
user_tokens = {}

# Яндекс.Диск API endpoints
YANDEX_API_BASE = 'https://cloud-api.yandex.net/v1/disk'
YANDEX_OAUTH_TOKEN_URL = 'https://oauth.yandex.ru/token'


class YandexDiskClient:
    """Клиент для работы с Яндекс.Диском"""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'OAuth {access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_files_list(self, path: str = '/') -> Optional[List[Dict]]:
        """Получение списка файлов в папке"""
        try:
            params = {
                'path': path,
                'fields': '_embedded.items.name,_embedded.items.type,_embedded.items.path,_embedded.items.size,_embedded.items.modified',
                'limit': 100
            }
            
            response = requests.get(
                f'{YANDEX_API_BASE}/resources',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('_embedded', {}).get('items', [])
                return items
            else:
                print(f"Error getting files: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"Exception in get_files_list: {e}")
            return None
    
    def get_file_info(self, path: str) -> Optional[Dict]:
        """Получение информации о файле"""
        try:
            params = {
                'path': path,
                'fields': 'name,type,size,modified,mime_type'
            }
            
            response = requests.get(
                f'{YANDEX_API_BASE}/resources',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except Exception as e:
            print(f"Exception in get_file_info: {e}")
            return None
    
    def download_file(self, path: str) -> Optional[bytes]:
        """Скачивание файла с Яндекс.Диска"""
        try:
            # Получаем ссылку для скачивания
            params = {'path': path}
            response = requests.get(
                f'{YANDEX_API_BASE}/resources/download',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                download_url = response.json().get('href')
                if download_url:
                    # Скачиваем файл
                    file_response = requests.get(download_url)
                    if file_response.status_code == 200:
                        return file_response.content
            
            return None
            
        except Exception as e:
            print(f"Exception in download_file: {e}")
            return None


def get_oauth_token(auth_code: str) -> Optional[str]:
    """Получение OAuth токена по коду авторизации"""
    try:
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'client_id': YANDEX_CLIENT_ID,
            'client_secret': YANDEX_CLIENT_SECRET,
            'redirect_uri': YANDEX_REDIRECT_URI
        }
        
        response = requests.post(YANDEX_OAUTH_TOKEN_URL, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            return token_data.get('access_token')
        else:
            print(f"Error getting token: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"Exception in get_oauth_token: {e}")
        return None


def get_auth_url() -> str:
    """Получение URL для авторизации на Яндекс.Диске"""
    auth_url = (
        f'https://oauth.yandex.ru/authorize'
        f'?response_type=code'
        f'&client_id={YANDEX_CLIENT_ID}'
        f'&redirect_uri={YANDEX_REDIRECT_URI}'
    )
    return auth_url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🔐 Авторизоваться в Яндекс.Диске", callback_data='auth')],
        [InlineKeyboardButton("📁 Показать файлы", callback_data='show_files')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {update.effective_user.first_name}!\n\n"
        f"Я бот для работы с Яндекс.Диском.\n"
        f"Чтобы начать, выполните авторизацию в Яндекс.Диске.\n\n"
        f"📌 Доступные команды:\n"
        f"/start - показать это меню\n"
        f"/auth - авторизоваться в Яндекс.Диске\n"
        f"/files - показать список файлов\n"
        f"/help - помощь",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
🤖 *Помощь по боту*

*Доступные команды:*
/start - Главное меню
/auth - Авторизация в Яндекс.Диске
/files - Показать список файлов
/help - Показать эту справку

*Как использовать:*
1. Нажмите /auth или кнопку "Авторизоваться"
2. Перейдите по ссылке и разрешите доступ
3. Скопируйте код из URL
4. Отправьте код боту в ответ на запрос
5. После авторизации используйте /files для просмотра файлов

*Примечание:* Бот работает с папкой: `{}`
    """.format(YANDEX_FOLDER_PATH)
    
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /auth - начало авторизации"""
    auth_url = get_auth_url()
    
    await update.message.reply_text(
        f"🔐 *Авторизация в Яндекс.Диске*\n\n"
        f"1. Перейдите по ссылке:\n{auth_url}\n\n"
        f"2. Разрешите доступ приложению\n"
        f"3. После авторизации вы будете перенаправлены на страницу с кодом\n"
        f"4. Скопируйте код из URL (часть после `?code=`)\n"
        f"5. Отправьте мне этот код\n\n"
        f"*Важно:* Код действителен только 5 минут!",
        parse_mode='Markdown'
    )
    
    # Устанавливаем состояние ожидания кода
    context.user_data['waiting_for_auth_code'] = True


async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка полученного кода авторизации"""
    if not context.user_data.get('waiting_for_auth_code'):
        return
    
    auth_code = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Показываем, что обрабатываем запрос
    processing_msg = await update.message.reply_text("🔄 Получаю токен доступа...")
    
    # Получаем токен
    token = get_oauth_token(auth_code)
    
    if token:
        user_tokens[user_id] = token
        context.user_data['waiting_for_auth_code'] = False
        
        await processing_msg.edit_text(
            "✅ *Авторизация успешна!*\n\n"
            "Теперь вы можете использовать команду /files для просмотра файлов на Яндекс.Диске.",
            parse_mode='Markdown'
        )
    else:
        await processing_msg.edit_text(
            "❌ *Ошибка авторизации*\n\n"
            "Не удалось получить токен доступа. Проверьте правильность кода и попробуйте снова.\n"
            "Используйте /auth для повторной авторизации.",
            parse_mode='Markdown'
        )


async def show_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список файлов в папке Яндекс.Диска"""
    user_id = update.effective_user.id
    
    # Проверяем, есть ли токен
    token = user_tokens.get(user_id)
    
    if not token:
        await update.message.reply_text(
            "❌ *Необходима авторизация*\n\n"
            "Пожалуйста, сначала выполните авторизацию в Яндекс.Диске с помощью команды /auth",
            parse_mode='Markdown'
        )
        return
    
    # Отправляем сообщение о загрузке
    loading_msg = await update.message.reply_text("📂 Загружаю список файлов...")
    
    # Создаем клиент Яндекс.Диска
    disk_client = YandexDiskClient(token)
    
    # Получаем список файлов
    files = disk_client.get_files_list(YANDEX_FOLDER_PATH)
    
    if files is None:
        await loading_msg.edit_text(
            "❌ *Ошибка*\n\n"
            "Не удалось получить список файлов. Возможно, токен истек.\n"
            "Попробуйте выполнить авторизацию заново: /auth",
            parse_mode='Markdown'
        )
        return
    
    if not files:
        await loading_msg.edit_text(
            f"📁 *Папка пуста*\n\n"
            f"В папке `{YANDEX_FOLDER_PATH}` нет файлов.",
            parse_mode='Markdown'
        )
        return
    
    # Форматируем вывод
    result_text = f"📁 *Файлы в папке `{YANDEX_FOLDER_PATH}`:*\n\n"
    
    # Создаем кнопки для каждого файла
    keyboard = []
    
    for i, item in enumerate(files[:20], 1):  # Показываем первые 20 файлов
        item_name = item.get('name', 'Без имени')
        item_type = item.get('type', 'file')
        item_size = item.get('size', 0)
        item_path = item.get('path', '')
        
        # Форматируем размер
        if item_type == 'dir':
            size_str = "📁 Папка"
            emoji = "📁"
        else:
            if item_size < 1024:
                size_str = f"{item_size} B"
            elif item_size < 1024 * 1024:
                size_str = f"{item_size / 1024:.1f} KB"
            else:
                size_str = f"{item_size / (1024 * 1024):.1f} MB"
            emoji = "📄"
        
        result_text += f"{i}. {emoji} *{item_name}*\n"
        result_text += f"   📊 {size_str}\n"
        
        # Добавляем кнопку для скачивания, если это файл
        if item_type == 'file':
            keyboard.append([
                InlineKeyboardButton(
                    f"📥 Скачать: {item_name[:30]}",
                    callback_data=f"download_{item_path}"
                )
            ])
    
    # Добавляем кнопку обновления
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data='refresh_files')])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await loading_msg.edit_text(
        result_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # Проверяем наличие токена
    token = user_tokens.get(user_id)
    
    if data == 'auth':
        await auth_command(update, context)
        
    elif data == 'show_files' or data == 'refresh_files':
        # Создаем фейковое сообщение для show_files
        class FakeMessage:
            def __init__(self, chat_id, reply_text_func):
                self.chat_id = chat_id
                self.reply_text_func = reply_text_func
            
            async def reply_text(self, text, **kwargs):
                await self.reply_text_func(text, **kwargs)
        
        fake_update = update
        fake_update.message = type('obj', (object,), {
            'reply_text': query.edit_message_text,
            'chat_id': query.message.chat_id
        })
        
        await show_files(fake_update, context)
        
    elif data.startswith('download_'):
        if not token:
            await query.edit_message_text(
                "❌ Необходима авторизация. Используйте /auth"
            )
            return
        
        # Получаем путь к файлу
        file_path = data.replace('download_', '')
        
        # Сообщение о загрузке
        await query.edit_message_text(f"📥 Скачиваю файл...")
        
        # Скачиваем файл
        disk_client = YandexDiskClient(token)
        file_content = disk_client.download_file(file_path)
        
        if file_content:
            # Получаем имя файла
            file_name = file_path.split('/')[-1]
            
            # Отправляем файл
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_content,
                filename=file_name,
                caption=f"✅ Файл успешно загружен: {file_name}"
            )
            
            # Возвращаем список файлов
            await show_files(update, context)
        else:
            await query.edit_message_text(
                "❌ Не удалось скачать файл. Возможно, файл был удален или токен истек.\n"
                "Попробуйте авторизоваться заново: /auth"
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    print(f"Error: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже."
        )


def main():
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(CommandHandler("files", show_files))
    
    # Обработчик текстовых сообщений (для кода авторизации)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    print("🚀 Бот запущен...")
    print(f"📁 Рабочая папка на Яндекс.Диске: {YANDEX_FOLDER_PATH}")
    application.run_polling()


if __name__ == '__main__':
    main()