from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, db, channel: str):
        self.db = db
        self.channel = channel

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data and event.data.startswith("captcha:"):
            return await handler(event, data)
        config = data.get("config")
        if config and user.id == config.admin_id:
            return await handler(event, data)
        user_record = await self.db.user(user.id)
        if user_record and not user_record["captcha_passed"]:
            if isinstance(event, CallbackQuery):
                await event.answer("Сначала пройдите проверку безопасности.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Сначала пройдите проверку безопасности в сообщении с фруктами.")
            return
        channel = await self.db.setting("required_channel", self.channel)
        if not channel:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)
        try:
            member = await data["bot"].get_chat_member(channel, user.id)
            allowed = member.status in {"member", "administrator", "creator"} or (member.status == "restricted" and member.is_member)
        except Exception:
            allowed = False
        if allowed:
            return await handler(event, data)
        text = "🔒 Для начала подпишитесь на обязательный информационный канал и нажмите «Проверить подписку»."
        if isinstance(event, CallbackQuery):
            await event.answer("Сначала подпишитесь на канал.", show_alert=True)
        elif isinstance(event, Message):
            from keyboards.user import gate
            await event.answer(text, reply_markup=gate(await self.db.setting("required_channel_url")))