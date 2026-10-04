from aiogram.fsm.state import State, StatesGroup


class AdminInput(StatesGroup):
    broadcast = State()
    setting_value = State()
    photo_upload = State()
    text_edit = State()
    withdraw_amount = State()
    promo_create = State()