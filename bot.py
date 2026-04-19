import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext

from config import BOT_TOKEN, SEARCH_RADIUS_KM
from keyboards import location_keyboard, respond_keyboard, phone_keyboard
from services import find_nearby_vacancies
from states import ResponseForm
from db import get_vacancy_by_id, save_response


dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет!\n\n"
        "Я найду вакансии рядом с вами в радиусе 10 км.\n"
        "Нажмите кнопку ниже и отправьте геопозицию.",
        reply_markup=location_keyboard()
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
        print(vacancies)
        user_lat=user_lat,
        user_lon=user_lon,
        radius_km=SEARCH_RADIUS_KM
    )

    if not vacancies:
        await message.answer("Вакансии не найдены.")
        return

    nearby = [v for v in vacancies if v["in_radius"]]

    # если в радиусе меньше 5, добираем ближайшими
    if len(nearby) >= 5:
        result_vacancies = nearby[:5]
        header = f"Нашел 5 ближайших вакансий в радиусе {SEARCH_RADIUS_KM} км:"
    else:
        result_vacancies = vacancies[:5]
        header = (
            f"В радиусе {SEARCH_RADIUS_KM} км найдено только {len(nearby)} вакансий.\n"
            f"Показываю 5 ближайших вариантов:"
        )

    await message.answer(header)

    for vacancy in result_vacancies:
        text = f"<b>{vacancy['title']}</b>\n"

        if vacancy.get("description"):
            text += f"{vacancy['description']}\n"

        if vacancy.get("description_2"):
            text += f"{vacancy['description_2']}\n"

        if vacancy.get("payment"):
            text += f"💰 {vacancy['payment']}\n"

        text += f"📍 {vacancy['address']}\n"
        text += f"📏 Расстояние: {vacancy['distance']} км\n"

        if vacancy.get("maps"):
            text += f"🗺 <a href=\"{vacancy['maps']}\">Открыть на карте</a>\n"

        await message.answer(
            text,
            reply_markup=respond_keyboard(vacancy["id"]),
            disable_web_page_preview=True
        )

@dp.callback_query(F.data.startswith("respond:"))
async def respond_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
    vacancy_id = int(callback.data.split(":")[1])
    vacancy = get_vacancy_by_id(vacancy_id)

    if not vacancy:
        await callback.answer("Вакансия не найдена", show_alert=True)
        return

    await state.update_data(vacancy_id=vacancy_id)

    await state.set_state(ResponseForm.waiting_full_name)
    await callback.message.answer(
        f"Отклик на вакансию: <b>{vacancy['title']}</b>\n\n"
        "Введите ваше ФИО:"
    )
    await callback.answer()


@dp.message(ResponseForm.waiting_full_name)
async def full_name_handler(message: Message, state: FSMContext) -> None:
    full_name = message.text.strip()

    if len(full_name) < 5:
        await message.answer("Пожалуйста, введите корректные ФИО.")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(ResponseForm.waiting_phone)

    await message.answer(
        "Теперь отправьте телефон.\n"
        "Можно нажать кнопку ниже или ввести номер вручную.",
        reply_markup=phone_keyboard()
    )


@dp.message(ResponseForm.waiting_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext) -> None:
    phone = message.contact.phone_number
    data = await state.get_data()

    vacancy_id = data["vacancy_id"]
    full_name = data["full_name"]

    save_response(vacancy_id=vacancy_id, full_name=full_name, phone=phone)

    vacancy = get_vacancy_by_id(vacancy_id)

    await message.answer(
        f"Спасибо! Ваш отклик на вакансию <b>{vacancy['title']}</b> сохранен.",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.clear()


@dp.message(ResponseForm.waiting_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext) -> None:
    phone = message.text.strip()
    data = await state.get_data()

    if len(phone) < 6:
        await message.answer("Введите корректный номер телефона.")
        return

    vacancy_id = data["vacancy_id"]
    full_name = data["full_name"]

    save_response(vacancy_id=vacancy_id, full_name=full_name, phone=phone)

    vacancy = get_vacancy_by_id(vacancy_id)

    await message.answer(
        f"Спасибо! Ваш отклик на вакансию <b>{vacancy['title']}</b> сохранен.",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.clear()


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
