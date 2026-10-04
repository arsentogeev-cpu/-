import logging
import secrets
from decimal import Decimal, InvalidOperation
from html import escape
from random import sample

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.user import back, captcha as captcha_keyboard, gate, home, tasks as task_keyboard
from states.captcha import Captcha
from states.admin import AdminInput
from utils.advertising import AdvertisingClient
from utils.flyer import FlyerClient
from utils.formatting import icon, stars

router = Router(name="user")
logger = logging.getLogger(__name__)
PHOTO_KEYS = {"welcome", "tasks", "balance", "profile", "referrals", "bonuses", "withdraw"}
FRUITS = (
    ("apple", "🍎", "яблоко"), ("banana", "🍌", "банан"), ("grapes", "🍇", "виноград"),
    ("orange", "🍊", "апельсин"), ("pear", "🍐", "грушу"), ("watermelon", "🍉", "арбуз"),
    ("strawberry", "🍓", "клубнику"), ("cherries", "🍒", "вишню"), ("lemon", "🍋", "лимон"),
)


async def send_section(target, db, key: str, text: str, reply_markup=None):
    photo_id = await db.setting(f"photo_{key}")
    if photo_id:
        if isinstance(target, CallbackQuery):
            try:
                await target.message.delete()
            except Exception:
                pass
            await target.message.answer_photo(photo_id, caption=text, reply_markup=reply_markup)
        else:
            await target.answer_photo(photo_id, caption=text, reply_markup=reply_markup)
    elif isinstance(target, CallbackQuery):
        if target.message.text is not None:
            await target.message.edit_text(text, reply_markup=reply_markup)
        else:
            try:
                await target.message.delete()
            except Exception:
                pass
            await target.message.answer(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


def cents(value: str) -> int:
    amount = Decimal(value.replace(",", "."))
    if amount <= 0 or amount.as_tuple().exponent < -2:
        raise InvalidOperation
    return int(amount * 100)


async def ad_client(db, config):
    token = await db.setting("ad_api_token")
    return AdvertisingClient(token or config.ad_api_token)


async def flyer_client(db, config):
    key = await db.setting("flyer_api_key")
    return FlyerClient(key or config.flyer_api_key)


async def issue_captcha(message: Message, state: FSMContext):
    options = sample(FRUITS, 6)
    correct = secrets.choice(options)
    challenge_id = secrets.token_urlsafe(6)
    await state.set_state(Captcha.waiting_for_fruit)
    await state.update_data(captcha_id=challenge_id, captcha_answer=correct[0])
    text = f"{icon('LOCK', '🔒')} <b>Проверка безопасности</b>\nНажмите на фрукт: <b>{correct[2]}</b>"
    await message.answer(text, reply_markup=captcha_keyboard(challenge_id, [(key, emoji) for key, emoji, _ in options]))


async def show_entry(target, db, config, bot, user_id: int):
    channel = await db.setting("required_channel", config.required_channel)
    subscribed = not channel
    if channel:
        try:
            member = await bot.get_chat_member(channel, user_id)
            subscribed = member.status in {"member", "administrator", "creator"} or (member.status == "restricted" and member.is_member)
        except Exception:
            subscribed = False
    welcome_text = f"{icon('BOT','🤖')} <b>{await db.setting('text_welcome')}</b>"
    markup = home(user_id == config.admin_id)
    if not subscribed:
        welcome_text += f"\n\n{icon('CHANNEL','🛡')} Для работы подпишитесь на канал и нажмите проверку."
        markup = gate(await db.setting("required_channel_url", config.required_channel_url))
    await send_section(target, db, "welcome", welcome_text, markup)


@router.message(Command("start"))
async def start(message: Message, command: CommandObject, db, config, state: FSMContext):
    referrer_id = None
    if command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args[4:])
        except ValueError:
            pass
    await db.register_user(message.from_user.id, message.from_user.username, referrer_id)
    user_record = await db.user(message.from_user.id)
    if user_record and not user_record["captcha_passed"]:
        await issue_captcha(message, state)
        return
    await show_entry(message, db, config, message.bot, message.from_user.id)


@router.callback_query(F.data.startswith("captcha:"))
async def verify_captcha(callback: CallbackQuery, state: FSMContext, db, config):
    parts = callback.data.split(":", 2)
    challenge = await state.get_data()
    if len(parts) != 3 or challenge.get("captcha_id") != parts[1]:
        await callback.answer("Проверка устарела. Отправьте /start, чтобы получить новую.", show_alert=True)
        return
    if challenge.get("captcha_answer") != parts[2]:
        await callback.answer("Неверный фрукт. Попробуйте ещё раз.", show_alert=True)
        return
    await db.mark_captcha_passed(callback.from_user.id)
    await state.clear()
    await callback.answer("Проверка пройдена!")
    await show_entry(callback, db, config, callback.bot, callback.from_user.id)


@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery, db, config):
    channel = await db.setting("required_channel", config.required_channel)
    if not channel:
        await callback.answer("Канал не настроен администратором.", show_alert=True)
        return
    try:
        member = await callback.bot.get_chat_member(channel, callback.from_user.id)
        subscribed = member.status in {"member", "administrator", "creator"} or (member.status == "restricted" and member.is_member)
    except Exception:
        subscribed = False
    if not subscribed:
        await callback.answer("Подписка пока не найдена. Подпишитесь и проверьте ещё раз.", show_alert=True)
        return
    await callback.answer("Подписка подтверждена!")
    welcome_text = f"{icon('BOT','🤖')} <b>{await db.setting('text_welcome')}</b>"
    await send_section(callback, db, "welcome", welcome_text, home(callback.from_user.id == config.admin_id))


@router.message(Command("admin"))
async def admin_command(message: Message, config):
    if message.from_user.id != config.admin_id:
        await message.answer("Команда недоступна.")
        return
    await message.answer("👑 Админ-панель:", reply_markup=home(True))


@router.callback_query(F.data == "home")
async def go_home(callback: CallbackQuery, db, config):
    await callback.answer()
    welcome_text = f"{icon('BOT','🤖')} <b>{await db.setting('text_welcome')}</b>"
    await send_section(callback, db, "welcome", welcome_text, home(callback.from_user.id == config.admin_id))


@router.callback_query(F.data == "tasks")
async def show_tasks(callback: CallbackQuery, db, config):
    await render_tasks(callback, db, config)


async def render_tasks(callback: CallbackQuery, db, config):
    botohub = await ad_client(db, config)
    flyer = await flyer_client(db, config)
    if not botohub.enabled and not flyer.enabled:
        await callback.answer()
        await send_section(callback, db, "tasks", f"{icon('TASKS','🗂')} <b>{await db.setting('text_tasks')}</b>\n\n{icon('INFO','💬')} Источники заданий не настроены. Добавьте токен в админ-панели.", back())
        return
    await callback.answer()
    user_id = callback.from_user.id
    reward_cents = round(config.task_reward * 100)
    referral_reward_cents = round(config.referral_reward * 100)
    rewarded_count = 0
    provider_errors = []
    botohub_fake = False

    if botohub.enabled:
        try:
            response = await botohub.get_tasks(user_id)
            botohub_fake = response["fake"]
            offers = response["tasks"]
            assignments = []
            for offer in offers:
                if offer["completed"]:
                    rewarded = await db.complete_task(
                        user_id,
                        f"botohub:{offer['resource_id']}",
                        reward_cents,
                        referral_reward_cents,
                    )
                    rewarded_count += int(rewarded)
                else:
                    assignments.append({
                        "id": str(offer["resource_id"]),
                        "urls": [offer["url"]],
                        "status": "incomplete",
                    })
            await db.sync_task_assignments(user_id, "botohub", assignments)
        except Exception:
            logger.exception("Ошибка получения заданий Botohub")
            provider_errors.append("Botohub")
    else:
        await db.sync_task_assignments(user_id, "botohub", [])

    if flyer.enabled:
        try:
            offers = await flyer.get_tasks(
                user_id,
                callback.from_user.language_code,
                limit=6,
            )
            assignments = []
            for offer in offers:
                signature = offer["signature"]
                status = await flyer.check_task(signature)
                status = status or offer["status"] or "incomplete"
                external_id = f"flyer:{signature}"
                if status == "complete":
                    rewarded = await db.complete_task(
                        user_id,
                        external_id,
                        reward_cents,
                        referral_reward_cents,
                    )
                    rewarded_count += int(rewarded)
                elif status in {"abort", "unavailable"}:
                    continue
                else:
                    urls = [] if status == "waiting" else offer["links"]
                    assignments.append({"id": signature, "urls": urls, "status": status})
            await db.sync_task_assignments(user_id, "flyer", assignments)
        except Exception:
            logger.exception("Ошибка получения или проверки заданий Flyer")
            provider_errors.append("Flyer")
    else:
        await db.sync_task_assignments(user_id, "flyer", [])

    rows = await db.task_assignments(user_id)
    reward_text = ""
    if rewarded_count:
        total_reward = rewarded_count * reward_cents
        reward_text = f"{icon('SUCCESS','✅')} Начислено за выполненные задания: {stars(total_reward)} Stars.\n\n"
    status_lines = []
    actionable_count = sum(row["task_status"] != "waiting" for row in rows)
    if actionable_count:
        status_lines.append(f"Доступно заданий: {actionable_count}")
    if any(row["task_status"] == "waiting" for row in rows):
        status_lines.append("Часть заданий Flyer выполнена и ожидает оплаты; Stars будут начислены после статуса complete (до 24 часов).")
    if botohub_fake:
        status_lines.append("Botohub временно не выдаёт задания этому аккаунту.")
    if not rows and not status_lines:
        status_lines.append("Сейчас нет доступных заданий. Попробуйте обновить список позже.")
    if provider_errors:
        status_lines.append("Источник заданий временно недоступен: " + ", ".join(provider_errors) + ".")
    status_lines.append(f"Награда за подтверждённое задание: {stars(reward_cents)} Stars.")
    status_text = "\n".join(status_lines)
    text = f"{icon('TASKS','🗂')} <b>{await db.setting('text_tasks')}</b>\n\n{reward_text}{status_text}"
    await send_section(callback, db, "tasks", text, task_keyboard(rows))


@router.callback_query(F.data == "refresh_tasks")
async def refresh_tasks(callback: CallbackQuery, db, config):
    await render_tasks(callback, db, config)


@router.callback_query(F.data.startswith("task:"))
async def verify_task(callback: CallbackQuery, db, config):
    await render_tasks(callback, db, config)


@router.callback_query(F.data == "balance")
async def balance(callback: CallbackQuery, db):
    user = await db.user(callback.from_user.id)
    counts = await db.profile_counts(callback.from_user.id)
    text = f"{icon('MONEY','🪙')} <b>Баланс</b>\n\nБаланс: {stars(user['balance_cents'])} ⭐️\nВсего заработано: {stars(user['earned_cents'])} ⭐️\nВсего выведено: {stars(user['withdrawn_cents'])} ⭐️\nВыполнено заданий: {counts['tasks']}"
    await callback.answer()
    await send_section(callback, db, "balance", f"{text}\n\n{await db.setting('text_balance')}", back())


@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery, db):
    user = await db.user(callback.from_user.id)
    counts = await db.profile_counts(callback.from_user.id)
    username = f"@{escape(user['username'])}" if user["username"] else "не указан"
    text = f"{icon('PROFILE','👤')} <b>Профиль</b>\n\nTelegram ID: <code>{user['user_id']}</code>\nUsername: {username}\nБаланс: {stars(user['balance_cents'])} ⭐️\nВыполнено заданий: {counts['tasks']}\nРефералов: {counts['referrals']}\nДата регистрации: {user['registered_at'][:10]}\n\n{await db.setting('text_profile')}"
    await callback.answer()
    await send_section(callback, db, "profile", text, back())


@router.callback_query(F.data == "referrals")
async def referrals(callback: CallbackQuery, db, config):
    counts = await db.profile_counts(callback.from_user.id)
    link = f"https://t.me/{(await callback.bot.get_me()).username}?start=ref_{callback.from_user.id}"
    text = f"{icon('REF','👥')} <b>Реферальная программа</b>\n\nВаша ссылка:\n<code>{link}</code>\nПриглашено: {counts['referrals']}\nПолучено бонусов: {stars(counts['referral_bonus'])} ⭐️\n\n{await db.setting('text_referrals')}"
    await callback.answer()
    await send_section(callback, db, "referrals", text, back())


@router.callback_query(F.data == "bonuses")
async def bonuses(callback: CallbackQuery, db):
    await callback.answer()
    await send_section(callback, db, "bonuses", f"{icon('GIFT','🎁')} <b>Бонусы</b>\n\n{await db.setting('text_bonuses')}\n\nЕжедневный бонус: /daily\nАктивировать промокод: /promo КОД", back())


@router.message(Command("daily"))
async def daily_bonus(message: Message, db):
    if await db.claim_daily(message.from_user.id, 50):
        await message.answer("🎁 Ежедневный бонус 0.5 ⭐️ начислен!")
    else:
        await message.answer("Вы уже получили бонус сегодня. Возвращайтесь завтра.")


@router.message(Command("promo"))
async def promo(message: Message, command: CommandObject, db):
    if not command.args:
        await message.answer("Использование: /promo КОД")
        return
    if await db.redeem_promo(message.from_user.id, command.args.strip()):
        await message.answer("✅ Промокод активирован.")
    else:
        await message.answer("Промокод недействителен, исчерпан или уже использован.")


@router.callback_query(F.data == "withdraw")
async def withdraw_start(callback: CallbackQuery, state: FSMContext, db):
    await state.set_state(AdminInput.withdraw_amount)
    await callback.answer()
    await callback.message.answer(f"{icon('WITHDRAW','🪙')} {await db.setting('text_withdraw')}\nВведите сумму в Stars (минимум {stars(int(await db.setting('min_withdraw', '500')))}).")


@router.message(AdminInput.withdraw_amount)
async def withdraw_submit(message: Message, state: FSMContext, db, config):
    try:
        amount = cents(message.text.strip())
    except (InvalidOperation, ValueError, AttributeError):
        await message.answer("Введите положительную сумму с точностью до 0.01 Stars.")
        return
    minimum = int(await db.setting("min_withdraw", str(round(config.min_withdraw * 100))))
    if amount < minimum:
        await message.answer(f"Минимальная сумма: {stars(minimum)} Stars.")
        return
    request_id = await db.request_withdrawal(message.from_user.id, amount)
    await state.clear()
    if request_id is None:
        await message.answer("Недостаточно средств на балансе.")
        return
    await message.answer(f"✅ Заявка #{request_id} создана. Статус: «Ожидает выплаты».")
    try:
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID {message.from_user.id}"
        await message.bot.send_message(config.admin_id, f"💸 Заявка #{request_id}\nID: <code>{message.from_user.id}</code>\nПользователь: {escape(username)}\nСумма: {stars(amount)} Stars\nДата: {await db.setting('timezone', 'UTC')} / {db.now()}", reply_markup=__import__("keyboards.admin", fromlist=["withdrawal_actions"]).withdrawal_actions(request_id))
    except Exception:
        logger.exception("Не удалось отправить заявку администратору")
