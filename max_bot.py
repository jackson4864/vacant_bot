import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests.exceptions import ReadTimeout, RequestException

from config import MAX_BOT_TOKEN, SEARCH_RADIUS_KM
from db import (
    create_tables,
    delete_user_data,
    get_user_profile,
    save_response,
    save_user_profile,
    upsert_vacancy,
)
from services import find_nearest_vacancies
from vacancy_api import append_sheet_row, get_available_titles, get_vacancies, search_vacancies

BASE_URL = "https://platform-api.max.ru"
MAX_RESULTS = 5
BOT_LABEL = "[MAX v2]"
MAX_BUTTONS_PER_ROW = 2
CONSENT_DOC_PATH = Path(__file__).with_name("personal_data_consent_merch_bot.docx")

ACTION_SEARCH = "action:search"
ACTION_CANCEL = "action:cancel"
ACTION_BACK_TO_MENU = "action:menu"
ACTION_SKIP_CITY = "action:skip_city"
ACTION_SKIP_TITLE = "action:skip_title"
ACTION_SHOW_MORE = "action:show_more"
ACTION_MY_DATA = "action:my_data"
ACTION_REGISTER = "action:register"
ACTION_DELETE_DATA = "action:delete_data"
ACTION_EDIT_DATA = "action:edit_data"
ACTION_EDIT_CITY = "action:edit_city"
ACTION_EDIT_FULL_NAME = "action:edit_full_name"
ACTION_EDIT_PHONE = "action:edit_phone"
TITLE_PREFIX = "title:"
RESPOND_PREFIX = "respond:"
LABEL_SEARCH = "🔎 Поиск по городу и должности"
LABEL_CANCEL = "❌ Отмена"
LABEL_MENU = "🏠 В меню"
LABEL_MY_DATA = "👤 Мои данные"
LABEL_REGISTER = "✅ Согласен"
LABEL_DELETE_DATA = "🗑 Удалить данные"
LABEL_EDIT_DATA = "✏️ Скорректировать данные"
LABEL_EDIT_CITY = "🏙 Город"
LABEL_EDIT_FULL_NAME = "👤 ФИО"
LABEL_EDIT_PHONE = "📞 Телефон"
LABEL_SKIP_CITY = "🌍 Любой город"
LABEL_SKIP_TITLE = "💼 Любая должность"
LABEL_RESPOND_PREFIX = "Откликнуться #"
LABEL_SHOW_MORE = "➡️ Показать еще"
CONSENT_TEXT = (
    "Даю согласие на обработку моих персональных данных: города, ФИО и телефона "
    "для подбора вакансий, связи со мной и фиксации откликов."
)

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
            [request_geo_button("📍 Быстрый поиск по гео")],
            [message_button(LABEL_SEARCH, ACTION_SEARCH)],
            [message_button(LABEL_MY_DATA, ACTION_MY_DATA)],
        ]
    )


def profile_actions_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button(LABEL_EDIT_DATA, ACTION_EDIT_DATA)],
            [message_button(LABEL_DELETE_DATA, ACTION_DELETE_DATA)],
            [message_button(LABEL_MENU, ACTION_BACK_TO_MENU)],
        ]
    )


def profile_edit_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button(LABEL_EDIT_CITY, ACTION_EDIT_CITY)],
            [message_button(LABEL_EDIT_FULL_NAME, ACTION_EDIT_FULL_NAME)],
            [message_button(LABEL_EDIT_PHONE, ACTION_EDIT_PHONE)],
            [message_button(LABEL_MENU, ACTION_BACK_TO_MENU)],
        ]
    )


def consent_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button(LABEL_REGISTER, ACTION_REGISTER)],
            [message_button(LABEL_CANCEL, ACTION_CANCEL)],
        ]
    )


def cancel_keyboard() -> list[dict[str, Any]]:
    return make_keyboard([[message_button(LABEL_CANCEL, ACTION_CANCEL)]])


def phone_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [request_contact_button("📞 Отправить телефон")],
            [message_button(LABEL_CANCEL, ACTION_CANCEL)],
        ]
    )


def vacancy_actions_keyboard(index: int) -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button(f"{LABEL_RESPOND_PREFIX}{index}", f"{RESPOND_PREFIX}{index}")],
            [message_button(LABEL_MENU, ACTION_BACK_TO_MENU)],
        ]
    )


def show_more_keyboard() -> list[dict[str, Any]]:
    return make_keyboard(
        [
            [message_button(LABEL_SHOW_MORE, ACTION_SHOW_MORE)],
            [message_button(LABEL_MENU, ACTION_BACK_TO_MENU)],
        ]
    )


def title_keyboard(titles: list[str]) -> list[dict[str, Any]]:
    buttons = [message_button(title, f"{TITLE_PREFIX}{title}") for title in titles]
    rows = chunk_buttons(buttons)
    rows.append([message_button(LABEL_SKIP_TITLE, ACTION_SKIP_TITLE)])
    rows.append([message_button(LABEL_CANCEL, ACTION_CANCEL)])
    return make_keyboard(rows)


def send_message(
    user_id: str,
    text: str,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> requests.Response:
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
    return response


def upload_file_attachment(file_path: Path) -> Optional[dict[str, Any]]:
    print("MAX FILE UPLOAD START:", file_path)
    if not file_path.exists():
        print("MAX FILE UPLOAD SKIPPED: file not found", file_path)
        return None

    token = require_max_token()
    try:
        upload_response = requests.post(
            f"{BASE_URL}/uploads",
            headers={"Authorization": token},
            params={"type": "file"},
            timeout=30,
        )
        upload_response.raise_for_status()
        upload_url = upload_response.json().get("url")
        if not upload_url:
            print("MAX FILE UPLOAD FAILED: upload url missing", upload_response.text)
            return None

        with file_path.open("rb") as file:
            file_response = requests.post(
                upload_url,
                files={"data": (file_path.name, file)},
                timeout=60,
            )
        if not file_response.ok:
            print("MAX FILE UPLOAD RESPONSE:", file_response.status_code, file_response.text)
        file_response.raise_for_status()
    except RequestException as exc:
        print("MAX FILE UPLOAD ERROR:", exc)
        return None

    payload = file_response.json()
    print("MAX FILE UPLOAD OK:", payload)
    return {"type": "file", "payload": payload}


def send_personal_data_document(user_id: str) -> None:
    print("MAX FILE SEND START:", user_id)
    attachment = upload_file_attachment(CONSENT_DOC_PATH)
    if not attachment:
        print("MAX FILE SEND SKIPPED: no attachment")
        return

    for attempt in range(3):
        response = send_message(
            user_id,
            "📎 Документ по обработке персональных данных.",
            attachments=[attachment],
        )
        if response.status_code != 400 or "attachment.not.ready" not in response.text:
            return

        print("MAX FILE ATTACHMENT NOT READY, retry:", attempt + 1)
        time.sleep(2 + attempt * 2)


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
            "all_results": [],
            "result_offset": 0,
            "selected_vacancy_id": None,
            "selected_vacancy_title": None,
            "pending_response_index": None,
            "questionnaire": {},
        },
    )


def reset_dialog(session: Dict[str, Any]) -> None:
    session["state"] = None
    session["search_city"] = None
    session["search_title"] = None
    session["available_titles"] = []
    session["all_results"] = []
    session["result_offset"] = 0
    session["selected_vacancy_id"] = None
    session["selected_vacancy_title"] = None
    session["pending_response_index"] = None
    session["questionnaire"] = {}


def normalize_text(text: Optional[str]) -> str:
    return (text or "").strip()


def escape_text(value: object) -> str:
    return str(value)


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


def get_max_profile(user_id: str) -> Optional[Dict[str, Any]]:
    return get_user_profile("max", user_id)


def format_profile(profile: Dict[str, Any]) -> str:
    return (
        "👤 Ваши данные:\n\n"
        f"🏙 Город: {escape_text(profile['applicant_city'])}\n"
        f"👤 ФИО: {escape_text(profile['full_name'])}\n"
        f"📞 Телефон: {escape_text(profile['phone'])}"
    )


def send_registration_intro(user_id: str) -> None:
    send_personal_data_document(user_id)
    send_message(
        user_id,
        "👋 Давайте познакомимся и соберем основную информацию для связи.\n\n"
        "Нужно будет указать:\n"
        "🏙 город\n"
        "👤 ФИО\n"
        "📞 телефон для связи",
    )
    send_message(
        user_id,
        "📄 Согласие на обработку персональных данных\n\n"
        f"{CONSENT_TEXT}\n\n"
        "Если согласны, нажмите кнопку ниже.",
        attachments=consent_keyboard(),
    )


def append_profile_to_sheet(user_id: str, profile: Dict[str, Any]) -> None:
    append_sheet_row(
        {
            "record_type": "profile",
            "created_at": "DATETIME",
            "source_platform": "max",
            "external_user_id": user_id,
            "applicant_city": profile["applicant_city"],
            "city": profile["applicant_city"],
            "full_name": profile["full_name"],
            "phone": profile["phone"],
            "vacancy": "",
            "vacancy_city": "",
            "address": "",
            "consent_given": "yes" if profile.get("consent_given") else "no",
            "consent_text": profile.get("consent_text") or "",
        }
    )


def append_response_to_sheet(
    user_id: str,
    profile: Dict[str, Any],
    vacancy: Dict[str, Any],
) -> None:
    append_sheet_row(
        {
            "record_type": "response",
            "created_at": "DATETIME",
            "source_platform": "max",
            "external_user_id": user_id,
            "applicant_city": profile["applicant_city"],
            "city": profile["applicant_city"],
            "full_name": profile["full_name"],
            "phone": profile["phone"],
            "vacancy": vacancy.get("title") or "",
            "vacancy_city": vacancy.get("city") or "",
            "address": vacancy.get("address") or "",
            "vacancy_region": vacancy.get("region") or "",
            "vacancy_title": vacancy.get("title") or "",
            "vacancy_address": vacancy.get("address") or "",
            "vacancy_project": vacancy.get("project") or "",
        }
    )


def format_vacancy(vacancy: Dict[str, Any], index: Optional[int] = None) -> str:
    title = vacancy.get("title") or "Вакансия"
    title_prefix = f"{index}. " if index is not None else ""
    lines = [f"💼 {title_prefix}{escape_text(title)}"]

    if vacancy.get("project"):
        lines.append(f"🏢 Проект: {escape_text(vacancy['project'])}")
    if vacancy.get("region") or vacancy.get("city"):
        location = " / ".join(
            str(value)
            for value in (vacancy.get("region"), vacancy.get("city"))
            if value
        )
        lines.append(f"🏙 Локация: {location}")
    if vacancy.get("address"):
        lines.append(f"📍 Адрес: {escape_text(vacancy['address'])}")
    if vacancy.get("payment"):
        lines.append(f"💰 Оплата: {escape_text(vacancy['payment'])}")
    if vacancy.get("distance") is not None:
        lines.append(f"📏 Расстояние: {escape_text(vacancy['distance'])} км")

    description_lines = []
    if vacancy.get("description"):
        description_lines.append(escape_text(vacancy["description"]))
    if vacancy.get("description_2"):
        description_lines.append(escape_text(vacancy["description_2"]))

    if description_lines:
        lines.append("")
        lines.append("📝 Описание:")
        lines.extend(description_lines)

    return "\n".join(lines)


def send_welcome(user_id: str) -> None:
    send_message(
        user_id,
        "👋 Привет! Здесь можно быстро найти подработку или постоянную вакансию рядом с вами.\n\n"
        "💼 Подберём варианты по геолокации, городу или должности.\n"
        "✅ Когда найдёте подходящую вакансию, отклик займёт меньше минуты.\n"
        "📞 Ваши контактные данные понадобятся только для связи по отклику.",
        attachments=main_menu_keyboard(),
    )


def send_vacancy_list(user_id: str, session: Dict[str, Any], vacancies: list[Dict[str, Any]]) -> None:
    session["all_results"] = vacancies
    session["result_offset"] = 0

    if not vacancies:
        send_message(
            user_id,
            "🔎 По вашему запросу вакансий не найдено.",
            attachments=main_menu_keyboard(),
        )
        return

    send_next_results_page(user_id, session)


def send_next_results_page(user_id: str, session: Dict[str, Any]) -> None:
    vacancies = session["all_results"]
    start = session["result_offset"]
    end = min(start + MAX_RESULTS, len(vacancies))

    if start == 0:
        send_message(
            user_id,
            f"✅ Нашел {len(vacancies)} вакансий. Ниже карточки с кнопками отклика.",
        )
    else:
        send_message(user_id, f"➡️ Показываю вакансии {start + 1}-{end} из {len(vacancies)}.")

    for index in range(start, end):
        vacancy = vacancies[index]
        display_index = index + 1
        send_message(
            user_id,
            format_vacancy(vacancy, index=display_index),
            attachments=vacancy_actions_keyboard(display_index),
        )

    session["result_offset"] = end

    if end < len(vacancies):
        send_message(
            user_id,
            f"📋 Показаны {end} из {len(vacancies)} вакансий.",
            attachments=show_more_keyboard(),
        )
    else:
        send_message(
            user_id,
            "✅ Это все найденные вакансии.",
            attachments=main_menu_keyboard(),
        )


def start_questionnaire(user_id: str, session: Dict[str, Any], selected_vacancy: Dict[str, Any]) -> None:
    profile = get_max_profile(user_id)
    if not profile:
        send_registration_intro(user_id)
        return

    local_vacancy_id = upsert_vacancy(selected_vacancy)
    send_personal_data_document(user_id)
    save_response(
        vacancy_id=local_vacancy_id,
        full_name=profile["full_name"],
        phone=profile["phone"],
        applicant_city=profile["applicant_city"],
        source_platform="max",
        external_user_id=user_id,
    )
    append_response_to_sheet(user_id, profile, selected_vacancy)
    send_message(
        user_id,
        f"✅ Отклик на вакансию {selected_vacancy['title']} сохранен.\n"
        "📞 С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка.",
        attachments=main_menu_keyboard(),
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
        f"✅ Спасибо! Ваш отклик на вакансию {title} сохранен.\n"
        "📞 С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка.",
        attachments=main_menu_keyboard(),
    )


def begin_registration_flow(user_id: str, session: Dict[str, Any]) -> None:
    session["state"] = "waiting_profile_city"
    session["questionnaire"] = {"consent_text": CONSENT_TEXT}
    send_message(
        user_id,
        "🏙 Введите ваш город:",
        attachments=cancel_keyboard(),
    )


def complete_registration(user_id: str, session: Dict[str, Any]) -> None:
    questionnaire = session["questionnaire"]
    profile = save_user_profile(
        source_platform="max",
        external_user_id=user_id,
        applicant_city=questionnaire["applicant_city"],
        full_name=questionnaire["full_name"],
        phone=questionnaire["phone"],
        consent_given=True,
        consent_text=questionnaire.get("consent_text") or CONSENT_TEXT,
    )
    append_profile_to_sheet(user_id, profile)

    pending_response_index = session.get("pending_response_index")
    session["state"] = None
    session["questionnaire"] = {}
    session["pending_response_index"] = None

    send_message(
        user_id,
        "✅ Спасибо, данные сохранены.\n\n" + format_profile(profile),
        attachments=main_menu_keyboard(),
    )

    if pending_response_index is not None and session["all_results"]:
        if 0 <= pending_response_index < len(session["all_results"]):
            start_questionnaire(user_id, session, session["all_results"][pending_response_index])


def save_profile_field(user_id: str, session: Dict[str, Any], field_name: str, value: str) -> None:
    profile = get_max_profile(user_id)
    if not profile:
        reset_dialog(session)
        send_registration_intro(user_id)
        return

    updated_city = profile["applicant_city"]
    updated_full_name = profile["full_name"]
    updated_phone = profile["phone"]

    if field_name == "applicant_city":
        updated_city = value
    elif field_name == "full_name":
        updated_full_name = value
    elif field_name == "phone":
        updated_phone = normalize_phone(value)

    updated_profile = save_user_profile(
        source_platform="max",
        external_user_id=user_id,
        applicant_city=updated_city,
        full_name=updated_full_name,
        phone=updated_phone,
        consent_given=True,
        consent_text=profile.get("consent_text") or CONSENT_TEXT,
    )
    session["state"] = None
    session["questionnaire"] = {}
    send_message(
        user_id,
        "✅ Данные обновлены.\n\n" + format_profile(updated_profile),
        attachments=profile_actions_keyboard(),
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

    normalized_text = text.strip()
    if normalized_text == LABEL_SEARCH:
        return ACTION_SEARCH
    if normalized_text == LABEL_CANCEL:
        return ACTION_CANCEL
    if normalized_text == LABEL_MENU:
        return ACTION_BACK_TO_MENU
    if normalized_text == LABEL_MY_DATA:
        return ACTION_MY_DATA
    if normalized_text == LABEL_REGISTER:
        return ACTION_REGISTER
    if normalized_text == LABEL_DELETE_DATA:
        return ACTION_DELETE_DATA
    if normalized_text == LABEL_EDIT_DATA:
        return ACTION_EDIT_DATA
    if normalized_text == LABEL_EDIT_CITY:
        return ACTION_EDIT_CITY
    if normalized_text == LABEL_EDIT_FULL_NAME:
        return ACTION_EDIT_FULL_NAME
    if normalized_text == LABEL_EDIT_PHONE:
        return ACTION_EDIT_PHONE
    if normalized_text == LABEL_SKIP_CITY:
        return ACTION_SKIP_CITY
    if normalized_text == LABEL_SKIP_TITLE:
        return ACTION_SKIP_TITLE
    if normalized_text == LABEL_SHOW_MORE:
        return ACTION_SHOW_MORE
    if normalized_text.startswith(LABEL_RESPOND_PREFIX):
        index = normalized_text.removeprefix(LABEL_RESPOND_PREFIX).strip()
        if index.isdigit():
            return f"{RESPOND_PREFIX}{index}"

    return normalized_text


def extract_text_value(text: str, payload: Any) -> str:
    normalized_text = normalize_text(text)
    if normalized_text:
        return normalized_text

    if isinstance(payload, str):
        return normalize_text(payload)

    if isinstance(payload, dict):
        for key in ("text", "value", "payload"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def begin_search_flow(user_id: str, session: Dict[str, Any]) -> None:
    session["state"] = "waiting_search_city"
    session["search_city"] = None
    session["search_title"] = None
    session["available_titles"] = []
    session["all_results"] = []
    session["result_offset"] = 0
    send_message(
        user_id,
        "🏙 Введите город для поиска вакансий.\n"
        "🌍 Если город не важен, нажмите кнопку ниже.",
        attachments=make_keyboard(
            [
                [message_button(LABEL_SKIP_CITY, ACTION_SKIP_CITY)],
                [message_button(LABEL_CANCEL, ACTION_CANCEL)],
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
            limit=None,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return

    session["state"] = "waiting_search_title"
    send_message(
        user_id,
        "💼 Выберите должность из списка.",
        attachments=title_keyboard(titles),
    )


def handle_stateful_input(user_id: str, text: str, session: Dict[str, Any]) -> bool:
    if session["state"] == "waiting_search_city":
        if len(text) < 2:
            send_message(user_id, "⚠️ Введите корректный город или нажмите 'Любой город'.")
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
                limit=None,
            )
            session["state"] = None
            send_vacancy_list(user_id, session, vacancies)
            return True

        send_message(user_id, "💼 Выберите должность кнопкой из списка.")
        return True

    if session["state"] in ("waiting_applicant_city", "waiting_profile_city"):
        if len(text) < 2:
            send_message(user_id, "⚠️ Введите корректный город.")
            return True
        session["questionnaire"]["applicant_city"] = text
        session["state"] = "waiting_profile_full_name"
        send_message(
            user_id,
            "👤 Введите ФИО:",
            attachments=cancel_keyboard(),
        )
        return True

    if session["state"] in ("waiting_full_name", "waiting_profile_full_name"):
        if len(text) < 5 or len(text.split()) < 2:
            send_message(user_id, "⚠️ Пожалуйста, введите корректные ФИО.")
            return True
        session["questionnaire"]["full_name"] = text
        session["state"] = "waiting_profile_phone"
        send_message(
            user_id,
            "📞 Отправьте телефон кнопкой ниже или введите номер вручную.",
            attachments=phone_keyboard(),
        )
        return True

    if session["state"] in ("waiting_phone", "waiting_profile_phone"):
        if not is_valid_phone(text):
            send_message(user_id, "⚠️ Введите корректный номер телефона.")
            return True
        session["questionnaire"]["phone"] = normalize_phone(text)
        complete_registration(user_id, session)
        return True

    if session["state"] == "waiting_edit_city":
        if len(text) < 2:
            send_message(user_id, "⚠️ Введите корректный город.")
            return True
        save_profile_field(user_id, session, "applicant_city", text)
        return True

    if session["state"] == "waiting_edit_full_name":
        if len(text) < 5 or len(text.split()) < 2:
            send_message(user_id, "⚠️ Пожалуйста, введите корректные ФИО.")
            return True
        save_profile_field(user_id, session, "full_name", text)
        return True

    if session["state"] == "waiting_edit_phone":
        if not is_valid_phone(text):
            send_message(user_id, "⚠️ Введите корректный номер телефона.")
            return True
        save_profile_field(user_id, session, "phone", text)
        return True

    return False


def try_handle_action(user_id: str, action: str, session: Dict[str, Any]) -> bool:
    if action == ACTION_REGISTER:
        begin_registration_flow(user_id, session)
        return True

    if action == ACTION_MY_DATA:
        profile = get_max_profile(user_id)
        if not profile:
            send_registration_intro(user_id)
            return True

        send_message(
            user_id,
            format_profile(profile),
            attachments=profile_actions_keyboard(),
        )
        return True

    if action == ACTION_DELETE_DATA:
        delete_user_data("max", user_id)
        reset_dialog(session)
        send_message(
            user_id,
            "🗑 Ваши данные удалены. Чтобы снова откликаться на вакансии, нужно будет заполнить их заново.",
            attachments=main_menu_keyboard(),
        )
        return True

    if action == ACTION_EDIT_DATA:
        if not get_max_profile(user_id):
            send_registration_intro(user_id)
            return True

        send_message(
            user_id,
            "✏️ Что хотите скорректировать?",
            attachments=profile_edit_keyboard(),
        )
        return True

    if action == ACTION_EDIT_CITY:
        if not get_max_profile(user_id):
            send_registration_intro(user_id)
            return True

        session["state"] = "waiting_edit_city"
        send_message(user_id, "🏙 Введите новый город:", attachments=cancel_keyboard())
        return True

    if action == ACTION_EDIT_FULL_NAME:
        if not get_max_profile(user_id):
            send_registration_intro(user_id)
            return True

        session["state"] = "waiting_edit_full_name"
        send_message(user_id, "👤 Введите новые ФИО:", attachments=cancel_keyboard())
        return True

    if action == ACTION_EDIT_PHONE:
        if not get_max_profile(user_id):
            send_registration_intro(user_id)
            return True

        session["state"] = "waiting_edit_phone"
        send_message(
            user_id,
            "📞 Отправьте новый телефон кнопкой ниже или введите номер вручную.",
            attachments=phone_keyboard(),
        )
        return True

    if action == ACTION_SEARCH:
        begin_search_flow(user_id, session)
        return True

    if action == ACTION_CANCEL:
        reset_dialog(session)
        send_message(
            user_id,
            "✅ Текущий сценарий сброшен.",
            attachments=main_menu_keyboard(),
        )
        return True

    if action == ACTION_BACK_TO_MENU:
        reset_dialog(session)
        send_message(
            user_id,
            "🏠 Вернул вас в главное меню.",
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
            limit=None,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return True

    if action == ACTION_SHOW_MORE:
        if not session["all_results"]:
            send_message(user_id, "🔎 Сначала выполните поиск вакансий.")
            return True
        if session["result_offset"] >= len(session["all_results"]):
            send_message(user_id, "✅ Больше вакансий нет.", attachments=main_menu_keyboard())
            return True
        send_next_results_page(user_id, session)
        return True

    if action.startswith(TITLE_PREFIX):
        if session["state"] != "waiting_search_title":
            return False

        selected_title = action.split(":", 1)[1].strip()
        session["search_title"] = selected_title or None
        vacancies = search_vacancies(
            city=session["search_city"],
            title_query=session["search_title"],
            limit=None,
        )
        session["state"] = None
        send_vacancy_list(user_id, session, vacancies)
        return True

    if action.startswith(RESPOND_PREFIX):
        if not session["all_results"]:
            send_message(user_id, "🔎 Сначала получите список вакансий.")
            return True

        try:
            index = int(action.split(":", 1)[1]) - 1
        except ValueError:
            send_message(user_id, "⚠️ Не удалось определить выбранную вакансию.")
            return True

        if index < 0 or index >= len(session["all_results"]):
            send_message(user_id, "🔎 Нет вакансии с таким номером.")
            return True

        if not get_max_profile(user_id):
            session["pending_response_index"] = index
            send_registration_intro(user_id)
            return True

        start_questionnaire(user_id, session, session["all_results"][index])
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
        limit=None,
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
        limit=None,
    )
    send_vacancy_list(user_id, session, vacancies)
    return True


def handle_contact(user_id: str, attachments: list[dict[str, Any]], session: Dict[str, Any]) -> bool:
    if session["state"] not in ("waiting_phone", "waiting_profile_phone", "waiting_edit_phone"):
        return False

    phone = parse_contact_phone(attachments)
    if not phone or not is_valid_phone(phone):
        send_message(user_id, "⚠️ Не удалось прочитать номер телефона, введите его вручную.")
        return True

    if session["state"] == "waiting_edit_phone":
        save_profile_field(user_id, session, "phone", phone)
        return True

    session["questionnaire"]["phone"] = normalize_phone(phone)
    complete_registration(user_id, session)
    return True


def handle_text_message(user_id: str, text: str, attachments: list[dict[str, Any]], payload: Any) -> None:
    session = get_session(user_id)
    text = extract_text_value(text, payload)
    action = extract_action_token(text, payload)

    if (
        text
        and session["state"] in ("waiting_phone", "waiting_profile_phone", "waiting_edit_phone")
        and handle_stateful_input(user_id, text, session)
    ):
        return

    if handle_contact(user_id, attachments, session):
        return

    if try_handle_action(user_id, action, session):
        return

    if handle_geo(user_id, attachments, session):
        return

    if not text:
        send_message(
            user_id,
            "🏠 Нажмите кнопку меню или отправьте текстовый запрос.",
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
            "✅ Текущий сценарий сброшен.",
            attachments=main_menu_keyboard(),
        )
        return

    send_message(
        user_id,
        "⚠️ Не понял запрос. Используйте кнопки ниже или /start для возврата в меню.",
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
