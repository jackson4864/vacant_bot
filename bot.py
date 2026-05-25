import asyncio
import hashlib
import html
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from config import BOT_TOKEN, SEARCH_RADIUS_KM, VACANCY_NOTIFY_INTERVAL_SECONDS
from db import (
    create_tables,
    get_all_cities,
    get_cities_by_region,
    get_known_external_vacancy_keys,
    get_regions,
    get_user_profile,
    get_user_profiles_by_city,
    get_vacancies_by_city,
    get_vacancy_by_id,
    save_known_external_vacancy_key,
    save_known_external_vacancy_keys,
    save_response,
    save_user_profile,
    upsert_vacancy,
)
from keyboards import (
    CATALOG_BUTTON_TEXT,
    MY_DATA_BUTTON_TEXT,
    catalog_navigation_keyboard,
    city_keyboard,
    consent_keyboard,
    location_keyboard,
    phone_keyboard,
    region_keyboard,
    respond_keyboard,
)
from services import find_nearby_vacancies
from states import ProfileForm, ResponseForm
from vacancy_api import append_sheet_row, get_vacancies


dp = Dispatcher()
VACANCY_NOTIFY_SOURCE = "telegram_vacancy_api"
CONSENT_TEXT = (
    "Даю согласие на обработку моих персональных данных: города, ФИО и телефона "
    "для подбора вакансий, связи со мной и фиксации откликов."
)


def escape_text(value: object) -> str:
    return html.escape(str(value), quote=False)


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


def telegram_external_user_id(message_or_callback: Message | CallbackQuery) -> Optional[str]:
    user = message_or_callback.from_user
    return str(user.id) if user else None


def get_telegram_profile(message_or_callback: Message | CallbackQuery) -> Optional[dict]:
    external_user_id = telegram_external_user_id(message_or_callback)
    if not external_user_id:
        return None
    return get_user_profile("telegram", external_user_id)


def format_profile(profile: dict) -> str:
    return (
        "👤 <b>Ваши данные:</b>\n\n"
        f"🏙 <b>Город:</b> {escape_text(profile['applicant_city'])}\n"
        f"👤 <b>ФИО:</b> {escape_text(profile['full_name'])}\n"
        f"📞 <b>Телефон:</b> {escape_text(profile['phone'])}"
    )


async def send_registration_intro(message: Message) -> None:
    await message.answer(
        "👋 Давайте познакомимся и соберем основную информацию для связи.\n\n"
        "Нужно будет указать:\n"
        "🏙 город\n"
        "👤 ФИО\n"
        "📞 телефон для связи",
    )
    await message.answer(
        "📄 <b>Согласие на обработку персональных данных</b>\n\n"
        f"{escape_text(CONSENT_TEXT)}\n\n"
        "Если согласны, нажмите кнопку ниже.",
        reply_markup=consent_keyboard(),
    )


def append_response_to_sheet(external_user_id: str, profile: dict, vacancy: dict) -> None:
    append_sheet_row(
        {
            "record_type": "response",
            "created_at": "DATETIME",
            "source_platform": "telegram",
            "external_user_id": external_user_id,
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


def vacancy_key(vacancy: dict) -> str:
    vacancy_id = str(vacancy.get("vacancy_id") or "").strip()
    if vacancy_id:
        return f"id:{vacancy_id.lower()}"

    parts = [
        vacancy.get("project") or "",
        vacancy.get("region") or "",
        vacancy.get("city") or "",
        vacancy.get("title") or "",
        vacancy.get("address") or "",
        str(vacancy.get("latitude") or ""),
        str(vacancy.get("longitude") or ""),
    ]
    raw = "|".join(str(part).strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sync_vacancies_from_api() -> int:
    synced = 0
    for vacancy in get_vacancies():
        upsert_vacancy(vacancy)
        synced += 1
    print("TELEGRAM VACANCY SYNC:", synced)
    return synced


def seed_known_vacancies() -> None:
    known = get_known_external_vacancy_keys(VACANCY_NOTIFY_SOURCE)
    if known:
        print("TELEGRAM VACANCY NOTIFY KNOWN:", len(known))
        return

    vacancies = get_vacancies()
    save_known_external_vacancy_keys(
        VACANCY_NOTIFY_SOURCE,
        [vacancy_key(vacancy) for vacancy in vacancies],
    )
    print("TELEGRAM VACANCY NOTIFY SEED:", len(vacancies))


def format_vacancy(vacancy: dict, include_distance: bool = False) -> str:
    lines = [f"💼 <b>{escape_text(vacancy['title'])}</b>"]

    if vacancy.get("project"):
        lines.append(f"🏢 <b>Проект:</b> {escape_text(vacancy['project'])}")

    if vacancy.get("payment"):
        lines.append(f"💰 <b>Оплата:</b> {escape_text(vacancy['payment'])}")

    if vacancy.get("city"):
        lines.append(f"🏙 <b>Город:</b> {escape_text(vacancy['city'])}")

    lines.append(f"📍 <b>Адрес:</b> {escape_text(vacancy['address'])}")

    if include_distance and vacancy.get("distance") is not None:
        lines.append(f"📏 <b>Расстояние:</b> {escape_text(vacancy['distance'])} км")

    description_lines = []
    if vacancy.get("description"):
        description_lines.append(escape_text(vacancy["description"]))
    if vacancy.get("description_2"):
        description_lines.append(escape_text(vacancy["description_2"]))

    if description_lines:
        lines.append("")
        lines.append("📝 <b>Описание:</b>")
        lines.extend(description_lines)

    return "\n".join(lines)


async def notify_new_vacancy(bot: Bot, vacancy: dict) -> None:
    city = str(vacancy.get("city") or "").strip()
    if not city:
        print("TELEGRAM VACANCY NOTIFY SKIP: empty city", vacancy.get("title"))
        return

    profiles = get_user_profiles_by_city("telegram", city)
    print(
        "TELEGRAM VACANCY NOTIFY MATCH:",
        "city=",
        city,
        "title=",
        vacancy.get("title"),
        "profiles=",
        len(profiles),
    )
    if not profiles:
        return

    local_vacancy_id = upsert_vacancy(vacancy)
    message_text = (
        f"🔔 Открыта новая вакансия в городе {escape_text(city)}.\n\n"
        f"{format_vacancy(vacancy)}"
    )

    for profile in profiles:
        try:
            await bot.send_message(
                chat_id=int(profile["external_user_id"]),
                text=message_text,
                reply_markup=respond_keyboard(local_vacancy_id),
                disable_web_page_preview=True,
            )
            print(
                "TELEGRAM VACANCY NOTIFY SENT:",
                "user_id=",
                profile["external_user_id"],
                "city=",
                city,
                "title=",
                vacancy.get("title"),
            )
        except Exception as exc:
            print(
                "TELEGRAM VACANCY NOTIFY ERROR:",
                "user_id=",
                profile["external_user_id"],
                "error=",
                exc,
            )


async def check_new_vacancies(bot: Bot) -> None:
    known = get_known_external_vacancy_keys(VACANCY_NOTIFY_SOURCE)
    vacancies = get_vacancies()
    print("TELEGRAM VACANCY NOTIFY CHECK:", "known=", len(known), "api=", len(vacancies))

    if not known:
        save_known_external_vacancy_keys(
            VACANCY_NOTIFY_SOURCE,
            [vacancy_key(vacancy) for vacancy in vacancies],
        )
        print("TELEGRAM VACANCY NOTIFY SEED DURING CHECK:", len(vacancies))
        return

    for vacancy in vacancies:
        key = vacancy_key(vacancy)
        if key in known:
            continue

        print(
            "TELEGRAM VACANCY NOTIFY NEW:",
            "city=",
            vacancy.get("city"),
            "title=",
            vacancy.get("title"),
            "address=",
            vacancy.get("address"),
        )
        await notify_new_vacancy(bot, vacancy)
        save_known_external_vacancy_key(VACANCY_NOTIFY_SOURCE, key)
        known.add(key)


async def vacancy_notification_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(VACANCY_NOTIFY_INTERVAL_SECONDS)
        try:
            sync_vacancies_from_api()
            await check_new_vacancies(bot)
        except Exception as exc:
            print("TELEGRAM VACANCY NOTIFY LOOP ERROR:", exc)


async def show_regions(target: Message | CallbackQuery, state: FSMContext) -> None:
    sync_vacancies_from_api()
    regions = get_regions()
    await state.update_data(catalog_regions=regions)

    if not regions:
        cities = get_all_cities()
        if cities:
            await state.update_data(catalog_region=None, catalog_cities=cities)
            text = "🏙 Выберите город:"
            markup = city_keyboard(cities)
            if isinstance(target, CallbackQuery):
                await target.message.answer(text, reply_markup=markup)
                await target.answer()
            else:
                await target.answer(text, reply_markup=markup)
            return

        text = "🔎 Пока нет вакансий."
        if isinstance(target, CallbackQuery):
            await target.message.answer(text)
            await target.answer()
        else:
            await target.answer(text)
        return

    text = "🌍 Выберите регион:"
    markup = region_keyboard(regions)

    if isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


async def show_cities(callback: CallbackQuery, state: FSMContext, region: str) -> None:
    cities = get_cities_by_region(region)
    await state.update_data(catalog_region=region, catalog_cities=cities)

    if not cities:
        await callback.message.answer("🔎 В этом регионе пока нет городов с вакансиями.")
        await callback.answer()
        return

    await callback.message.answer(
        f"🌍 <b>Регион:</b> {escape_text(region)}\n🏙 Выберите город:",
        reply_markup=city_keyboard(cities),
    )
    await callback.answer()


async def show_catalog_vacancies(
    callback: CallbackQuery,
    state: FSMContext,
    region: str,
    city: str,
) -> None:
    vacancies = get_vacancies_by_city(region, city)
    await state.update_data(catalog_region=region, catalog_city=city)

    if not vacancies:
        await callback.message.answer(
            "🔎 В этом городе пока нет вакансий.",
            reply_markup=catalog_navigation_keyboard(),
        )
        await callback.answer()
        return

    shown = vacancies[:10]
    await callback.message.answer(
        f"💼 <b>Вакансии:</b> {escape_text(city)}\n"
        f"✅ <b>Найдено:</b> {len(vacancies)}. Показываю {len(shown)}.",
        reply_markup=catalog_navigation_keyboard(),
    )

    for vacancy in shown:
        await callback.message.answer(
            format_vacancy(vacancy),
            reply_markup=respond_keyboard(vacancy["id"]),
            disable_web_page_preview=True,
        )

    await callback.answer()


async def persist_response(message: Message, state: FSMContext, phone: str) -> None:
    data = await state.get_data()
    vacancy_id = data["vacancy_id"]
    full_name = data["full_name"]

    save_response(
        vacancy_id=vacancy_id,
        full_name=full_name,
        phone=normalize_phone(phone),
        telegram_user_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None,
        chat_id=message.chat.id,
    )

    vacancy = get_vacancy_by_id(vacancy_id)
    title = escape_text(vacancy["title"]) if vacancy else "вакансию"

    await message.answer(
        f"✅ Спасибо! Ваш отклик на вакансию <b>{title}</b> сохранен.\n"
        "📞 С вами в ближайшее время свяжется специалист отдела подбора, "
        "ожидайте звонка.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()


async def persist_response_with_profile(
    callback: CallbackQuery,
    vacancy: dict,
    profile: dict,
) -> None:
    external_user_id = telegram_external_user_id(callback)
    save_response(
        vacancy_id=vacancy["id"],
        full_name=profile["full_name"],
        phone=profile["phone"],
        applicant_city=profile["applicant_city"],
        source_platform="telegram",
        external_user_id=external_user_id,
        telegram_user_id=callback.from_user.id if callback.from_user else None,
    )
    if external_user_id:
        append_response_to_sheet(external_user_id, profile, vacancy)

    await callback.message.answer(
        f"✅ Отклик на вакансию <b>{escape_text(vacancy['title'])}</b> сохранен.\n"
        "📞 С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка.",
        reply_markup=location_keyboard(),
    )


@dp.message(CommandStart())
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not get_telegram_profile(message):
        await send_registration_intro(message)
        return

    await message.answer(
        "👋 Привет!\n\n"
        f"💼 Я найду вакансии рядом с вами в радиусе {SEARCH_RADIUS_KM} км.\n"
        "📍 Для быстрого поиска отправьте геопозицию.\n"
        "🏙 Для просмотра по региону и городу откройте каталог.",
        reply_markup=location_keyboard(),
    )


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Как это работает:</b>\n\n"
        "1. 📍 Для быстрого поиска отправьте геопозицию\n"
        "2. 💼 Для детального поиска откройте каталог вакансий\n"
        "3. 🏙 Выберите регион и город\n"
        "4. ✅ Нажмите 'Откликнуться'\n"
        "5. 📞 Заполните ФИО и телефон"
    )


@dp.message(Command("catalog"))
async def catalog_command_handler(message: Message, state: FSMContext) -> None:
    await show_regions(message, state)


@dp.message(F.text == CATALOG_BUTTON_TEXT)
async def catalog_button_handler(message: Message, state: FSMContext) -> None:
    await show_regions(message, state)


@dp.message(F.text == MY_DATA_BUTTON_TEXT)
async def my_data_button_handler(message: Message, state: FSMContext) -> None:
    profile = get_telegram_profile(message)
    if not profile:
        await send_registration_intro(message)
        return

    await message.answer(format_profile(profile), reply_markup=location_keyboard())


@dp.callback_query(F.data == "profile:consent")
async def profile_consent_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileForm.waiting_city)
    await state.update_data(consent_text=CONSENT_TEXT)
    await callback.message.answer("🏙 Введите ваш город:")
    await callback.answer()


@dp.callback_query(F.data == "profile:later")
async def profile_later_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "Хорошо, можно заполнить данные позже через кнопку «Мои данные».",
        reply_markup=location_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "catalog:regions")
async def catalog_regions_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await show_regions(callback, state)


@dp.callback_query(F.data == "catalog:cities")
async def catalog_cities_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "catalog_region" not in data:
        await show_regions(callback, state)
        return

    region = data.get("catalog_region")
    if not region:
        cities = get_all_cities()
        await state.update_data(catalog_cities=cities)
        await callback.message.answer("🏙 Выберите город:", reply_markup=city_keyboard(cities))
        await callback.answer()
        return

    await show_cities(callback, state, region)


@dp.callback_query(F.data.startswith("catalog_region:"))
async def catalog_region_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    regions = data.get("catalog_regions") or get_regions()

    try:
        region_index = int(callback.data.split(":", 1)[1])
        region = regions[region_index]
    except (IndexError, TypeError, ValueError):
        await callback.answer("🔎 Регион не найден", show_alert=True)
        return

    await show_cities(callback, state, region)


@dp.callback_query(F.data.startswith("catalog_city:"))
async def catalog_city_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    region = data.get("catalog_region")
    cities = data.get("catalog_cities")

    if "catalog_region" not in data:
        await show_regions(callback, state)
        return

    if not cities:
        cities = get_cities_by_region(region) if region else get_all_cities()

    try:
        city_index = int(callback.data.split(":", 1)[1])
        city = cities[city_index]
    except (IndexError, TypeError, ValueError):
        await callback.answer("🔎 Город не найден", show_alert=True)
        return

    await show_catalog_vacancies(callback, state, region, city)


@dp.message(F.location)
async def location_handler(message: Message) -> None:
    user_lat = message.location.latitude
    user_lon = message.location.longitude

    vacancies = find_nearby_vacancies(
        user_lat=user_lat,
        user_lon=user_lon,
        radius_km=SEARCH_RADIUS_KM,
    )

    nearby = [v for v in vacancies if v["distance"] <= SEARCH_RADIUS_KM]
    nearby = sorted(nearby, key=lambda x: x["distance"])

    if not nearby:
        await message.answer(
            f"🔎 Рядом нет вакансий в радиусе {SEARCH_RADIUS_KM} км."
        )
        return

    result_vacancies = nearby[:5]

    await message.answer(
        f"✅ Нашел {len(result_vacancies)} вакансий в радиусе {SEARCH_RADIUS_KM} км:"
    )

    for vacancy in result_vacancies:
        await message.answer(
            format_vacancy(vacancy, include_distance=True),
            reply_markup=respond_keyboard(vacancy["id"]),
            disable_web_page_preview=True,
        )


@dp.callback_query(F.data.startswith("respond:"))
async def respond_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        vacancy_id = int(callback.data.split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        await callback.answer("⚠️ Некорректная вакансия", show_alert=True)
        return

    vacancy = get_vacancy_by_id(vacancy_id)

    if not vacancy:
        await callback.answer("🔎 Вакансия не найдена", show_alert=True)
        return

    profile = get_telegram_profile(callback)
    if not profile:
        await state.update_data(pending_vacancy_id=vacancy_id)
        await send_registration_intro(callback.message)
        await callback.answer()
        return

    await persist_response_with_profile(callback, vacancy, profile)
    await callback.answer()


@dp.message(ProfileForm.waiting_city, F.text)
async def profile_city_handler(message: Message, state: FSMContext) -> None:
    city = message.text.strip()
    if len(city) < 2:
        await message.answer("⚠️ Введите корректный город.")
        return

    await state.update_data(applicant_city=city)
    await state.set_state(ProfileForm.waiting_full_name)
    await message.answer("👤 Введите ваше ФИО:")


@dp.message(ProfileForm.waiting_city)
async def profile_city_fallback_handler(message: Message) -> None:
    await message.answer("🏙 Введите город текстом.")


@dp.message(ProfileForm.waiting_full_name, F.text)
async def profile_full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = message.text.strip()
    if len(full_name) < 5 or len(full_name.split()) < 2:
        await message.answer("⚠️ Пожалуйста, введите корректные ФИО.")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(ProfileForm.waiting_phone)
    await message.answer(
        "📞 Отправьте телефон кнопкой ниже или введите номер вручную.",
        reply_markup=phone_keyboard(),
    )


@dp.message(ProfileForm.waiting_full_name)
async def profile_full_name_fallback_handler(message: Message) -> None:
    await message.answer("👤 Пожалуйста, введите ФИО текстом.")


async def complete_profile(message: Message, state: FSMContext, phone: str) -> None:
    external_user_id = telegram_external_user_id(message)
    if not external_user_id:
        await message.answer("⚠️ Не удалось определить пользователя.")
        return

    data = await state.get_data()
    profile = save_user_profile(
        source_platform="telegram",
        external_user_id=external_user_id,
        applicant_city=data["applicant_city"],
        full_name=data["full_name"],
        phone=normalize_phone(phone),
        consent_given=True,
        consent_text=data.get("consent_text") or CONSENT_TEXT,
    )
    pending_vacancy_id = data.get("pending_vacancy_id")
    await state.clear()
    await message.answer(
        "✅ Спасибо, данные сохранены.\n\n" + format_profile(profile),
        reply_markup=location_keyboard(),
    )

    if pending_vacancy_id:
        vacancy = get_vacancy_by_id(int(pending_vacancy_id))
        if vacancy:
            save_response(
                vacancy_id=vacancy["id"],
                full_name=profile["full_name"],
                phone=profile["phone"],
                applicant_city=profile["applicant_city"],
                source_platform="telegram",
                external_user_id=external_user_id,
                telegram_user_id=message.from_user.id if message.from_user else None,
                username=message.from_user.username if message.from_user else None,
                chat_id=message.chat.id,
            )
            append_response_to_sheet(external_user_id, profile, vacancy)
            await message.answer(
                f"✅ Отклик на вакансию <b>{escape_text(vacancy['title'])}</b> сохранен.\n"
                "📞 С вами в ближайшее время свяжется специалист отдела подбора, ожидайте звонка."
            )


@dp.message(ProfileForm.waiting_phone, F.contact)
async def profile_phone_contact_handler(message: Message, state: FSMContext) -> None:
    if (
        message.contact.user_id
        and message.from_user
        and message.contact.user_id != message.from_user.id
    ):
        await message.answer("⚠️ Пожалуйста, отправьте свой контакт.")
        return

    phone = message.contact.phone_number
    if not is_valid_phone(phone):
        await message.answer("⚠️ Введите корректный номер телефона.")
        return

    await complete_profile(message, state, phone)


@dp.message(ProfileForm.waiting_phone, F.text)
async def profile_phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()
    if not is_valid_phone(phone):
        await message.answer("⚠️ Введите корректный номер телефона.")
        return

    await complete_profile(message, state, phone)


@dp.message(ProfileForm.waiting_phone)
async def profile_phone_fallback_handler(message: Message) -> None:
    await message.answer("📞 Отправьте телефон контактом или введите номер текстом.")


@dp.message(ResponseForm.waiting_full_name, F.text)
async def full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = message.text.strip()

    if len(full_name) < 5 or len(full_name.split()) < 2:
        await message.answer("⚠️ Пожалуйста, введите корректные ФИО.")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(ResponseForm.waiting_phone)

    await message.answer(
        "📞 Теперь отправьте телефон.",
        reply_markup=phone_keyboard(),
    )


@dp.message(ResponseForm.waiting_full_name)
async def full_name_fallback_handler(message: Message) -> None:
    await message.answer("👤 Пожалуйста, введите ФИО текстом.")


@dp.message(ResponseForm.waiting_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext) -> None:
    if (
        message.contact.user_id
        and message.from_user
        and message.contact.user_id != message.from_user.id
    ):
        await message.answer("⚠️ Пожалуйста, отправьте свой контакт.")
        return

    phone = message.contact.phone_number
    if not is_valid_phone(phone):
        await message.answer("⚠️ Введите корректный номер телефона.")
        return

    await persist_response(message, state, phone)


@dp.message(ResponseForm.waiting_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()

    if not is_valid_phone(phone):
        await message.answer("⚠️ Введите корректный номер телефона.")
        return

    await persist_response(message, state, phone)


@dp.message(ResponseForm.waiting_phone)
async def phone_fallback_handler(message: Message) -> None:
    await message.answer("📞 Отправьте телефон контактом или введите номер текстом.")


async def main() -> None:
    create_tables()
    sync_vacancies_from_api()
    seed_known_vacancies()

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set in .env")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    asyncio.create_task(vacancy_notification_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
