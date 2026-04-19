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
from db import create_tables, get_vacancy_by_id, save_response
from keyboards import location_keyboard, phone_keyboard, respond_keyboard
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
        f"Спасибо! Ваш отклик на вакансию <b>{title}</b> сохранен.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет!\n\n"
        f"Я найду вакансии рядом с вами в радиусе {SEARCH_RADIUS_KM} км.\n"
        "Нажмите кнопку ниже и отправьте геопозицию.",
        reply_markup=location_keyboard(),
    )


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Как это работает:\n\n"
        "1. Отправляете геопозицию\n"
        "2. Получаете ближайшие вакансии\n"
        "3. Нажимаете 'Откликнуться'\n"
        "4. Заполняете ФИО и телефон"
    )


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
        text = f"<b>{escape_text(vacancy['title'])}</b>\n"

        if vacancy.get("description"):
            text += f"{escape_text(vacancy['description'])}\n"

        if vacancy.get("description_2"):
            text += f"{escape_text(vacancy['description_2'])}\n"

        if vacancy.get("payment"):
            text += f"💰 {escape_text(vacancy['payment'])}\n"

        text += f"📍 {escape_text(vacancy['address'])}\n"
        text += f"📏 Расстояние: {escape_text(vacancy['distance'])} км\n"

        maps_url = safe_maps_url(vacancy.get("maps"))
        if maps_url:
            text += f"🗺 <a href=\"{escape_url(maps_url)}\">Открыть на карте</a>\n"

        await message.answer(
            text,
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
        "Теперь отправьте телефон.\n"
        "Можно нажать кнопку ниже или ввести номер вручную.",
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
