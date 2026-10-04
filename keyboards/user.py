from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import json


def gate(channel_url: str) -> InlineKeyboardMarkup:
    rows = []
    if channel_url:
        rows.append([InlineKeyboardButton(text="Подписаться на канал", url=channel_url)])
    rows.append([InlineKeyboardButton(text="Проверить подписку", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def captcha(challenge_id: str, fruits: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = []
    for index in range(0, len(fruits), 3):
        rows.append([
            InlineKeyboardButton(text=emoji, callback_data=f"captcha:{challenge_id}:{key}")
            for key, emoji in fruits[index:index + 3]
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Заработок", callback_data="tasks"), InlineKeyboardButton(text="Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="Профиль", callback_data="profile"), InlineKeyboardButton(text="Рефералы", callback_data="referrals")],
        [InlineKeyboardButton(text="Бонусы", callback_data="bonuses"), InlineKeyboardButton(text="Вывод", callback_data="withdraw")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админ-панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tasks(task_assignments: list) -> InlineKeyboardMarkup:
    rows = []
    buttons = []
    for task_number, assignment in enumerate(task_assignments, start=1):
        if assignment["task_status"] == "waiting":
            continue
        try:
            urls = json.loads(assignment["task_urls"] or "[]")
        except (TypeError, ValueError):
            urls = []
        if not urls and assignment["task_url"]:
            urls = [assignment["task_url"]]
        for link_number, url in enumerate(urls, start=1):
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            label = f"Задание {task_number}" if len(urls) == 1 else f"Задание {task_number}.{link_number}"
            buttons.append(InlineKeyboardButton(text=label, url=url))
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index:index + 2])
    rows.extend([[InlineKeyboardButton(text="Проверить подписки", callback_data="refresh_tasks")], [InlineKeyboardButton(text="Обновить задания", callback_data="refresh_tasks")], [InlineKeyboardButton(text="Меню", callback_data="home")]])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Меню", callback_data="home")]])