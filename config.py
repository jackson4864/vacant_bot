import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SEARCH_RADIUS_KM = int(os.getenv("SEARCH_RADIUS_KM", "10"))
DB_NAME = os.path.join(BASE_DIR, "vacancies.db")

print("DEBUG TOKEN:", BOT_TOKEN)

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в файле .env")