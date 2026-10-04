import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from database import Database
import handlers.user as user_handlers
from utils.flyer import FlyerAPIError, FlyerClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    def raise_for_status(self):
        return None

    async def json(self, **kwargs):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    def post(self, url, json):
        self.requests.append({"url": url, "json": json})
        return FakeResponse(self.payloads.pop(0))


class FlyerTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_me_tasks_and_check_task_contract(self):
        session = FakeSession([
            {"type": "tasks", "status": True},
            {"result": [{
                "signature": "sig-1", "task": "subscribe channel", "price": 1.2,
                "links": ["https://t.me/example"], "status": "incomplete",
            }]},
            {"result": "complete"},
        ])
        with patch("utils.flyer.aiohttp.ClientSession", return_value=session):
            client = FlyerClient("flyer-key")
            self.assertEqual((await client.get_me())["type"], "tasks")
            tasks = await client.get_tasks(123, "ru", 100)
            status = await client.check_task("sig-1")

        self.assertEqual(session.requests[0], {
            "url": "https://api.flyerhubs.com/get_me", "json": {"key": "flyer-key"},
        })
        self.assertEqual(session.requests[1]["url"], "https://api.flyerhubs.com/get_tasks")
        self.assertEqual(session.requests[1]["json"], {
            "key": "flyer-key", "user_id": 123, "language_code": "ru", "limit": 10,
        })
        self.assertEqual(session.requests[2], {
            "url": "https://api.flyerhubs.com/check_task",
            "json": {"key": "flyer-key", "signature": "sig-1"},
        })
        self.assertEqual(tasks[0]["signature"], "sig-1")
        self.assertEqual(status, "complete")

    async def test_get_me_rejects_non_tasks_key(self):
        session = FakeSession([{"type": "sub", "status": True}])
        with patch("utils.flyer.aiohttp.ClientSession", return_value=session):
            with self.assertRaises(FlyerAPIError):
                await FlyerClient("wrong-type-key").get_me()

    async def test_earning_awards_only_flyer_complete_status(self):
        class FakeCallback:
            from_user = SimpleNamespace(id=123, language_code="ru")

            async def answer(self):
                return None

        class FakeFlyer:
            enabled = True

            async def get_tasks(self, user_id, language_code, limit):
                return [
                    {"signature": "done", "links": ["https://t.me/done"], "status": "incomplete"},
                    {"signature": "waiting", "links": ["https://t.me/wait"], "status": "incomplete"},
                ]

            async def check_task(self, signature):
                return {"done": "complete", "waiting": "waiting"}[signature]

        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "flyer-flow.sqlite3")
            await db.initialize()
            await db.register_user(123, "flyer-user", None)
            config = SimpleNamespace(task_reward=0.5, referral_reward=0.5, admin_id=391992084)
            rendered = {}

            async def capture_section(target, database, key, text, markup=None):
                rendered["text"] = text
                rendered["markup"] = markup

            with patch.object(user_handlers, "ad_client", new=AsyncMock(return_value=SimpleNamespace(enabled=False))), \
                    patch.object(user_handlers, "flyer_client", new=AsyncMock(return_value=FakeFlyer())), \
                    patch.object(user_handlers, "send_section", new=AsyncMock(side_effect=capture_section)):
                await user_handlers.render_tasks(FakeCallback(), db, config)

            user = await db.user(123)
            self.assertEqual(user["balance_cents"], 50)
            self.assertIn("ожидает оплаты", rendered["text"])
            buttons = [button for row in rendered["markup"].inline_keyboard for button in row]
            task_links = [button for button in buttons if button.url]
            self.assertEqual(task_links, [])
            waiting_rows = await db.task_assignments(123)
            self.assertEqual([(row["external_id"], row["task_status"]) for row in waiting_rows], [("flyer:waiting", "waiting")])

            with patch.object(user_handlers, "ad_client", new=AsyncMock(return_value=SimpleNamespace(enabled=False))), \
                    patch.object(user_handlers, "flyer_client", new=AsyncMock(return_value=FakeFlyer())), \
                    patch.object(user_handlers, "send_section", new=AsyncMock(side_effect=capture_section)):
                await user_handlers.render_tasks(FakeCallback(), db, config)
            self.assertEqual((await db.user(123))["balance_cents"], 50)
            self.assertNotIn("Начислено за выполненные задания", rendered["text"])


if __name__ == "__main__":
    unittest.main()