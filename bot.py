import asyncio
import html
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from config import BOT_TOKEN, SEARCH_RADIUS_KM
from db import (
    create_tables,
    get_cities_by_region,
    get_regions,
    get_vacancies_by_city,
    get_vacancy_by_id,
    save_response,
)
from keyboards import (
    CATALOG_BUTTON_TEXT,
    catalog_navigation_keyboard,
    city_keyboard,
    location_keyboard,
    phone_keyboard,
    region_keyboard,
    respond_keyboard,
)
from services import find_nearby_vacancies
from states import ResponseForm


dp = Dispatcher()


def escape_text(value: object) -> str:
    return html.escape(str(value), quote=False)


def escape_url(value: object) -> str:
    return html.escape(str(value), quote=True)


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


def safe_maps_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    url = str(url).strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def format_vacancy(vacancy: dict, include_distance: bool = False) -> str:
    text = f"<b>{escape_text(vacancy['title'])}</b>\n"

    if vacancy.get("project"):
        text += f"{escape_text(vacancy['project'])}\n"

    if vacancy.get("description"):
        text += f"{escape_text(vacancy['description'])}\n"

    if vacancy.get("description_2"):
        text += f"{escape_text(vacancy['description_2'])}\n"

    if vacancy.get("payment"):
        text += f"💰 {escape_text(vacancy['payment'])}\n"

    if vacancy.get("city"):
        text += f"🏙 {escape_text(vacancy['city'])}\n"

    text += f"📍 {escape_text(vacancy['address'])}\n"

    if include_distance and vacancy.get("distance") is not None:
        text += f"📏 Расстояние: {escape_text(vacancy['distance'])} км\n"

    maps_url = safe_maps_url(vacancy.get("maps"))
    if maps_url:
        text += f"🗺 <a href=\"{escape_url(maps_url)}\">Открыть на карте</a>\n"

    return text


async def show_regions(target: Message | CallbackQuery, state: FSMContext) -> None:
    regions = get_regions()
    await state.update_data(catalog_regions=regions)

    if not regions:
        text = "Пока нет вакансий с заполненным регионом."
        if isinstance(target, CallbackQuery):
            await target.message.answer(text)
            await target.answer()
        else:
            await target.answer(text)
        return

    text = "Выберите регион:"
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
        await callback.message.answer("В этом регионе пока нет городов с вакансиями.")
        await callback.answer()
        return

    await callback.message.answer(
        f"Регион: <b>{escape_text(region)}</b>\nВыберите город:",
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
            "В этом городе пока нет вакансий.",
            reply_markup=catalog_navigation_keyboard(),
        )
        await callback.answer()
        return

    shown = vacancies[:10]
    await callback.message.answer(
        f"Вакансии: <b>{escape_text(city)}</b>\n"
        f"Найдено: {len(vacancies)}. Показываю {len(shown)}.",
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
        f"Спасибо! Ваш отклик на вакансию <b>{title}</b> сохранен.\n"
        "С вами в ближайшее время свяжется специалист отдела подбора, "
        "ожидайте звонка.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()


@dp.message(CommandStart())
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет!\n\n"
        f"Я найду вакансии рядом с вами в радиусе {SEARCH_RADIUS_KM} км.\n"
        "Для быстрого поиска отправьте геопозицию. "
        "Для просмотра по региону и городу откройте каталог.",
        reply_markup=location_keyboard(),
    )


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Как это работает:\n\n"
        "1. Для быстрого поиска отправьте геопозицию\n"
        "2. Для детального поиска откройте каталог вакансий\n"
        "3. Выберите регион и город\n"
        "4. Нажмите 'Откликнуться'\n"
        "5. Заполните ФИО и телефон"
    )


@dp.message(Command("catalog"))
async def catalog_command_handler(message: Message, state: FSMContext) -> None:
    await show_regions(message, state)


@dp.message(F.text == CATALOG_BUTTON_TEXT)
async def catalog_button_handler(message: Message, state: FSMContext) -> None:
    await show_regions(message, state)


@dp.callback_query(F.data == "catalog:regions")
async def catalog_regions_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await show_regions(callback, state)


@dp.callback_query(F.data == "catalog:cities")
async def catalog_cities_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    region = data.get("catalog_region")
    if not region:
        await show_regions(callback, state)
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
        await callback.answer("Регион не найден", show_alert=True)
        return

    await show_cities(callback, state, region)


@dp.callback_query(F.data.startswith("catalog_city:"))
async def catalog_city_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    region = data.get("catalog_region")
    cities = data.get("catalog_cities")

    if not region:
        await show_regions(callback, state)
        return

    if not cities:
        cities = get_cities_by_region(region)

    try:
        city_index = int(callback.data.split(":", 1)[1])
        city = cities[city_index]
    except (IndexError, TypeError, ValueError):
        await callback.answer("Город не найден", show_alert=True)
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
            f"Рядом нет вакансий в радиусе {SEARCH_RADIUS_KM} км."
        )
        return

    result_vacancies = nearby[:5]

    await message.answer(
        f"Нашел {len(result_vacancies)} вакансий в радиусе {SEARCH_RADIUS_KM} км:"
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
        await callback.answer("Некорректная вакансия", show_alert=True)
        return

    vacancy = get_vacancy_by_id(vacancy_id)

    if not vacancy:
        await callback.answer("Вакансия не найдена", show_alert=True)
        return

    await state.update_data(vacancy_id=vacancy_id)
    await state.set_state(ResponseForm.waiting_full_name)
    await callback.message.answer(
        f"Отклик на вакансию: <b>{escape_text(vacancy['title'])}</b>\n\n"
        "Введите ваше ФИО:"
    )
    await callback.answer()


@dp.message(ResponseForm.waiting_full_name, F.text)
async def full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = message.text.strip()

    if len(full_name) < 5 or len(full_name.split()) < 2:
        await message.answer("Пожалуйста, введите корректные ФИО.")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(ResponseForm.waiting_phone)

    await message.answer(
        "Теперь отправьте телефон.",
        reply_markup=phone_keyboard(),
    )


@dp.message(ResponseForm.waiting_full_name)
async def full_name_fallback_handler(message: Message) -> None:
    await message.answer("Пожалуйста, введите ФИО текстом.")


@dp.message(ResponseForm.waiting_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext) -> None:
    if (
        message.contact.user_id
        and message.from_user
        and message.contact.user_id != message.from_user.id
    ):
        await message.answer("Пожалуйста, отправьте свой контакт.")
        return

    phone = message.contact.phone_number
    if not is_valid_phone(phone):
        await message.answer("Введите корректный номер телефона.")
        return

    await persist_response(message, state, phone)


@dp.message(ResponseForm.waiting_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()

    if not is_valid_phone(phone):
        await message.answer("Введите корректный номер телефона.")
        return

    await persist_response(message, state, phone)


@dp.message(ResponseForm.waiting_phone)
async def phone_fallback_handler(message: Message) -> None:
    await message.answer("Отправьте телефон контактом или введите номер текстом.")


async def main() -> None:
    create_tables()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
