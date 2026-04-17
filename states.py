from aiogram.fsm.state import State, StatesGroup


class ResponseForm(StatesGroup):
    waiting_full_name = State()
    waiting_phone = State()