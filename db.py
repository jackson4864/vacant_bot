import csv
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_NAME, RESPONSES_EXPORT_FILE


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name not in _column_names(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def create_tables() -> None:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT,
            region TEXT,
            city TEXT,
            title TEXT NOT NULL,
            description TEXT,
            description_2 TEXT,
            address TEXT NOT NULL,
            maps TEXT,
            payment TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            is_active INTEGER DEFAULT 1
        )
        """)

        _add_column_if_missing(conn, "vacancies", "project", "TEXT")
        _add_column_if_missing(conn, "vacancies", "region", "TEXT")
        _add_column_if_missing(conn, "vacancies", "city", "TEXT")
        _add_column_if_missing(conn, "vacancies", "description", "TEXT")
        _add_column_if_missing(conn, "vacancies", "description_2", "TEXT")
        _add_column_if_missing(conn, "vacancies", "maps", "TEXT")
        _add_column_if_missing(conn, "vacancies", "payment", "TEXT")
        _add_column_if_missing(conn, "vacancies", "is_active", "INTEGER DEFAULT 1")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vacancy_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            telegram_user_id INTEGER,
            username TEXT,
            chat_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vacancy_id) REFERENCES vacancies(id)
        )
        """)

        _add_column_if_missing(conn, "responses", "telegram_user_id", "INTEGER")
        _add_column_if_missing(conn, "responses", "username", "TEXT")
        _add_column_if_missing(conn, "responses", "chat_id", "INTEGER")

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_vacancies_region_city
        ON vacancies(region, city)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_vacancies_coordinates
        ON vacancies(latitude, longitude)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_responses_vacancy_id
        ON responses(vacancy_id)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_responses_telegram_user_id
        ON responses(telegram_user_id)
        """)

        conn.commit()


def seed_vacancies() -> None:
    with closing(get_connection()) as conn:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM vacancies").fetchone()["cnt"]
        if count > 0:
            return

        test_vacancies = [
            (
                "Техник",
                "Доставка шелфбанера",
                "улица Академика Северина, 11/1",
                55.620318,
                37.943902,
            ),
            (
                "Курьер",
                "Доставка заказов по району",
                "Москва, ул. Тверская, 1",
                55.757220,
                37.615560,
            ),
            (
                "Продавец-консультант",
                "Работа в магазине одежды",
                "Москва, ул. Арбат, 12",
                55.752023,
                37.592812,
            ),
        ]

        conn.executemany("""
        INSERT INTO vacancies (title, description, address, latitude, longitude)
        VALUES (?, ?, ?, ?, ?)
        """, test_vacancies)
        conn.commit()


def get_all_vacancies() -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM vacancies WHERE is_active = 1").fetchall()
    return [dict(row) for row in rows]


def get_vacancies_in_bounds(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM vacancies
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
              AND is_active = 1
            """,
            (min_lat, max_lat, min_lon, max_lon),
        ).fetchall()
    return [dict(row) for row in rows]


def get_vacancy_by_id(vacancy_id: int) -> Optional[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM vacancies WHERE id = ?",
            (vacancy_id,),
        ).fetchone()

    return dict(row) if row else None


def get_regions() -> List[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT region FROM vacancies
            WHERE region IS NOT NULL AND TRIM(region) != ''
              AND is_active = 1
            ORDER BY region
            """
        ).fetchall()
    return [row["region"] for row in rows]


def get_cities_by_region(region: str) -> List[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT city FROM vacancies
            WHERE region = ?
              AND city IS NOT NULL
              AND TRIM(city) != ''
              AND is_active = 1
            ORDER BY city
            """,
            (region,),
        ).fetchall()
    return [row["city"] for row in rows]


def get_vacancies_by_city(region: str, city: str) -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM vacancies
            WHERE region = ? AND city = ?
              AND is_active = 1
            ORDER BY project, title, address
            """,
            (region, city),
        ).fetchall()
    return [dict(row) for row in rows]


RESPONSE_EXPORT_FIELDS = [
    "created_at",
    "full_name",
    "phone",
    "vacancy_region",
    "vacancy_city",
    "vacancy_title",
    "vacancy_address",
    "telegram_user_id",
    "username",
    "chat_id",
]


def _response_export_rows(response_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        query = """
        SELECT
            responses.id,
            responses.created_at,
            responses.full_name,
            responses.phone,
            responses.telegram_user_id,
            responses.username,
            responses.chat_id,
            vacancies.title AS vacancy_title,
            vacancies.region AS vacancy_region,
            vacancies.city AS vacancy_city,
            vacancies.address AS vacancy_address
        FROM responses
        LEFT JOIN vacancies ON vacancies.id = responses.vacancy_id
        """
        params: tuple[Any, ...] = ()

        if response_id is not None:
            query += " WHERE responses.id = ?"
            params = (response_id,)

        query += " ORDER BY responses.created_at, responses.id"
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def _write_response_export(rows: List[Dict[str, Any]], append: bool) -> None:
    if not rows:
        return

    export_path = Path(RESPONSES_EXPORT_FILE)
    file_exists = export_path.exists() and export_path.stat().st_size > 0
    mode = "a" if append else "w"

    with export_path.open(mode, newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=RESPONSE_EXPORT_FIELDS,
            delimiter=";",
        )
        if not append or not file_exists:
            writer.writeheader()

        for row in rows:
            writer.writerow({field: row[field] for field in RESPONSE_EXPORT_FIELDS})


def append_response_export(response_id: int) -> None:
    rows = _response_export_rows(response_id)
    _write_response_export(rows, append=True)


def export_responses() -> None:
    rows = _response_export_rows()
    export_path = Path(RESPONSES_EXPORT_FILE)

    if not rows:
        with export_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=RESPONSE_EXPORT_FIELDS,
                delimiter=";",
            )
            writer.writeheader()
        return

    _write_response_export(rows, append=False)


def save_response(
    vacancy_id: int,
    full_name: str,
    phone: str,
    telegram_user_id: Optional[int] = None,
    username: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> None:
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO responses (
                vacancy_id,
                full_name,
                phone,
                telegram_user_id,
                username,
                chat_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, full_name, phone, telegram_user_id, username, chat_id),
        )
        response_id = cursor.lastrowid
        conn.commit()

    append_response_export(response_id)
