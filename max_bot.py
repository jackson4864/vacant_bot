import re
import time
from typing import Any, Dict, Optional

import requests
from requests.exceptions import ReadTimeout, RequestException

from config import MAX_BOT_TOKEN, SEARCH_RADIUS_KM
from db import create_tables, save_response, upsert_vacancy
from services import find_nearest_vacancies
from vacancy_api import get_available_titles, get_vacancies, search_vacancies

BASE_URL = "https://platform-api.max.ru"
MAX_RESULTS = 5
BOT_LABEL = "[MAX v2]"
MAX_BUTTONS_PER_ROW = 2

ACTION_SEARCH = "action:search"
ACTION_CANCEL = "action:cancel"
ACTION_BACK_TO_MENU = "action:menu"
ACTION_SKIP_CITY = "action:skip_city"
ACTION_SKIP_TITLE = "action:skip_title"
TITLE_PREFIX = "title:"
RESPOND_PREFIX = "respond:"

user_sessions: Dict[str, Dict[str, Any]] = {}


def require_max_token() -> str:
    if not MAX_BOT_TOKEN:
        raise ValueError("MAX_BOT_TOKEN is not set in .env")
    return MAX_BOT_TOKEN


def make_keyboard(buttons: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def message_button(text: str, payload: str) -> dict[str, Any]:
    return {
        "type": "message",
        "text": text,
        "payload": payload,
    }


def request_geo_button(text: str = "Отправить геолокацию") -> dict[str, Any]:
    return {
        "type": "request_geo_location",
        "text": text,
    }


def request_contact_button(text: str = "Отправить телефон") -> dict[str, Any]:
    return {
        "type": "request_contact",
        "text": text,
    }


def chunk_buttons(buttons: list[dict[str, Any]], row_size: int = MAX_BUTTONS_PER_ROW) -> list[list[dict[str, Any]]]:
    return [buttons[index:index + row_size] for index in range(0, len(buttons), row_size)]


def main_menu_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [request_geo_button("Быстрый поиск по гео")],
            [message_button("Поиск по городу и должности", ACTION_SEARCH)],
        ]
    )


def cancel_keyboard() -> list[dict[str, Any]]:
    return make_keyboard([[message_button("Отмена", ACTION_CANCEL)]])


def phone_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [request_contact_button("Отправить телефон")],
            [message_button("Отмена", ACTION_CANCEL)],
        ]
    )


def vacancy_actions_keyboard(index: int) -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button("Откликнуться", f"{RESPOND_PREFIX}{index}")],
            [message_button("В меню", ACTION_BACK_TO_MENU)],
        ]
    )


def title_keyboard(titles: list[str]) -> list[dict[str, Any]]:
    buttons = [message_button(title, f"{TITLE_PREFIX}{title}") for title in titles]
    rows = chunk_buttons(buttons)
    rows.append([message_button("Любая должность", ACTION_SKIP_TITLE)])
    rows.append([message_button("Отмена", ACTION_CANCEL)])
    return make_keyboard(rows)


def send_message(
    user_id: str,
    text: str,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> None:
    token = require_max_token()
    payload: dict[str, Any] = {"text": f"{BOT_LABEL}\n{text}"}
    if attachments:
        payload["attachments"] = attachments

    response = requests.post(
        f"{BASE_URL}/messages",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        params={"user_id": user_id},
        json=payload,
        timeout=30,
    )
    print("SEND STATUS:", response.status_code)
    print("SEND RESPONSE:", response.text)


def get_updates(marker: Optional[str] = None) -> Dict[str, Any]:
    token = require_max_token()
    params: dict[str, Any] = {
        "timeout": 30,
        "types": ["message_created"],
    }
    if marker:
        params["marker"] = marker

    response = requests.get(
        f"{BASE_URL}/updates",
        headers={"Authorization": token},
        params=params,
        timeout=35,
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
            "available_titles": [],
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
    session["available_titles"] = []
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
    title = str(vacancy.get("title") or "Вакансия")
    lines.append(f"{index}. {title}" if index is not None else title)

    if vacancy.get("project"):
        lines.append(str(vacancy["project"]))
    if vacancy.get("region") or vacancy.get("city"):
        location = " / ".join(
            str(value)
            for value in (vacancy.get("region"), vacancy.get("city"))
            if value
        )
        lines.append(f"Локация: {location}")
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
    if vacancy.get("maps"):
        lines.append(f"Карта: {vacancy['maps']}")

    return "\n".join(lines)


def send_welcome(user_id: str) -> None:
    send_message(
        user_id,
        "Привет! Я помогу найти вакансии.\n\n"
        "Используйте кнопки ниже:\n"
        "• быстрый поиск по геолокации\n"
        "• поиск по городу и должности",
        attachments=main_menu_keyboard(),
    )


def send_vacancy_list(user_id: str, session: Dict[str, Any], vacancies: list[Dict[str, Any]]) -> None:
    session["last_results"] = vacancies

    if not vacancies:
        send_message(
            user_id,
            "По вашему запросу вакансий не найдено.",
            attachments=main_menu_keyboard(),
        )
        return

    send_message(
        user_id,
        f"Нашел {len(vacancies)} вакансий. Ниже карточки с кнопками отклика.",
    )

    for index, vacancy in enumerate(vacancies, start=1):
        send_message(
            user_id,
            format_vacancy(vacancy, index=index),
            attachments=vacancy_actions_keyboard(index),
        )


def start_questionnaire(user_id: str, session: Dict[str, Any], selected_vacancy: Dict[str, Any]) -> None:
    local_vacancy_id = upsert_vacancy(selected_vacancy)
    session["selected_vacancy_id"] = local_vacancy_id
    session["selected_vacancy_title"] = selected_vacancy["title"]
    session["questionnaire"] = {}
    session["state"] = "waiting_applicant_city"

    send_message(
        user_id,
        "Отклик на вакансию:\n"
        f"{selected_vacancy['title']}\n\n"
        "Введите ваш город:",
        attachments=cancel_keyboard(),
    )


def complete_response(user_id: str, session: Dict[str, Any]) -> None:
    questionnaire = session["questionnaire"]
    title = session["selected_vacancy_title"]

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
        f"Спасибо! Ваш отклик на вакансию {title} сохранен.\n"
        "С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка.",
        attachments=main_menu_keyboard(),
    )


def parse_contact_phone(attachments: list[dict[str, Any]]) -> Optional[str]:
    for attachment in attachments:
        if attachment.get("type") != "contact":
            continue

        payload = attachment.get("payload") or {}
        vcf_info = payload.get("vcf_info", "")
        match = re.search(r"TEL[^:]*:(\+?\d+)", vcf_info)
        if match:
            return match.group(1)

        max_info = payload.get("max_info") or {}
        for key in ("phone", "phone_number"):
            if max_info.get(key):
                return str(max_info[key])
    return None


def _extract_geo_from_value(value: Any) -> Optional[tuple[float, float]]:
    if isinstance(value, dict):
        lower_map = {str(key).lower(): val for key, val in value.items()}

        lat = None
        lon = None
        for key in ("latitude", "lat"):
            if key in lower_map:
                lat = lower_map[key]
                break
        for key in ("longitude", "lon", "lng"):
            if key in lower_map:
                lon = lower_map[key]
                break

        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon)
            except (TypeError, ValueError):
                pass

        for nested_value in value.values():
            result = _extract_geo_from_value(nested_value)
            if result:
                return result

    if isinstance(value, list):
        for item in value:
            result = _extract_geo_from_value(item)
            if result:
                return result

    return None


def parse_geo(attachments: list[dict[str, Any]]) -> Optional[tuple[float, float]]:
    for attachment in attachments:
        result = _extract_geo_from_value(attachment)
        if result:
            return result
    return None


def extract_action_token(text: str, payload: Any) -> str:
    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    if isinstance(payload, dict):
        for key in ("payload", "text", "value", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return text.strip()


def begin_search_flow(user_id: str, session: Dict[str, Any]) -> None:
    session["state"] = "waiting_search_city"
    session["search_city"] = None
    session["search_title"] = None
    session["available_titles"] = []
    session["last_results"] = []
    send_message(
        user_id,
        "Введите город для поиска вакансий.\n"
        "Если город не важен, нажмите кнопку ниже.",
        attachments=make_keyboard(
            [
                [message_button("Любой город", ACTION_SKIP_CITY)],
                [message_button("Отмена", ACTION_CANCEL)],
            ]
        ),
    )


def ask_for_title(user_id: str, session: Dict[str, Any]) -> None:
    titles = get_available_titles(session["search_city"])
    session["available_titles"] = titles

    if not titles:
        vacancies = search_vacancies(
            city=session["search_city"],
            title_query=None,
            limit=MAX_RESULTS,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return

    session["state"] = "waiting_search_title"
    send_message(
        user_id,
        "Выберите должность из списка.",
        attachments=title_keyboard(titles),
    )


def handle_stateful_input(user_id: str, text: str, session: Dict[str, Any]) -> bool:
    if session["state"] == "waiting_search_city":
        if len(text) < 2:
            send_message(user_id, "Введите корректный город или нажмите 'Любой город'.")
            return True
        session["search_city"] = text
        ask_for_title(user_id, session)
        return True

    if session["state"] == "waiting_search_title":
        if session["available_titles"] and text in session["available_titles"]:
            session["search_title"] = text
            vacancies = search_vacancies(
                city=session["search_city"],
                title_query=session["search_title"],
                limit=MAX_RESULTS,
            )
            session["state"] = None
            send_vacancy_list(user_id, session, vacancies)
            return True

        send_message(user_id, "Выберите должность кнопкой из списка.")
        return True

    if session["state"] == "waiting_applicant_city":
        if len(text) < 2:
            send_message(user_id, "Введите корректный город.")
            return True
        session["questionnaire"]["applicant_city"] = text
        session["state"] = "waiting_full_name"
        send_message(
            user_id,
            "Введите ФИО:",
            attachments=cancel_keyboard(),
        )
        return True

    if session["state"] == "waiting_full_name":
        if len(text) < 5 or len(text.split()) < 2:
            send_message(user_id, "Пожалуйста, введите корректные ФИО.")
            return True
        session["questionnaire"]["full_name"] = text
        session["state"] = "waiting_phone"
        send_message(
            user_id,
            "Отправьте телефон кнопкой ниже или введите номер вручную.",
            attachments=phone_keyboard(),
        )
        return True

    if session["state"] == "waiting_phone":
        if not is_valid_phone(text):
            send_message(user_id, "Введите корректный номер телефона.")
            return True
        session["questionnaire"]["phone"] = normalize_phone(text)
        complete_response(user_id, session)
        return True

    return False


def try_handle_action(user_id: str, action: str, session: Dict[str, Any]) -> bool:
    if action == ACTION_SEARCH:
        begin_search_flow(user_id, session)
        return True

    if action == ACTION_CANCEL:
        reset_dialog(session)
        send_message(
            user_id,
            "Текущий сценарий сброшен.",
            attachments=main_menu_keyboard(),
        )
        return True

    if action == ACTION_BACK_TO_MENU:
        reset_dialog(session)
        send_message(
            user_id,
            "Вернул вас в главное меню.",
            attachments=main_menu_keyboard(),
        )
        return True

    if action == ACTION_SKIP_CITY:
        session["search_city"] = None
        ask_for_title(user_id, session)
        return True

    if action == ACTION_SKIP_TITLE:
        session["search_title"] = None
        vacancies = search_vacancies(
            city=session["search_city"],
            title_query=None,
            limit=MAX_RESULTS,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return True

    if action.startswith(TITLE_PREFIX):
        if session["state"] != "waiting_search_title":
            return False

        selected_title = action.split(":", 1)[1].strip()
        session["search_title"] = selected_title or None
        vacancies = search_vacancies(
            city=session["search_city"],
            title_query=session["search_title"],
            limit=MAX_RESULTS,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return True

    if action.startswith(RESPOND_PREFIX):
        if not session["last_results"]:
            send_message(user_id, "Сначала получите список вакансий.")
            return True

        try:
            index = int(action.split(":", 1)[1]) - 1
        except ValueError:
            send_message(user_id, "Не удалось определить выбранную вакансию.")
            return True

        if index < 0 or index >= len(session["last_results"]):
            send_message(user_id, "Нет вакансии с таким номером.")
            return True

        start_questionnaire(user_id, session, session["last_results"][index])
        return True

    return False


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


def handle_geo(user_id: str, attachments: list[dict[str, Any]], session: Dict[str, Any]) -> bool:
    geo = parse_geo(attachments)
    if not geo:
        return False

    user_lat, user_lon = geo
    vacancies = find_nearest_vacancies(
        user_lat=user_lat,
        user_lon=user_lon,
        vacancies=get_vacancies(),
        radius_km=SEARCH_RADIUS_KM,
        limit=MAX_RESULTS,
    )
    send_vacancy_list(user_id, session, vacancies)
    return True


def handle_contact(user_id: str, attachments: list[dict[str, Any]], session: Dict[str, Any]) -> bool:
    if session["state"] != "waiting_phone":
        return False

    phone = parse_contact_phone(attachments)
    if not phone or not is_valid_phone(phone):
        send_message(user_id, "Не удалось прочитать номер телефона, введите его вручную.")
        return True

    session["questionnaire"]["phone"] = normalize_phone(phone)
    complete_response(user_id, session)
    return True


def handle_text_message(user_id: str, text: str, attachments: list[dict[str, Any]], payload: Any) -> None:
    session = get_session(user_id)
    text = normalize_text(text)
    action = extract_action_token(text, payload)

    if handle_contact(user_id, attachments, session):
        return

    if handle_geo(user_id, attachments, session):
        return

    if try_handle_action(user_id, action, session):
        return

    if not text:
        send_message(
            user_id,
            "Нажмите кнопку меню или отправьте текстовый запрос.",
            attachments=main_menu_keyboard(),
        )
        return

    if text.lower() == "/start":
        reset_dialog(session)
        send_welcome(user_id)
        return

    if handle_stateful_input(user_id, text, session):
        return

    if text.lower() == "/search":
        begin_search_flow(user_id, session)
        return

    if handle_near_command(user_id, text, session):
        return

    if text.lower() == "/cancel":
        reset_dialog(session)
        send_message(
            user_id,
            "Текущий сценарий сброшен.",
            attachments=main_menu_keyboard(),
        )
        return

    send_message(
        user_id,
        "Не понял запрос. Используйте кнопки ниже или /start для возврата в меню.",
        attachments=main_menu_keyboard(),
    )


def handle_update(update: Dict[str, Any]) -> None:
    if update.get("update_type") != "message_created":
        return

    message = update.get("message", {})
    sender = message.get("sender", {})
    body = message.get("body", {}) or {}

    if sender.get("is_bot"):
        return

    user_id = sender.get("user_id")
    if user_id is None:
        return

    text = body.get("text", "")
    attachments = body.get("attachments") or []
    payload = body.get("payload")
    handle_text_message(str(user_id), text, attachments, payload)


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
        except RequestException as exc:
            print("NETWORK ERROR:", exc)
        except Exception as exc:
            print("ERROR:", exc)

        time.sleep(1)


if __name__ == "__main__":
    main()
