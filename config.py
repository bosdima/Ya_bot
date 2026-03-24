import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_DISK_FOLDER = os.getenv("YANDEX_DISK_FOLDER")
YANDEX_DISK_PASSWORD = os.getenv("YANDEX_DISK_PASSWORD")

if not TELEGRAM_BOT_TOKEN:
    print("⚠️  ВНИМАНИЕ: TELEGRAM_BOT_TOKEN не найден!")
    print("Создайте файл .env с переменной TELEGRAM_BOT_TOKEN")