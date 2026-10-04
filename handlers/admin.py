import asyncio
import logging
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile

from database import DEFAULT_TEXTS
from keyboards.admin import panel, section_actions, settings as settings_keyboard, withdrawal_actions
from states.admin import AdminInput
from utils.flyer import FlyerClient
from utils.formatting import stars

router = Router(name="admin")
logger = logging.getLogger(__name__)
SECTIONS = {
    "welcome": "🏡 Приветствие", "tasks": "🗂 Заработок", "balance": "🪙 Баланс",
    "profile": "👤 Профиль", "referrals": "👥 Рефералы", "bonuses": "🎁 Бонусы", "withdraw": "💸 Вывод",
}
SECTION_BUTTONS = {
    "welcome": "Приветствие", "tasks": "Заработок", "balance": "Баланс",
    "profile": "Профиль", "referrals": "Рефералы", "bonuses": "Бонусы", "withdraw": "Вывод",
}


def owner(callback: CallbackQuery, config) -> bool:
    return callback.from_user.id == config.admin_id


@router.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery, config):
    if not owner(callback, config):
        await callback.answer("Недоступно.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("👑 <b>Админ-панель</b>\nОдобрение заявки означает, что Stars уже отправлены пользователю вручную.", reply_markup=panel())


@router.callback_query(F.data.startswith("admin:"))
async def admin_actions(callback: CallbackQuery, state: FSMContext, db, config, bot):
    if not owner(callback, config):
        await callback.answer("Недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")
    action = parts[1]
    await callback.answer()
    if action == "stats":
        stats = await db.admin_stats()
        await callback.message.answer(f"📊 <b>Статистика</b>\nПользователей: {stats['users']}\nВыполнено заданий: {stats['tasks']}\nВыплачено Stars: {stars(stats['paid'])}\nЗаявок: {stats['requests']}", reply_markup=panel())
    elif action == "withdrawals":
        rows = await db.pending_withdrawals()
        if not rows:
            await callback.message.answer("Ожидающих заявок нет.", reply_markup=panel())
        for row in rows:
            username = f"@{row['username']}" if row["username"] else f"ID {row['user_id']}"
            await callback.message.answer(f"💸 Заявка #{row['id']}\nID: <code>{row['user_id']}</code>\nПользователь: {username}\nСумма: {stars(row['amount_cents'])} Stars\nДата: {row['created_at']}", reply_markup=withdrawal_actions(row["id"]))
    elif action == "settings":
        await callback.message.answer("⚙️ Выберите настройку:", reply_markup=settings_keyboard())
    elif action == "photos":
        await callback.message.answer("🖼 Выберите раздел:", reply_markup=self_sections("photo"))
    elif action == "texts":
        await callback.message.answer("📝 Выберите текст:", reply_markup=self_sections("text"))
    elif action == "broadcast":
        await state.set_state(AdminInput.broadcast)
        await callback.message.answer("Отправьте текст рассылки. Для отмены выполните /cancel.")
    elif action == "promo_create":
        await state.set_state(AdminInput.promo_create)
        await callback.message.answer("Введите промокод, награду и число активаций через пробел: CODE 1.5 100")
    elif action == "backup":
        await create_backup(callback.message, db, config)
    elif action == "set" and len(parts) == 3:
        key = parts[2]
        await state.update_data(setting_key=key)
        await state.set_state(AdminInput.setting_value)
        current = await db.setting(key)
        if key in {"ad_api_token", "flyer_api_key"}:
            current = "ключ уже сохранён" if current else "не задан"
        await callback.message.answer(f"Отправьте новое значение для <code>{key}</code>. Текущее состояние: {current}")
    elif action in {"upload", "view", "delete", "edit", "show", "reset"} and len(parts) == 3:
        operation, key = action, parts[2]
        if key not in SECTIONS:
            await callback.message.answer("Раздел не найден.")
            return
        if operation == "upload":
            await state.update_data(photo_key=key)
            await state.set_state(AdminInput.photo_upload)
            await callback.message.answer(f"Отправьте фото для раздела «{SECTIONS[key]}».")
        elif operation == "view":
            photo_id = await db.setting(f"photo_{key}")
            if photo_id:
                await callback.message.answer_photo(photo_id, caption=SECTIONS[key])
            else:
                await callback.message.answer("Фото не загружено.")
        elif operation == "delete":
            await db.set_setting(f"photo_{key}", "")
            (config.photos_dir / f"{key}.jpg").unlink(missing_ok=True)
            await db.log_admin(config.admin_id, "photo_delete", key)
            await callback.message.answer("Фото удалено.")
        elif operation == "edit":
            await state.update_data(text_key=key)
            await state.set_state(AdminInput.text_edit)
            await callback.message.answer(f"Отправьте новый текст для раздела «{SECTIONS[key]}».")
        elif operation == "show":
            await callback.message.answer(await db.setting(f"text_{key}"))
        else:
            await db.set_setting(f"text_{key}", DEFAULT_TEXTS[key])
            await db.log_admin(config.admin_id, "text_reset", key)
            await callback.message.answer("Текст сброшен к исходному.")
    elif action == "photo" and len(parts) == 3:
        key = parts[2]
        if key in SECTIONS:
            await callback.message.answer(f"🖼 {SECTIONS[key]}", reply_markup=section_actions("photo", key))
    elif action == "text" and len(parts) == 3:
        key = parts[2]
        if key in SECTIONS:
            await callback.message.answer(f"📝 {SECTIONS[key]}", reply_markup=section_actions("text", key))


def self_sections(kind: str):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    prefix = "admin:photo" if kind == "photo" else "admin:text"
    buttons = [[InlineKeyboardButton(text=SECTION_BUTTONS[key], callback_data=f"{prefix}:{key}")] for key in SECTIONS]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("admin:photo:"))
async def photo_section(callback: CallbackQuery, config):
    if not owner(callback, config):
        await callback.answer("Недоступно.", show_alert=True)
        return
    key = callback.data.split(":")[2]
    await callback.answer()
    await callback.message.answer(f"🖼 {SECTIONS.get(key, key)}", reply_markup=section_actions("photo", key))


@router.callback_query(F.data.startswith("admin:text:"))
async def text_section(callback: CallbackQuery, config):
    if not owner(callback, config):
        await callback.answer("Недоступно.", show_alert=True)
        return
    key = callback.data.split(":")[2]
    await callback.answer()
    await callback.message.answer(f"📝 {SECTIONS.get(key, key)}", reply_markup=section_actions("text", key))


@router.callback_query(F.data.startswith("withdraw:"))
async def resolve_withdrawal(callback: CallbackQuery, db, config, bot):
    if callback.from_user.id != config.admin_id:
        await callback.answer("Недоступно.", show_alert=True)
        return
    _, decision, request_id = callback.data.split(":")
    result = await db.resolve_withdrawal(int(request_id), decision == "approve")
    if result is None:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await db.log_admin(config.admin_id, f"withdraw_{decision}", str(request_id))
    await callback.answer("Заявка обработана.")
    try:
        if decision == "approve":
            await bot.send_message(result["user_id"], f"✅ Заявка #{request_id} одобрена. Выплачено {stars(result['amount_cents'])} Stars.")
            payout_channel = await db.setting("payout_channel", config.payout_channel)
            if payout_channel:
                username = f"@{result['username']}" if result["username"] else f"ID {result['user_id']}"
                date = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
                await bot.send_message(payout_channel, f"🪙 <b>Новая выплата успешно обработана</b>\n👤 Пользователь: {username}\n⭐ Сумма: {stars(result['amount_cents'])} Stars\n⌛ {date}\n✅ Выплата успешно отправлена")
        else:
            await bot.send_message(result["user_id"], f"❌ Заявка #{request_id} отклонена. Сумма возвращена на баланс.")
    except Exception:
        logger.exception("Не удалось отправить уведомление по заявке %s", request_id)
        await callback.message.answer("Статус изменён, но уведомление или пост не отправлен. Проверьте права бота и настройки канала.")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.message(AdminInput.setting_value)
async def save_setting(message: Message, state: FSMContext, db, config):
    if message.from_user.id != config.admin_id:
        await state.clear()
        return
    data = await state.get_data()
    key, value = data["setting_key"], (message.text or "").strip()
    if key == "min_withdraw":
        try:
            amount = int(float(value.replace(",", ".")) * 100)
            if amount <= 0:
                raise ValueError
            value = str(amount)
        except ValueError:
            await message.answer("Введите положительное число, например 5 или 2.5.")
            return
    if key == "flyer_api_key" and value:
        try:
            await FlyerClient(value).get_me()
        except Exception as error:
            await message.answer(f"Ключ Flyer не сохранён: {error}")
            return
    await db.set_setting(key, value)
    await db.log_admin(config.admin_id, "setting_update", key)
    await state.clear()
    await message.answer("Настройка сохранена в SQLite.")


@router.message(AdminInput.photo_upload)
async def save_photo(message: Message, state: FSMContext, db, config):
    if message.from_user.id != config.admin_id:
        await state.clear()
        return
    if not message.photo:
        await message.answer("Нужно отправить изображение как фото.")
        return
    key = (await state.get_data())["photo_key"]
    await db.set_setting(f"photo_{key}", message.photo[-1].file_id)
    config.photos_dir.mkdir(parents=True, exist_ok=True)
    remote = await message.bot.get_file(message.photo[-1].file_id)
    local_path = config.photos_dir / f"{key}.jpg"
    await message.bot.download_file(remote.file_path, destination=local_path)
    await db.log_admin(config.admin_id, "photo_upload", key)
    await state.clear()
    await message.answer("Фото сохранено. Telegram file_id остаётся доступен после перезапуска.")


@router.message(AdminInput.text_edit)
async def save_text(message: Message, state: FSMContext, db, config):
    if message.from_user.id != config.admin_id:
        await state.clear()
        return
    key = (await state.get_data())["text_key"]
    await db.set_setting(f"text_{key}", message.text or "")
    await db.log_admin(config.admin_id, "text_update", key)
    await state.clear()
    await message.answer("Текст сохранён в SQLite.")


@router.message(AdminInput.broadcast)
async def broadcast(message: Message, state: FSMContext, db, config, bot):
    if message.from_user.id != config.admin_id:
        await state.clear()
        return
    text = message.text or ""
    if not text:
        await message.answer("Рассылка поддерживает текстовые сообщения.")
        return
    await state.clear()
    sent = failed = 0
    for user_id in await db.all_user_ids():
        try:
            await bot.send_message(user_id, text, parse_mode=None)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    await db.log_admin(config.admin_id, "broadcast", f"sent={sent},failed={failed}")
    await message.answer(f"Рассылка завершена. Доставлено: {sent}; ошибок: {failed}.")


@router.message(Command("promo_add"))
async def promo_add_start(message: Message, state: FSMContext, config):
    if message.from_user.id != config.admin_id:
        await message.answer("Команда недоступна.")
        return
    await state.set_state(AdminInput.promo_create)
    await message.answer("Введите промокод, награду и число активаций через пробел: CODE 1.5 100")


@router.message(AdminInput.promo_create)
async def promo_add_save(message: Message, state: FSMContext, db, config):
    if message.from_user.id != config.admin_id:
        await state.clear()
        return
    try:
        from decimal import Decimal
        code, reward, uses = message.text.split()
        reward_cents = int(Decimal(reward.replace(",", ".")) * 100)
        uses = int(uses)
        if reward_cents <= 0 or uses <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Формат: CODE 1.5 100, сумма и количество должны быть положительными.")
        return
    import aiosqlite
    async with await db.connect() as conn:
        await conn.execute("INSERT OR REPLACE INTO promo_codes(code,reward_cents,uses_left) VALUES(?,?,?)", (code.upper(), reward_cents, uses))
    await db.log_admin(config.admin_id, "promo_create", code.upper())
    await state.clear()
    await message.answer("Промокод создан.")


@router.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.")


async def create_backup(message: Message, db, config):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive = Path(tempfile.gettempdir()) / f"telegram_bot_backup_{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        if db.path.exists():
            zipped.write(db.path, f"database/{db.path.name}")
        if config.photos_dir.exists():
            for path in config.photos_dir.rglob("*"):
                if path.is_file():
                    zipped.write(path, str(Path("photos") / path.relative_to(config.photos_dir)))
    try:
        await message.answer_document(FSInputFile(archive), caption="💾 Резервная копия базы данных и файловых фото.")
        await db.log_admin(config.admin_id, "backup", archive.name)
    finally:
        archive.unlink(missing_ok=True)