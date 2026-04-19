import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH)


def get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


BOT_TOKEN = os.getenv("BOT_TOKEN")
SEARCH_RADIUS_KM = get_int_env("SEARCH_RADIUS_KM", 10)
DB_NAME = os.path.join(BASE_DIR, "vacancies.db")
RESPONSES_EXPORT_FILE = os.path.join(BASE_DIR, "responses.csv")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
