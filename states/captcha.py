from aiogram.fsm.state import State, StatesGroup


class Captcha(StatesGroup):
    waiting_for_fruit = State()