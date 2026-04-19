import os
import sqlite3
from typing import Any

import pandas as pd

from config import BASE_DIR, DB_NAME
from db import create_tables

EXCEL_FILE = os.path.join(BASE_DIR, "vacancies.xlsx")
REQUIRED_COLUMNS = {"title", "address", "latitude", "longitude"}


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def _validate_columns(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing required Excel columns: {missing_list}")


def import_vacancies() -> None:
    create_tables()

    df = pd.read_excel(EXCEL_FILE)
    _validate_columns(df)
    df = df.where(pd.notnull(df), None)

    imported = 0
    updated = 0
    created = 0

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        for _, row in df.iterrows():
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            title = str(row["title"]).strip()
            address = str(row["address"]).strip()

            data = {
                "project": _clean_value(row.get("project")),
                "title": title,
                "description": _clean_value(row.get("description")),
                "description_2": _clean_value(row.get("description_2")),
                "address": address,
                "maps": _clean_value(row.get("maps")),
                "payment": _clean_value(row.get("payment")),
                "latitude": latitude,
                "longitude": longitude,
            }

            existing = conn.execute(
                """
                SELECT id FROM vacancies
                WHERE title = ?
                  AND address = ?
                  AND latitude = ?
                  AND longitude = ?
                """,
                (title, address, latitude, longitude),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE vacancies
                    SET project = ?,
                        description = ?,
                        description_2 = ?,
                        maps = ?,
                        payment = ?
                    WHERE id = ?
                    """,
                    (
                        data["project"],
                        data["description"],
                        data["description_2"],
                        data["maps"],
                        data["payment"],
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO vacancies (
                        project,
                        title,
                        description,
                        description_2,
                        address,
                        maps,
                        payment,
                        latitude,
                        longitude
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["project"],
                        data["title"],
                        data["description"],
                        data["description_2"],
                        data["address"],
                        data["maps"],
                        data["payment"],
                        data["latitude"],
                        data["longitude"],
                    ),
                )
                created += 1

            imported += 1

    print(f"Imported {imported} vacancies: {created} created, {updated} updated.")


if __name__ == "__main__":
    import_vacancies()
