import sqlite3
from typing import List, Dict, Any, Optional
from config import DB_NAME


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vacancies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT,
        title TEXT NOT NULL,
        description TEXT,
        description_2 TEXT,
        address TEXT NOT NULL,
        maps TEXT,
        payment TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vacancy_id INTEGER NOT NULL,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (vacancy_id) REFERENCES vacancies(id)
    )
    """)

    conn.commit()
    conn.close()


def seed_vacancies() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    count = cursor.execute("SELECT COUNT(*) AS cnt FROM vacancies").fetchone()["cnt"]
    if count > 0:
        conn.close()
        return

    test_vacancies = [
        (
            "Техник",
            "Доставка шелфбанера",
            "улица Академика Северина, 11/1",
            55.620318,
            37.943902
        ),
        (
            "Курьер",
            "Доставка заказов по району",
            "Москва, ул. Тверская, 1",
            55.757220,
            37.615560
        ),
        (
            "Продавец-консультант",
            "Работа в магазине одежды",
            "Москва, ул. Арбат, 12",
            55.752023,
            37.592812
        )
    ]

    cursor.executemany("""
    INSERT INTO vacancies (title, description, address, latitude, longitude)
    VALUES (?, ?, ?, ?, ?)
    """, test_vacancies)

    conn.commit()
    conn.close()


def get_all_vacancies() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM vacancies").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_vacancy_by_id(vacancy_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM vacancies WHERE id = ?",
        (vacancy_id,)
    ).fetchone()
    conn.close()

    return dict(row) if row else None


def save_response(vacancy_id: int, full_name: str, phone: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO responses (vacancy_id, full_name, phone)
    VALUES (?, ?, ?)
    """, (vacancy_id, full_name, phone))

    conn.commit()
    conn.close()