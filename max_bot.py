import re
import time
from typing import Any, Dict, Optional

import requests
from requests.exceptions import ReadTimeout

from config import MAX_BOT_TOKEN, SEARCH_RADIUS_KM
from db import create_tables, save_response, upsert_vacancy
from services import find_nearest_vacancies
from vacancy_api import get_vacancies, search_vacancies

BASE_URL = "https://platform-api.max.ru"
MAX_RESULTS = 5
user_sessions: Dict[str, Dict[str, Any]] = {}


def require_max_token() -> str:
    if not MAX_BOT_TOKEN:
        raise ValueError("MAX_BOT_TOKEN is not set in .env")
    return MAX_BOT_TOKEN


def send_message(user_id: str, text: str) -> None:
    token = require_max_token()
    response = requests.post(
        f"{BASE_URL}/messages",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        params={"user_id": user_id},
        json={"text": text},
        timeout=30,
    )
    print("SEND STATUS:", response.status_code)
    print("SEND RESPONSE:", response.text)


def get_updates(marker: Optional[str] = None) -> Dict[str, Any]:
    token = require_max_token()
    params = {}

    if marker:
        params["marker"] = marker

    response = requests.get(
        f"{BASE_URL}/updates",
        headers={"Authorization": token},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    print("UPDATES MARKER:", data.get("marker"))
    return data


def get_session(user_id: str) -> Dict[str, Any]:
    return user_sessions.setdefault(
        user_id,
        {
            "state": None,
            "search_city": None,
            "search_title": None,
            "last_results": [],
            "selected_vacancy_id": None,
            "selected_vacancy_title": None,
            "questionnaire": {},
        },
    )


def reset_dialog(session: Dict[str, Any]) -> None:
    session["state"] = None
    session["search_city"] = None
    session["search_title"] = None
    session["last_results"] = []
    session["selected_vacancy_id"] = None
    session["selected_vacancy_title"] = None
    session["questionnaire"] = {}


def normalize_text(text: Optional[str]) -> str:
    return (text or "").strip()


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    phone = re.sub(r"[^\d+]", "", phone)
    if phone.startswith("++"):
        phone = "+" + phone.lstrip("+")
    return phone


def is_valid_phone(phone: str) -> bool:
    normalized = normalize_phone(phone)
    if not normalized:
        return False

    digits = re.sub(r"\D", "", normalized)
    return 10 <= len(digits) <= 15 and (
        normalized.startswith("+") or normalized[0].isdigit()
    )


def format_vacancy(vacancy: Dict[str, Any], index: Optional[int] = None) -> str:
    lines = []
    if index is not None:
        lines.append(f"{index}. {vacancy['title']}")
    else:
        lines.append(str(vacancy["title"]))

    if vacancy.get("project"):
        lines.append(str(vacancy["project"]))
    if vacancy.get("city"):
        lines.append(f"Город: {vacancy['city']}")
    if vacancy.get("address"):
        lines.append(f"Адрес: {vacancy['address']}")
    if vacancy.get("payment"):
        lines.append(f"Оплата: {vacancy['payment']}")
    if vacancy.get("distance") is not None:
        lines.append(f"Расстояние: {vacancy['distance']} км")
    if vacancy.get("description"):
        lines.append(str(vacancy["description"]))
    if vacancy.get("description_2"):
        lines.append(str(vacancy["description_2"]))

    return "\n".join(lines)


def send_welcome(user_id: str) -> None:
    send_message(
        user_id,
        "Привет! Я помогу найти вакансии.\n\n"
        f"Доступно:\n"
        f"1. /near широта, долгота — поиск вакансий в радиусе {SEARCH_RADIUS_KM} км\n"
        "2. /search — поиск по городу и должности\n"
        "3. После списка вакансий отправьте номер вакансии, чтобы откликнуться\n"
        "4. /cancel — сбросить текущий сценарий",
    )


def send_vacancy_list(user_id: str, session: Dict[str, Any], vacancies: list[Dict[str, Any]]) -> None:
    session["last_results"] = vacancies

    if not vacancies:
        send_message(user_id, "По вашему запросу вакансий не найдено.")
        return

    chunks = ["Нашел вакансии:\n"]
    for index, vacancy in enumerate(vacancies, start=1):
        chunks.append(format_vacancy(vacancy, index=index))
        chunks.append("")

    chunks.append("Отправьте номер вакансии, чтобы откликнуться.")
    send_message(user_id, "\n".join(chunks).strip())


def start_questionnaire(user_id: str, session: Dict[str, Any], selected_vacancy: Dict[str, Any]) -> None:
    local_vacancy_id = upsert_vacancy(selected_vacancy)
    session["selected_vacancy_id"] = local_vacancy_id
    session["selected_vacancy_title"] = selected_vacancy["title"]
    session["questionnaire"] = {}
    session["state"] = "waiting_full_name"

    send_message(
        user_id,
        "Отклик на вакансию:\n"
        f"{selected_vacancy['title']}\n\n"
        "Введите ФИО:",
    )


def complete_response(user_id: str, session: Dict[str, Any]) -> None:
    questionnaire = session["questionnaire"]
    save_response(
        vacancy_id=session["selected_vacancy_id"],
        full_name=questionnaire["full_name"],
        phone=questionnaire["phone"],
        applicant_city=questionnaire["applicant_city"],
        source_platform="max",
        external_user_id=user_id,
    )
    reset_dialog(session)
    send_message(
        user_id,
        f"Спасибо! Ваш отклик на вакансию {session['selected_vacancy_title']} сохранен.\n"
        "С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка.",
    )


def handle_stateful_input(user_id: str, text: str, session: Dict[str, Any]) -> bool:
    if session["state"] == "waiting_search_city":
        session["search_city"] = None if text == "-" else text
        session["state"] = "waiting_search_title"
        send_message(
            user_id,
            "Введите должность или часть названия вакансии.\n"
            "Если должность не важна, отправьте -",
        )
        return True

    if session["state"] == "waiting_search_title":
        session["search_title"] = None if text == "-" else text
        vacancies = search_vacancies(
            city=session["search_city"],
            title_query=session["search_title"],
            limit=MAX_RESULTS,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return True

    if session["state"] == "waiting_full_name":
        if len(text) < 5 or len(text.split()) < 2:
            send_message(user_id, "Пожалуйста, введите корректные ФИО.")
            return True
        session["questionnaire"]["full_name"] = text
        session["state"] = "waiting_applicant_city"
        send_message(user_id, "Введите ваш город:")
        return True

    if session["state"] == "waiting_applicant_city":
        if len(text) < 2:
            send_message(user_id, "Пожалуйста, введите корректный город.")
            return True
        session["questionnaire"]["applicant_city"] = text
        session["state"] = "waiting_phone"
        send_message(user_id, "Введите номер телефона:")
        return True

    if session["state"] == "waiting_phone":
        if not is_valid_phone(text):
            send_message(user_id, "Введите корректный номер телефона.")
            return True
        session["questionnaire"]["phone"] = normalize_phone(text)
        complete_response(user_id, session)
        return True

    return False


def try_handle_vacancy_selection(user_id: str, text: str, session: Dict[str, Any]) -> bool:
    if not session["last_results"]:
        return False

    selection_text = text
    if text.lower().startswith("/respond"):
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            send_message(user_id, "После /respond укажите номер вакансии, например: /respond 2")
            return True
        selection_text = parts[1].strip()

    if not selection_text.isdigit():
        return False

    index = int(selection_text) - 1
    if index < 0 or index >= len(session["last_results"]):
        send_message(user_id, "Нет вакансии с таким номером.")
        return True

    start_questionnaire(user_id, session, session["last_results"][index])
    return True


def handle_near_command(user_id: str, text: str, session: Dict[str, Any]) -> bool:
    match = re.match(
        r"^/near\s+(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return False

    user_lat = float(match.group(1))
    user_lon = float(match.group(2))
    vacancies = find_nearest_vacancies(
        user_lat=user_lat,
        user_lon=user_lon,
        vacancies=get_vacancies(),
        radius_km=SEARCH_RADIUS_KM,
        limit=MAX_RESULTS,
    )
    send_vacancy_list(user_id, session, vacancies)
    return True


def handle_text_message(user_id: str, text: str) -> None:
    session = get_session(user_id)
    text = normalize_text(text)

    if not text:
        send_message(user_id, "Отправьте текстовую команду или запрос.")
        return

    if text.lower() == "/cancel":
        reset_dialog(session)
        send_message(user_id, "Текущий сценарий сброшен.")
        return

    if text.lower() == "/start":
        reset_dialog(session)
        send_welcome(user_id)
        return

    if handle_stateful_input(user_id, text, session):
        return

    if text.lower() == "/search":
        session["state"] = "waiting_search_city"
        session["search_city"] = None
        session["search_title"] = None
        session["last_results"] = []
        send_message(
            user_id,
            "Введите город для поиска вакансий.\n"
            "Если город не важен, отправьте -",
        )
        return

    if handle_near_command(user_id, text, session):
        return

    if try_handle_vacancy_selection(user_id, text, session):
        return

    send_message(
        user_id,
        "Не понял запрос.\n"
        f"Используйте /near широта, долгота для поиска в радиусе {SEARCH_RADIUS_KM} км,\n"
        "/search для поиска по городу и должности\n"
        "или /start для подсказки.",
    )


def handle_update(update: Dict[str, Any]) -> None:
    if update.get("update_type") != "message_created":
        return

    message = update.get("message", {})
    sender = message.get("sender", {})
    body = message.get("body", {})

    if sender.get("is_bot"):
        return

    user_id = sender.get("user_id")
    if user_id is None:
        return

    text = body.get("text", "")
    handle_text_message(str(user_id), text)


def main() -> None:
    create_tables()
    marker = None

    print("MAX bot started")

    while True:
        try:
            data = get_updates(marker)

            if data.get("marker"):
                marker = data["marker"]

            for update in data.get("updates", []):
                handle_update(update)

        except ReadTimeout:
            pass
        except Exception as exc:
            print("ERROR:", exc)

        time.sleep(1)


if __name__ == "__main__":
    main()
