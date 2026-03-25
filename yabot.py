import os
import logging
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токены из .env
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
YANDEX_TOKEN = os.getenv('YANDEX_DISK_TOKEN')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

# Базовый URL для API Яндекс.Диска
YANDEX_API_URL = 'https://cloud-api.yandex.net/v1/disk'

class YandexDiskAPI:
    """Класс для работы с API Яндекс.Диска"""
    
    def __init__(self, token):
        self.token = token
        self.headers = {
            'Authorization': f'OAuth {token}',
            'Content-Type': 'application/json'
        }
    
    def get_folder_contents(self, folder_id=None):
        """Получить содержимое папки"""
        try:
            # Получаем информацию о ресурсах в папке
            params = {
                'path': f'/disk:/{folder_id}' if folder_id else '/disk:/'
            }
            response = requests.get(
                f'{YANDEX_API_URL}/resources',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('_embedded', {}).get('items', [])
                return items
            else:
                logger.error(f"Ошибка получения папки: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Исключение при получении папки: {e}")
            return None
    
    def get_file_content(self, file_path):
        """Получить содержимое файла"""
        try:
            # Получаем ссылку для скачивания
            params = {'path': file_path}
            response = requests.get(
                f'{YANDEX_API_URL}/resources/download',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                download_url = response.json().get('href')
                # Скачиваем файл
                file_response = requests.get(download_url)
                if file_response.status_code == 200:
                    return file_response.text, file_response.content
            return None, None
        except Exception as e:
            logger.error(f"Ошибка получения файла: {e}")
            return None, None
    
    def upload_file(self, file_content, file_path):
        """Загрузить файл на Яндекс.Диск"""
        try:
            # Получаем ссылку для загрузки
            params = {
                'path': file_path,
                'overwrite': 'true'
            }
            response = requests.get(
                f'{YANDEX_API_URL}/resources/upload',
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                upload_url = response.json().get('href')
                # Загружаем файл
                upload_response = requests.put(upload_url, files={'file': file_content})
                if upload_response.status_code == 201:
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка загрузки файла: {e}")
            return False

# Инициализируем API Яндекс.Диска
yandex_disk = YandexDiskAPI(YANDEX_TOKEN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_text = (
        "🤖 *Привет! Я бот для работы с Яндекс.Диском*\n\n"
        "Я умею:\n"
        "📁 Показывать список файлов в папке\n"
        "🔄 Обновлять код из папки Яндекс.Диска\n\n"
        "Используй команду /files чтобы увидеть файлы\n"
        "Или нажми на кнопку ниже"
    )
    
    keyboard = [
        [InlineKeyboardButton("📁 Показать файлы", callback_data='show_files')],
        [InlineKeyboardButton("🔄 Обновить все файлы", callback_data='update_all')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def show_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список файлов в папке Яндекс.Диска"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    # Отправляем сообщение о загрузке
    loading_msg = await message.reply_text("🔍 Загружаю список файлов...")
    
    # Получаем содержимое папки
    files = yandex_disk.get_folder_contents(YANDEX_FOLDER_ID)
    
    if files is None:
        await loading_msg.edit_text("❌ Ошибка подключения к Яндекс.Диску. Проверьте токен доступа.")
        return
    
    if not files:
        await loading_msg.edit_text("📂 Папка пуста. Нет файлов для отображения.")
        return
    
    # Формируем список файлов
    file_list = "*📁 Файлы в папке:*\n\n"
    for i, file in enumerate(files, 1):
        file_name = file.get('name', 'Без имени')
        file_size = file.get('size', 0)
        file_type = file.get('mime_type', 'unknown')
        
        # Конвертируем размер в читаемый формат
        if file_size < 1024:
            size_str = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"
        
        file_list += f"{i}. `{file_name}`\n"
        file_list += f"   📏 {size_str} | 📄 {file_type}\n\n"
    
    # Создаем кнопки для каждого файла
    keyboard = []
    for file in files:
        file_name = file.get('name')
        keyboard.append([InlineKeyboardButton(
            f"📄 {file_name}",
            callback_data=f"download_{file_name}"
        )])
    
    # Добавляем кнопку обновления всех файлов
    keyboard.append([InlineKeyboardButton("🔄 Обновить все файлы", callback_data='update_all')])
    keyboard.append([InlineKeyboardButton("🏠 На главную", callback_data='back_to_start')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await loading_msg.edit_text(
        file_list,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скачать конкретный файл"""
    query = update.callback_query
    await query.answer()
    
    file_name = query.data.replace('download_', '')
    file_path = f"{YANDEX_FOLDER_ID}/{file_name}" if YANDEX_FOLDER_ID else file_name
    
    await query.edit_message_text(f"📥 Скачиваю файл {file_name}...")
    
    # Получаем содержимое файла
    text_content, binary_content = yandex_disk.get_file_content(file_path)
    
    if text_content is None and binary_content is None:
        await query.edit_message_text(f"❌ Не удалось скачать файл {file_name}")
        return
    
    # Определяем тип файла и отправляем
    if file_name.endswith('.txt') or file_name.endswith('.py') or file_name.endswith('.json'):
        # Текстовый файл - отправляем как документ
        from io import BytesIO
        file_buffer = BytesIO(binary_content)
        file_buffer.name = file_name
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_buffer,
            caption=f"✅ Файл {file_name} успешно загружен"
        )
        await query.edit_message_text(f"✅ Файл {file_name} успешно скачан!")
    else:
        # Бинарный файл
        from io import BytesIO
        file_buffer = BytesIO(binary_content)
        file_buffer.name = file_name
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=file_buffer,
            caption=f"✅ Файл {file_name} успешно загружен"
        )
        await query.edit_message_text(f"✅ Файл {file_name} успешно скачан!")

async def update_all_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновить все файлы из папки Яндекс.Диска"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("🔄 Начинаю обновление файлов...")
        message = query.message
    else:
        message = update.message
        await message.reply_text("🔄 Начинаю обновление файлов...")
    
    # Получаем список файлов
    files = yandex_disk.get_folder_contents(YANDEX_FOLDER_ID)
    
    if files is None:
        await message.reply_text("❌ Ошибка подключения к Яндекс.Диску")
        return
    
    if not files:
        await message.reply_text("📂 Папка пуста. Нечего обновлять.")
        return
    
    updated_files = []
    failed_files = []
    
    for file in files:
        file_name = file.get('name')
        file_path = f"{YANDEX_FOLDER_ID}/{file_name}" if YANDEX_FOLDER_ID else file_name
        
        # Скачиваем файл
        text_content, binary_content = yandex_disk.get_file_content(file_path)
        
        if text_content is None and binary_content is None:
            failed_files.append(file_name)
            continue
        
        # Сохраняем файл локально
        try:
            with open(file_name, 'wb') as f:
                f.write(binary_content)
            updated_files.append(file_name)
        except Exception as e:
            logger.error(f"Ошибка сохранения файла {file_name}: {e}")
            failed_files.append(file_name)
    
    # Формируем отчет
    result_text = "✅ *Обновление завершено!*\n\n"
    
    if updated_files:
        result_text += "*Успешно обновлены:*\n"
        for file in updated_files:
            result_text += f"✓ `{file}`\n"
    
    if failed_files:
        result_text += "\n*Не удалось обновить:*\n"
        for file in failed_files:
            result_text += f"✗ `{file}`\n"
    
    # Создаем кнопки для навигации
    keyboard = [
        [InlineKeyboardButton("📁 Показать файлы", callback_data='show_files')],
        [InlineKeyboardButton("🏠 На главную", callback_data='back_to_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(
            result_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await message.reply_text(
            result_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться на главный экран"""
    query = update.callback_query
    await query.answer()
    
    welcome_text = (
        "🤖 *Главное меню*\n\n"
        "Выберите действие:"
    )
    
    keyboard = [
        [InlineKeyboardButton("📁 Показать файлы", callback_data='show_files')],
        [InlineKeyboardButton("🔄 Обновить все файлы", callback_data='update_all')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "*📚 Доступные команды:*\n\n"
        "/start - Начать работу с ботом\n"
        "/files - Показать список файлов\n"
        "/update - Обновить все файлы\n"
        "/help - Показать эту справку\n\n"
        "*💡 Как это работает:*\n"
        "Бот подключается к вашей папке на Яндекс.Диске и позволяет:\n"
        "• Просматривать список файлов\n"
        "• Скачивать отдельные файлы\n"
        "• Обновлять все файлы локально"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /files"""
    await show_files(update, context)

async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /update"""
    await update_all_files(update, context)

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("update", update_command))
    
    # Регистрируем обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(show_files, pattern='^show_files$'))
    application.add_handler(CallbackQueryHandler(update_all_files, pattern='^update_all$'))
    application.add_handler(CallbackQueryHandler(back_to_start, pattern='^back_to_start$'))
    application.add_handler(CallbackQueryHandler(download_file, pattern='^download_'))
    
    # Запускаем бота
    print("🤖 Бот запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()