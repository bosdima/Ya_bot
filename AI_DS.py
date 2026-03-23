import asyncio
import requests
import os
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загружаем переменные окружения из файла .env
load_dotenv()

# Получаем токены из переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# URL для DeepSeek API
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

async def check_deepseek_access() -> tuple[bool, str]:
    """Проверка доступа к DeepSeek API"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            return True, "✅ Доступ к DeepSeek API успешно подтверждён"
        else:
            return False, f"❌ Ошибка доступа к DeepSeek API: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"❌ Ошибка подключения к DeepSeek API: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я бот для работы с DeepSeek API.\n"
        "Просто отправь мне любое сообщение, и я передам его в DeepSeek.\n"
        "Используй /status для проверки статуса API"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса DeepSeek API"""
    status_msg = await update.message.reply_text("🔄 Проверяю доступ к DeepSeek API...")
    is_ok, message = await check_deepseek_access()
    await status_msg.edit_text(message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений пользователя"""
    user_message = update.message.text
    thinking_msg = await update.message.reply_text("🤔 Отправляю запрос в DeepSeek...")
    
    # Подготовка запроса к DeepSeek API
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        # Отправляем запрос к DeepSeek API
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            reply_text = result['choices'][0]['message']['content']
            # Разбиваем длинные сообщения на части
            if len(reply_text) > 4096:
                for i in range(0, len(reply_text), 4096):
                    await update.message.reply_text(reply_text[i:i+4096])
            else:
                await update.message.reply_text(reply_text)
        else:
            error_msg = f"❌ Ошибка DeepSeek API: {response.status_code}\n{response.text}"
            await update.message.reply_text(error_msg)
            
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Превышено время ожидания ответа от DeepSeek API")
    except Exception as e:
        await update.message.reply_text(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await thinking_msg.delete()

async def on_startup():
    """Действия при запуске бота"""
    print("🚀 Запуск бота...")
    
    # Проверяем доступ к DeepSeek API
    is_ok, message = await check_deepseek_access()
    print(message)
    
    # Отправляем сообщение в Telegram о статусе
    if TELEGRAM_TOKEN:
        bot = Bot(token=TELEGRAM_TOKEN)
        # Здесь можно отправить сообщение администратору, но нужно знать его ID
        # Вместо этого выводим в консоль и создадим отдельную функцию
    
    return is_ok

async def post_startup_cleanup(application: Application):
    """Очистка после запуска"""
    await asyncio.sleep(2)
    print("✅ Бот готов к работе!")
    print("📝 Отправляйте сообщения для получения ответов от DeepSeek")

def main():
    """Основная функция запуска бота"""
    if not TELEGRAM_TOKEN:
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не найден в .env файле")
        return
    
    if not DEEPSEEK_API_KEY:
        print("❌ Ошибка: DEEPSEEK_API_KEY не найден в .env файле")
        return
    
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем проверку при старте
    async def startup_check():
        is_ok, message = await check_deepseek_access()
        print(f"\n{'='*50}")
        print(f"🔍 ПРОВЕРКА ПРИ ЗАПУСКЕ:")
        print(message)
        if is_ok:
            print("✅ Бот готов к работе! Отправляйте сообщения для запросов к DeepSeek")
        else:
            print("⚠️ Бот запущен, но DeepSeek API недоступен. Используйте /status для проверки")
        print(f"{'='*50}\n")
    
    # Запускаем проверку в отдельном событии
    async def startup_wrapper():
        await startup_check()
    
    # Выполняем проверку
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(startup_wrapper())
        loop.close()
    except Exception as e:
        print(f"Ошибка при проверке: {e}")
    
    print("🤖 Бот запускается...")
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()