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
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
SHEETDB_API_URL = os.getenv("SHEETDB_API_URL", "https://sheetdb.io/api/v1/gydose9dofxsj")
SHEETDB_RESPONSES_API_URL = os.getenv("SHEETDB_RESPONSES_API_URL", SHEETDB_API_URL)
SHEETDB_RESPONSES_SHEET_NAME = os.getenv("SHEETDB_RESPONSES_SHEET_NAME", "отклик")
SEARCH_RADIUS_KM = get_int_env("SEARCH_RADIUS_KM", 10)
DB_NAME = os.path.join(BASE_DIR, "vacancies.db")
RESPONSES_EXPORT_FILE = os.path.join(BASE_DIR, "responses.csv")
USER_PROFILES_EXPORT_FILE = os.path.join(BASE_DIR, "user_profiles.csv")
