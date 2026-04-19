import pandas as pd
import sqlite3
from config import DB_NAME

EXCEL_FILE = "vacancies.xlsx"


def import_vacancies():
    df = pd.read_excel(EXCEL_FILE)
    df = df.where(pd.notnull(df), None)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM vacancies")

    rows = []
    for _, row in df.iterrows():
        rows.append((
            row.get("project"),
            row["title"],
            row.get("description"),
            row.get("description_2"),
            row["address"],
            row.get("maps"),
            row.get("payment"),
            float(row["latitude"]),
            float(row["longitude"]),
        ))

    cursor.executemany("""
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
    """, rows)

    conn.commit()
    conn.close()

    print(f"Импортировано: {len(rows)} вакансий")


if __name__ == "__main__":
    import_vacancies()