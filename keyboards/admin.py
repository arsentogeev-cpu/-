from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заявки на вывод", callback_data="admin:withdrawals"), InlineKeyboardButton(text="Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast"), InlineKeyboardButton(text="Настройки", callback_data="admin:settings")],
        [InlineKeyboardButton(text="Фотографии", callback_data="admin:photos"), InlineKeyboardButton(text="Тексты", callback_data="admin:texts")],
        [InlineKeyboardButton(text="Создать промокод", callback_data="admin:promo_create")],
        [InlineKeyboardButton(text="Резервная копия", callback_data="admin:backup"), InlineKeyboardButton(text="Меню", callback_data="home")],
    ])


def choices(prefix: str, names: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"{prefix}:{key}")] for label, key in names] + [[InlineKeyboardButton(text="Назад", callback_data="admin")]])


def settings() -> InlineKeyboardMarkup:
    return choices("admin:set", [("Минимальный вывод", "min_withdraw"), ("Информационный канал", "required_channel"), ("Ссылка на канал", "required_channel_url"), ("Канал выплат", "payout_channel"), ("Токен Botohub", "ad_api_token"), ("Ключ Flyer", "flyer_api_key")])


def section_actions(kind: str, key: str) -> InlineKeyboardMarkup:
    actions = [("Загрузить фото", f"admin:upload:{key}"), ("Просмотреть фото", f"admin:view:{key}"), ("Удалить фото", f"admin:delete:{key}")] if kind == "photo" else [("Изменить текст", f"admin:edit:{key}"), ("Посмотреть текст", f"admin:show:{key}"), ("Сбросить текст", f"admin:reset:{key}")]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)] for text, data in actions] + [[InlineKeyboardButton(text="Назад", callback_data=f"admin:{kind}s")]])


def withdrawal_actions(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Одобрить", callback_data=f"withdraw:approve:{request_id}"), InlineKeyboardButton(text="Отклонить", callback_data=f"withdraw:reject:{request_id}")]])