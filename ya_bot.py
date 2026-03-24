import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN, YANDEX_DISK_FOLDER, YANDEX_DISK_PASSWORD

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот для работы с Яндекс.Диском.\n"
        "Используй команду /list_files для просмотра файлов в папке."
    )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение списка файлов из Яндекс.Диска"""
    await update.message.reply_text("⏳ Получаю список файлов...")
    
    try:
        files = get_yandex_disk_files(YANDEX_DISK_FOLDER, YANDEX_DISK_PASSWORD)
        
        if files:
            response = "📁 *Файлы в папке:*\n\n"
            for i, file in enumerate(files, 1):
                response += f"{i}. {file}\n"
            
            await update.message.reply_text(response, parse_mode="Markdown")
        else:
            await update.message.reply_text("📂 Папка пуста или не удалось получить доступ.")
            
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка при получении списка файлов.")

def get_yandex_disk_files(folder_url: str, password: str) -> list:
    """
    Получение списка файлов из публичной папки Яндекс.Диска
    
    Примечание: Для полноценной работы с Яндекс.Диском
    рекомендуется использовать официальный API Yandex.Disk
    """
    try:
        session = requests.Session()
        
        # Получаем страницу папки
        response = session.get(folder_url)
        response.raise_for_status()
        
        # Парсим HTML (упрощенный вариант)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Ищем ссылки на файлы (селекторы могут меняться)
        file_elements = soup.find_all('a', class_='resources-item__name')
        
        files = []
        for element in file_elements:
            file_name = element.get_text(strip=True)
            if file_name:
                files.append(file_name)
        
        return files
        
    except Exception as e:
        logging.error(f"Ошибка при парсинге Яндекс.Диска: {e}")
        return []

async def update_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление кода бота (требует прав администратора)"""
    user_id = update.effective_user.id
    # Здесь можно проверить, является ли пользователь администратором
    # ADMIN_IDS = [123456789]  # ID админов
    
    await update.message.reply_text(
        "🔄 Функция обновления кода.\n"
        "Для реализации требуется:\n"
        "1. Git репозиторий\n"
        "2. Webhook для автоматического обновления\n"
        "3. Перезапуск бота"
    )

def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Токен бота не найден!")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list_files", list_files))
    application.add_handler(CommandHandler("update", update_code))
    
    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()