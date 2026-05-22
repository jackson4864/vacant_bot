import requests
from requests import RequestException

API_URL = "https://sheetdb.io/api/v1/gydose9dofxsj"


def _normalize_vacancy(vacancy):
    latitude = vacancy.get("latitude")
    longitude = vacancy.get("longitude")

    if not latitude or not longitude:
        return None

    normalized = dict(vacancy)
    normalized["latitude"] = float(latitude)
    normalized["longitude"] = float(longitude)

    for field in ("project", "region", "city", "title", "description", "description_2", "address", "maps", "payment"):
        value = normalized.get(field)
        if value is not None:
            normalized[field] = str(value).strip()

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


def search_vacancies(city=None, title_query=None, limit=10):
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
