import asyncio
import tempfile
import unittest
from pathlib import Path

import aiosqlite

from database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.db.initialize()
        await self.db.register_user(100, "inviter", None)
        await self.db.register_user(200, "invitee", 100)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_task_reward_and_referral_are_paid_once(self):
        self.assertTrue(await self.db.complete_task(200, "task-1", 50, 50))
        self.assertFalse(await self.db.complete_task(200, "task-1", 50, 50))
        self.assertEqual((await self.db.user(200))["balance_cents"], 50)
        self.assertEqual((await self.db.user(100))["balance_cents"], 50)

    async def test_withdrawal_rejection_refunds_balance(self):
        await self.db.complete_task(200, "task-2", 500, 50)
        request_id = await self.db.request_withdrawal(200, 300)
        self.assertIsNotNone(request_id)
        self.assertEqual((await self.db.user(200))["balance_cents"], 200)
        result = await self.db.resolve_withdrawal(request_id, False)
        self.assertEqual(result["username"], "invitee")
        self.assertEqual((await self.db.user(200))["balance_cents"], 500)

    async def test_simultaneous_start_registers_user_once(self):
        await asyncio.gather(*[
            self.db.register_user(300, "new_user", 100)
            for _ in range(8)
        ])
        user = await self.db.user(300)
        counts = await self.db.profile_counts(100)
        self.assertIsNotNone(user)
        self.assertEqual(counts["referrals"], 2)

    async def test_new_user_must_pass_captcha(self):
        self.assertEqual((await self.db.user(200))["captcha_passed"], 0)
        await self.db.mark_captcha_passed(200)
        self.assertEqual((await self.db.user(200))["captcha_passed"], 1)

    async def test_task_sources_sync_independently(self):
        await self.db.sync_task_assignments(200, "botohub", [{
            "id": "-100123", "urls": ["https://telegram.me/botohub"], "status": "incomplete",
        }])
        await self.db.sync_task_assignments(200, "flyer", [{
            "id": "signature-1", "urls": ["https://telegram.me/flyer"], "status": "incomplete",
        }])
        rows = await self.db.task_assignments(200)
        self.assertEqual({row["source"] for row in rows}, {"botohub", "flyer"})
        await self.db.sync_task_assignments(200, "botohub", [])
        rows = await self.db.task_assignments(200)
        self.assertEqual([row["external_id"] for row in rows], ["flyer:signature-1"])

    async def test_flyer_completion_reward_is_paid_once(self):
        await self.db.sync_task_assignments(200, "flyer", [{
            "id": "signature-2", "urls": ["https://telegram.me/flyer"], "status": "incomplete",
        }])
        self.assertTrue(await self.db.complete_task(200, "flyer:signature-2", 50, 50))
        self.assertFalse(await self.db.complete_task(200, "flyer:signature-2", 50, 50))
        self.assertEqual((await self.db.user(200))["balance_cents"], 50)

    async def test_legacy_user_is_not_prompted_for_captcha_again(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        async with aiosqlite.connect(legacy_path) as connection:
            await connection.execute("""CREATE TABLE users (
                user_id INTEGER PRIMARY KEY, username TEXT, balance_cents INTEGER NOT NULL DEFAULT 0,
                earned_cents INTEGER NOT NULL DEFAULT 0, withdrawn_cents INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT NOT NULL, referred_by INTEGER,
                referral_bonus_paid INTEGER NOT NULL DEFAULT 0
            )""")
            await connection.execute("""CREATE TABLE task_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                external_id TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(user_id, external_id)
            )""")
            await connection.execute("""CREATE TABLE completed_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                task_id TEXT NOT NULL, reward_cents INTEGER NOT NULL, completed_at TEXT NOT NULL,
                UNIQUE(user_id, task_id)
            )""")
            await connection.execute(
                "INSERT INTO users(user_id, username, registered_at) VALUES(300, 'legacy', '2025-01-01')"
            )
            await connection.execute(
                "INSERT INTO task_assignments(user_id, external_id, created_at) VALUES(300, 'old-task', '2025-01-01')"
            )
            await connection.execute(
                "INSERT INTO completed_tasks(user_id, task_id, reward_cents, completed_at) VALUES(300, 'done-task', 50, '2025-01-01')"
            )
            await connection.commit()
        legacy_db = Database(legacy_path)
        await legacy_db.initialize()
        self.assertEqual((await legacy_db.user(300))["captcha_passed"], 1)
        async with await legacy_db.connect() as connection:
            completed = await (await connection.execute("SELECT task_id FROM completed_tasks WHERE user_id=300")).fetchone()
        self.assertEqual(completed["task_id"], "botohub:done-task")
        assigned = await legacy_db.sync_task_assignments(300, "flyer", [{
            "id": "sig-123", "urls": ["https://telegram.me/new"], "status": "incomplete",
        }])
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]["external_id"], "flyer:sig-123")
        self.assertEqual(assigned[0]["task_url"], "https://telegram.me/new")


if __name__ == "__main__":
    unittest.main()