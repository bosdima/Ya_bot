import logging
import requests
import re
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
import httpx

# ===== ВСТАВЬТЕ НОВЫЙ ТОКЕН ЗДЕСЬ =====
# Получите новый токен у @BotFather
TELEGRAM_BOT_TOKEN = "8737491152:AAEB7GRYPfSP6cCMOoOgaKbaqnym99uzO1M"  # Замените на новый токен
YANDEX_DISK_FOLDER = "https://disk.yandex.ru/d/SXOb7oeWgbqk3w"
YANDEX_DISK_PASSWORD = "17092003"
# ======================================

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот для работы с Яндекс.Диском.\n\n"
        "📁 *Доступные команды:*\n"
        "/list_files - показать файлы в папке\n"
        "/update - обновить код бота\n"
        "/help - помощь",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    await update.message.reply_text(
        "🤖 *Помощь по боту*\n\n"
        "📁 *list_files* - показывает список файлов из папки Яндекс.Диска\n"
        "🔄 *update* - информация об обновлении бота\n\n"
        "📂 *Папка:* Защищена паролем\n"
        "🔑 *Пароль:* 17092003\n\n"
        "⚠️ Бот не может автоматически ввести пароль. "
        "Сделайте папку публичной для автоматического доступа.",
        parse_mode="Markdown"
    )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение списка файлов из Яндекс.Диска"""
    message = await update.message.reply_text("⏳ Получаю список файлов...")
    
    try:
        # Создаем сессию
        session = requests.Session()
        
        # Добавляем заголовки для имитации браузера
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Получаем страницу папки
        response = session.get(YANDEX_DISK_FOLDER, headers=headers, timeout=15)
        response.raise_for_status()
        
        html_content = response.text
        
        # Парсим HTML для поиска файлов
        files = []
        
        # Паттерны для поиска файлов в Яндекс.Диске
        patterns = [
            r'class="resources-item__name"[^>]*>([^<]+)</a>',
            r'<a[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</a>',
            r'data-filename="([^"]+)"',
            r'<div[^>]*title="([^"]+)"[^>]*>',
            r'<span[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</span>',
        ]
        
        for pattern in patterns:
            found = re.findall(pattern, html_content)
            if found:
                files.extend(found)
        
        # Фильтруем результаты
        files = [f.strip() for f in files if f.strip() and len(f.strip()) > 1]
        files = [f for f in files if not any(x in f.lower() for x in ['папка', 'folder', '..', 'parent'])]
        files = list(dict.fromkeys(files))  # Удаляем дубликаты
        
        if files:
            response_text = "📁 *Файлы в папке:*\n\n"
            for i, file in enumerate(files[:20], 1):
                # Обрезаем длинные имена
                if len(file) > 50:
                    file = file[:47] + "..."
                response_text += f"{i}. {file}\n"
            
            if len(files) > 20:
                response_text += f"\n... и еще {len(files) - 20} файлов"
            
            await message.edit_text(response_text, parse_mode="Markdown")
        else:
            # Если не нашли файлы
            await message.edit_text(
                "📂 *Папка требует авторизации*\n\n"
                "К сожалению, бот не может автоматически ввести пароль.\n\n"
                "🔑 *Пароль:* `17092003`\n\n"
                "💡 *Решение:*\n"
                "1. Сделайте папку публичной в настройках Яндекс.Диска\n"
                "2. Или используйте прямые ссылки на файлы\n\n"
                "Или откройте папку в браузере:\n"
                f"{YANDEX_DISK_FOLDER}",
                parse_mode="Markdown"
            )
            
    except requests.exceptions.Timeout:
        await message.edit_text("⏰ Таймаут подключения. Попробуйте позже.")
    except requests.exceptions.ConnectionError:
        await message.edit_text("🌐 Ошибка подключения к Яндекс.Диску.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса: {e}")
        await message.edit_text("❌ Ошибка при обращении к Яндекс.Диску.")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.edit_text(f"❌ Произошла ошибка: {str(e)[:100]}")

async def update_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для обновления кода"""
    await update.message.reply_text(
        "🔄 *Обновление кода*\n\n"
        "Для обновления бота:\n"
        "1. Отредактируйте файл `ya_bot.py`\n"
        "2. Перезапустите бота командой:\n"
        "   `Ctrl+C` затем `python ya_bot.py`\n\n"
        "📦 *Текущая версия:* v1.1\n"
        "👤 *Разработчик:* @your_username",
        parse_mode="Markdown"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    
    if update and update.effective_message:
        error_message = "⚠️ Произошла ошибка. Попробуйте позже."
        await update.effective_message.reply_text(error_message)

def main():
    """Запуск бота"""
    print("=" * 50)
    print("🤖 ЗАПУСК БОТА")
    print("=" * 50)
    
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "ВАШ_НОВЫЙ_ТОКЕН_ЗДЕСЬ":
        print("❌ ОШИБКА: Токен бота не настроен!")
        print("\n📝 Инструкция:")
        print("1. Найдите @BotFather в Telegram")
        print("2. Отправьте команду /newbot")
        print("3. Создайте нового бота")
        print("4. Скопируйте полученный токен")
        print("5. Вставьте токен в переменную TELEGRAM_BOT_TOKEN")
        return
    
    try:
        # Настраиваем запрос с таймаутами
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0,
            client=httpx.Client(timeout=30.0)
        )
        
        # Создаем приложение
        application = Application.builder()\
            .token(TELEGRAM_BOT_TOKEN)\
            .request(request)\
            .build()
        
        # Регистрируем команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("list_files", list_files))
        application.add_handler(CommandHandler("update", update_code))
        
        # Добавляем обработчик ошибок
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно инициализирован")
        print(f"📁 Папка Яндекс.Диска: {YANDEX_DISK_FOLDER}")
        print("💡 Доступные команды: /start, /list_files, /update, /help")
        print("🔄 Бот запущен и ожидает сообщения...")
        print("=" * 50)
        
        # Запускаем бота
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        print("\nВозможные решения:")
        print("1. Проверьте подключение к интернету")
        print("2. Убедитесь, что токен правильный")
        print("3. Попробуйте перезапустить бота")

if __name__ == "__main__":
    main()
