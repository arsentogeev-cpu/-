import aiosqlite
from datetime import datetime, timezone
import json
from pathlib import Path


DEFAULT_TEXTS = {
    "welcome": "Добро пожаловать! Выполняйте задания и получайте Stars.",
    "tasks": "Выберите задание. Информация о рекламодателе скрыта.",
    "balance": "Ваш баланс и история начислений.",
    "profile": "Информация о вашем профиле.",
    "referrals": "Приглашайте друзей и получайте бонус после их первого задания.",
    "bonuses": "Ежедневный бонус и промокоды.",
    "withdraw": "Создайте заявку на вывод Stars.",
}


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return _ConnectionContext(self.path)

    async def initialize(self, config=None):
        async with await self.connect() as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, username TEXT, balance_cents INTEGER NOT NULL DEFAULT 0,
                    earned_cents INTEGER NOT NULL DEFAULT 0, withdrawn_cents INTEGER NOT NULL DEFAULT 0,
                    registered_at TEXT NOT NULL, referred_by INTEGER REFERENCES users(user_id),
                    referral_bonus_paid INTEGER NOT NULL DEFAULT 0,
                    captcha_passed INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS completed_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                    task_id TEXT NOT NULL, reward_cents INTEGER NOT NULL, completed_at TEXT NOT NULL,
                    UNIQUE(user_id, task_id)
                );
                CREATE TABLE IF NOT EXISTS withdraw_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                    amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL, resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS referrals (
                    referrer_id INTEGER NOT NULL REFERENCES users(user_id), referred_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
                    bonus_cents INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, action TEXT NOT NULL,
                    details TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
                    external_id TEXT NOT NULL, task_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'botohub', task_urls TEXT NOT NULL DEFAULT '[]',
                    task_status TEXT NOT NULL DEFAULT 'incomplete',
                    UNIQUE(user_id, external_id)
                );
                CREATE TABLE IF NOT EXISTS daily_claims (
                    user_id INTEGER NOT NULL REFERENCES users(user_id), claim_date TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL, PRIMARY KEY(user_id, claim_date)
                );
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY, reward_cents INTEGER NOT NULL, uses_left INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS promo_uses (
                    code TEXT NOT NULL REFERENCES promo_codes(code), user_id INTEGER NOT NULL REFERENCES users(user_id),
                    PRIMARY KEY(code, user_id)
                );
            """)
            user_columns = await (await db.execute("PRAGMA table_info(users)")).fetchall()
            if "captcha_passed" not in {row["name"] for row in user_columns}:
                await db.execute("ALTER TABLE users ADD COLUMN captcha_passed INTEGER NOT NULL DEFAULT 1")
            assignment_columns = await (await db.execute("PRAGMA table_info(task_assignments)")).fetchall()
            assignment_column_names = {row["name"] for row in assignment_columns}
            if "task_url" not in assignment_column_names:
                await db.execute("ALTER TABLE task_assignments ADD COLUMN task_url TEXT NOT NULL DEFAULT ''")
            if "source" not in assignment_column_names:
                await db.execute("ALTER TABLE task_assignments ADD COLUMN source TEXT NOT NULL DEFAULT 'botohub'")
            if "task_urls" not in assignment_column_names:
                await db.execute("ALTER TABLE task_assignments ADD COLUMN task_urls TEXT NOT NULL DEFAULT '[]'")
                await db.execute("UPDATE task_assignments SET task_urls=json_array(task_url) WHERE task_url<>''")
            if "task_status" not in assignment_column_names:
                await db.execute("ALTER TABLE task_assignments ADD COLUMN task_status TEXT NOT NULL DEFAULT 'incomplete'")
            await db.execute("""UPDATE task_assignments SET external_id='botohub:' || external_id
                WHERE source='botohub' AND external_id NOT LIKE 'botohub:%' AND external_id NOT LIKE 'flyer:%'""")
            await db.execute("""UPDATE completed_tasks SET task_id='botohub:' || task_id
                WHERE task_id NOT LIKE 'botohub:%' AND task_id NOT LIKE 'flyer:%'""")
            defaults = {
                "min_withdraw": str(round(config.min_withdraw * 100)) if config else "500",
                "required_channel": config.required_channel if config else "",
                "required_channel_url": config.required_channel_url if config else "",
                "payout_channel": config.payout_channel if config else "",
                "ad_api_token": config.ad_api_token if config else "",
                "flyer_api_key": config.flyer_api_key if config else "",
            }
            defaults.update({f"text_{key}": value for key, value in DEFAULT_TEXTS.items()})
            for key in ("welcome", "tasks", "balance", "profile", "referrals", "bonuses", "withdraw"):
                defaults[f"photo_{key}"] = ""
            await db.executemany("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", defaults.items())

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def setting(self, key: str, default: str = "") -> str:
        async with await self.connect() as db:
            row = await (await db.execute("SELECT value FROM settings WHERE key=?", (key,))).fetchone()
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        async with await self.connect() as db:
            await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    async def register_user(self, user_id: int, username: str | None, referrer_id: int | None):
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                exists = await (await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))).fetchone()
                if exists:
                    await db.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
                    await db.commit()
                    return
                if referrer_id == user_id:
                    referrer_id = None
                valid_referrer = await (await db.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,))).fetchone() if referrer_id else None
                referrer_id = referrer_id if valid_referrer else None
                await db.execute("INSERT INTO users(user_id,username,registered_at,referred_by,captcha_passed) VALUES(?,?,?,?,0)", (user_id, username, self.now(), referrer_id))
                if referrer_id:
                    await db.execute("INSERT INTO referrals(referrer_id,referred_id,created_at) VALUES(?,?,?)", (referrer_id, user_id, self.now()))
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def user(self, user_id: int):
        async with await self.connect() as db:
            return await (await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))).fetchone()

    async def mark_captcha_passed(self, user_id: int):
        async with await self.connect() as db:
            await db.execute("UPDATE users SET captcha_passed=1 WHERE user_id=?", (user_id,))

    async def profile_counts(self, user_id: int):
        async with await self.connect() as db:
            row = await (await db.execute("""SELECT
                (SELECT COUNT(*) FROM completed_tasks WHERE user_id=?) tasks,
                (SELECT COUNT(*) FROM referrals WHERE referrer_id=?) referrals,
                (SELECT COALESCE(SUM(bonus_cents),0) FROM referrals WHERE referrer_id=?) referral_bonus""", (user_id, user_id, user_id))).fetchone()
            return row

    async def sync_task_assignments(self, user_id: int, source: str, tasks: list[dict]):
        prepared = []
        for task in tasks:
            task_id = str(task.get("id", "")).strip()
            urls = [url for url in task.get("urls", []) if isinstance(url, str) and url.startswith("https://")]
            status = str(task.get("status") or "incomplete")
            if not task_id or (not urls and status != "waiting"):
                continue
            external_id = f"{source}:{task_id}"
            prepared.append((external_id, urls, status))
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                external_ids = [row[0] for row in prepared]
                if external_ids:
                    placeholders = ",".join("?" for _ in external_ids)
                    await db.execute(
                        f"DELETE FROM task_assignments WHERE user_id=? AND source=? AND external_id NOT IN ({placeholders})",
                        (user_id, source, *external_ids),
                    )
                else:
                    await db.execute("DELETE FROM task_assignments WHERE user_id=? AND source=?", (user_id, source))
                for external_id, urls, status in prepared:
                    await db.execute("""INSERT INTO task_assignments(
                        user_id,external_id,task_url,created_at,source,task_urls,task_status
                    ) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,external_id) DO UPDATE SET
                        task_url=excluded.task_url,source=excluded.source,task_urls=excluded.task_urls,
                        task_status=excluded.task_status""",
                        (user_id, external_id, urls[0] if urls else "", self.now(), source,
                         json.dumps(urls), status))
                await db.commit()
            except Exception:
                await db.rollback()
                raise
            return await (await db.execute("""SELECT a.id,a.external_id,a.source,a.task_url,a.task_urls,a.task_status
                FROM task_assignments a LEFT JOIN completed_tasks c
                ON c.user_id=a.user_id AND c.task_id=a.external_id
                WHERE a.user_id=? AND c.id IS NULL AND a.task_status NOT IN ('complete','abort','unavailable')
                AND (a.task_url<>'' OR a.task_status='waiting')
                ORDER BY a.id LIMIT 6""", (user_id,))).fetchall()

    async def task_assignments(self, user_id: int):
        async with await self.connect() as db:
            return await (await db.execute("""SELECT a.id,a.external_id,a.source,a.task_url,a.task_urls,a.task_status
                FROM task_assignments a LEFT JOIN completed_tasks c
                ON c.user_id=a.user_id AND c.task_id=a.external_id
                WHERE a.user_id=? AND c.id IS NULL AND a.task_status NOT IN ('complete','abort','unavailable')
                AND (a.task_url<>'' OR a.task_status='waiting')
                ORDER BY a.id LIMIT 6""", (user_id,))).fetchall()

    async def update_task_status(self, user_id: int, external_id: str, status: str):
        async with await self.connect() as db:
            await db.execute("UPDATE task_assignments SET task_status=? WHERE user_id=? AND external_id=?", (status, user_id, external_id))

    async def remove_task_assignment(self, user_id: int, external_id: str):
        async with await self.connect() as db:
            await db.execute("DELETE FROM task_assignments WHERE user_id=? AND external_id=?", (user_id, external_id))

    async def task_id_for_assignment(self, user_id: int, assignment_id: int):
        async with await self.connect() as db:
            row = await (await db.execute("SELECT external_id FROM task_assignments WHERE id=? AND user_id=?", (assignment_id, user_id))).fetchone()
            return row["external_id"] if row else None

    async def complete_task(self, user_id: int, external_id: str, reward_cents: int, referral_reward_cents: int):
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute("INSERT INTO completed_tasks(user_id,task_id,reward_cents,completed_at) VALUES(?,?,?,?)", (user_id, external_id, reward_cents, self.now()))
                await db.execute("UPDATE users SET balance_cents=balance_cents+?, earned_cents=earned_cents+? WHERE user_id=?", (reward_cents, reward_cents, user_id))
                row = await (await db.execute("SELECT referred_by,referral_bonus_paid FROM users WHERE user_id=?", (user_id,))).fetchone()
                if row and row["referred_by"] and not row["referral_bonus_paid"]:
                    await db.execute("UPDATE users SET balance_cents=balance_cents+?, earned_cents=earned_cents+? WHERE user_id=?", (referral_reward_cents, referral_reward_cents, row["referred_by"]))
                    await db.execute("UPDATE users SET referral_bonus_paid=1 WHERE user_id=?", (user_id,))
                    await db.execute("UPDATE referrals SET bonus_cents=? WHERE referred_id=?", (referral_reward_cents, user_id))
                await db.execute("DELETE FROM task_assignments WHERE user_id=? AND external_id=?", (user_id, external_id))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                await db.rollback()
                return False

    async def request_withdrawal(self, user_id: int, amount_cents: int):
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            user = await (await db.execute("SELECT balance_cents FROM users WHERE user_id=?", (user_id,))).fetchone()
            if not user or user["balance_cents"] < amount_cents:
                await db.rollback()
                return None
            await db.execute("UPDATE users SET balance_cents=balance_cents-? WHERE user_id=?", (amount_cents, user_id))
            cur = await db.execute("INSERT INTO withdraw_requests(user_id,amount_cents,created_at) VALUES(?,?,?)", (user_id, amount_cents, self.now()))
            await db.commit()
            return cur.lastrowid

    async def withdrawal(self, request_id: int):
        async with await self.connect() as db:
            return await (await db.execute("SELECT r.*,u.username FROM withdraw_requests r JOIN users u USING(user_id) WHERE r.id=?", (request_id,))).fetchone()

    async def resolve_withdrawal(self, request_id: int, approve: bool):
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("SELECT r.*,u.username FROM withdraw_requests r JOIN users u USING(user_id) WHERE r.id=? AND r.status='pending'", (request_id,))).fetchone()
            if not row:
                await db.rollback()
                return None
            status = "approved" if approve else "rejected"
            if approve:
                await db.execute("UPDATE users SET withdrawn_cents=withdrawn_cents+? WHERE user_id=?", (row["amount_cents"], row["user_id"]))
            else:
                await db.execute("UPDATE users SET balance_cents=balance_cents+? WHERE user_id=?", (row["amount_cents"], row["user_id"]))
            await db.execute("UPDATE withdraw_requests SET status=?,resolved_at=? WHERE id=?", (status, self.now(), request_id))
            await db.commit()
            return dict(row)

    async def pending_withdrawals(self):
        async with await self.connect() as db:
            return await (await db.execute("SELECT r.*,u.username FROM withdraw_requests r JOIN users u USING(user_id) WHERE status='pending' ORDER BY id")).fetchall()

    async def claim_daily(self, user_id: int, reward_cents: int):
        date = datetime.now(timezone.utc).date().isoformat()
        async with await self.connect() as db:
            try:
                await db.execute("INSERT INTO daily_claims(user_id,claim_date,amount_cents) VALUES(?,?,?)", (user_id, date, reward_cents))
            except aiosqlite.IntegrityError:
                return False
            await db.execute("UPDATE users SET balance_cents=balance_cents+?,earned_cents=earned_cents+? WHERE user_id=?", (reward_cents, reward_cents, user_id))
            return True

    async def redeem_promo(self, user_id: int, code: str):
        async with await self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            promo = await (await db.execute("SELECT * FROM promo_codes WHERE code=? AND uses_left>0", (code.upper(),))).fetchone()
            if not promo:
                await db.rollback()
                return False
            try:
                await db.execute("INSERT INTO promo_uses(code,user_id) VALUES(?,?)", (code.upper(), user_id))
            except aiosqlite.IntegrityError:
                await db.rollback()
                return False
            await db.execute("UPDATE promo_codes SET uses_left=uses_left-1 WHERE code=?", (code.upper(),))
            await db.execute("UPDATE users SET balance_cents=balance_cents+?,earned_cents=earned_cents+? WHERE user_id=?", (promo["reward_cents"], promo["reward_cents"], user_id))
            await db.commit()
            return True

    async def admin_stats(self):
        async with await self.connect() as db:
            return await (await db.execute("SELECT (SELECT COUNT(*) FROM users) users,(SELECT COUNT(*) FROM completed_tasks) tasks,(SELECT COALESCE(SUM(amount_cents),0) FROM withdraw_requests WHERE status='approved') paid,(SELECT COUNT(*) FROM withdraw_requests) requests")).fetchone()

    async def all_user_ids(self):
        async with await self.connect() as db:
            rows = await (await db.execute("SELECT user_id FROM users")).fetchall()
            return [row["user_id"] for row in rows]

    async def log_admin(self, admin_id: int, action: str, details: str = ""):
        async with await self.connect() as db:
            await db.execute("INSERT INTO admin_logs(admin_id,action,details,created_at) VALUES(?,?,?,?)", (admin_id, action, details, self.now()))


class _ConnectionContext:
    def __init__(self, path: Path):
        self.path = path
        self.connection = None

    async def __aenter__(self):
        self.connection = await aiosqlite.connect(self.path, isolation_level=None)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        return self.connection

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.connection.close()