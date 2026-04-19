from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

CATALOG_BUTTON_TEXT = "📋 Каталог вакансий"


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)],
            [KeyboardButton(text=CATALOG_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
    )


def respond_keyboard(vacancy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Откликнуться",
                    callback_data=f"respond:{vacancy_id}",
                )
            ]
        ]
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Отправить телефон", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def region_keyboard(regions: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=region, callback_data=f"catalog_region:{index}")]
        for index, region in enumerate(regions)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def city_keyboard(cities: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=city, callback_data=f"catalog_city:{index}")]
        for index, city in enumerate(cities)
    ]
    rows.append([InlineKeyboardButton(text="← К регионам", callback_data="catalog:regions")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def catalog_navigation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Выбрать другой город", callback_data="catalog:cities")],
            [InlineKeyboardButton(text="← К регионам", callback_data="catalog:regions")],
        ]
    )
