from config import RESPONSES_EXPORT_FILE
from db import create_tables, export_responses


if __name__ == "__main__":
    create_tables()
    export_responses()
    print(f"Responses exported to {RESPONSES_EXPORT_FILE}")
