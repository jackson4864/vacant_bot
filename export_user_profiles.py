from config import USER_PROFILES_EXPORT_FILE
from db import create_tables, export_user_profiles


if __name__ == "__main__":
    create_tables()
    export_user_profiles()
    print(f"User profiles exported to {USER_PROFILES_EXPORT_FILE}")
