from typing import Optional

import requests
from requests import RequestException

from config import (
    SHEETDB_API_URL,
    SHEETDB_RESPONSES_API_URL,
    SHEETDB_RESPONSES_SHEET_NAME,
)

API_URL = SHEETDB_API_URL


def _get_value(row: dict, *names: str):
    for name in names:
        if name in row:
            return row.get(name)

    normalized_names = {name.lower(): name for name in names}
    for key, value in row.items():
        if str(key).strip().lower() in normalized_names:
            return value

    return None


def _normalize_vacancy(vacancy):
    normalized = dict(vacancy)

    field_aliases = {
        "vacancy_id": ("vacancy_id", "id", "external_id"),
        "project": ("project",),
        "region": ("region",),
        "city": ("city",),
        "title": ("title",),
        "description": ("description",),
        "description_2": ("description_2", "description 2"),
        "address": ("address",),
        "maps": ("maps", "map", "карта"),
        "payment": ("payment", "salary", "оплата"),
    }

    for field, aliases in field_aliases.items():
        value = _get_value(vacancy, field, *aliases)
        normalized[field] = str(value).strip() if value is not None else ""

    if not normalized["title"]:
        return None

    latitude = _get_value(vacancy, "latitude", "lat", "широта")
    longitude = _get_value(vacancy, "longitude", "lon", "lng", "долгота")

    try:
        normalized["latitude"] = float(latitude) if latitude not in (None, "") else 0.0
        normalized["longitude"] = float(longitude) if longitude not in (None, "") else 0.0
    except (TypeError, ValueError):
        normalized["latitude"] = 0.0
        normalized["longitude"] = 0.0

    return normalized


def get_vacancies():
    try:
        response = requests.get(API_URL, timeout=30)
    except RequestException:
        return []

    if response.status_code != 200:
        return []

    data = response.json()

    valid_vacancies = []

    for vacancy in data:
        normalized = _normalize_vacancy(vacancy)
        if normalized:
            valid_vacancies.append(normalized)

    return valid_vacancies


def search_vacancies(city=None, title_query=None, limit: Optional[int] = 10):
    vacancies = get_vacancies()
    result = []

    city_normalized = city.strip().lower() if city else None
    title_normalized = title_query.strip().lower() if title_query else None

    for vacancy in vacancies:
        vacancy_city = str(vacancy.get("city", "")).strip().lower()
        vacancy_title = str(vacancy.get("title", "")).strip().lower()

        if city_normalized and vacancy_city != city_normalized:
            continue

        if title_normalized and title_normalized not in vacancy_title:
            continue

        result.append(vacancy)

    result.sort(
        key=lambda vacancy: (
            vacancy.get("region") or "",
            vacancy.get("city") or "",
            vacancy.get("project") or "",
            vacancy.get("title") or "",
            vacancy.get("address") or "",
        )
    )
    if limit is None:
        return result
    return result[:limit]


def get_available_titles(city=None):
    vacancies = get_vacancies()
    city_normalized = city.strip().lower() if city else None
    titles = []

    for vacancy in vacancies:
        vacancy_city = str(vacancy.get("city", "")).strip().lower()
        if city_normalized and vacancy_city != city_normalized:
            continue

        title = str(vacancy.get("title", "")).strip()
        if title and title not in titles:
            titles.append(title)

    titles.sort()
    return titles


def append_sheet_row(row: dict, sheet_name: Optional[str] = SHEETDB_RESPONSES_SHEET_NAME) -> bool:
    params = {"sheet": sheet_name} if sheet_name else None

    try:
        response = requests.post(
            SHEETDB_RESPONSES_API_URL,
            params=params,
            json={"data": row},
            timeout=30,
        )
    except RequestException as exc:
        print(f"SHEETDB APPEND ERROR: {exc}")
        return False

    if 200 <= response.status_code < 300:
        print(
            "SHEETDB APPEND OK:",
            row.get("record_type", "unknown"),
            "sheet=",
            sheet_name,
        )
        return True

    print(
        "SHEETDB APPEND FAILED:",
        response.status_code,
        response.text,
        "sheet=",
        sheet_name,
    )
    return False
