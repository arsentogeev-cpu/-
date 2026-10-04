import unittest
from unittest.mock import patch

from utils.advertising import AdvertisingClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    def post(self, url, headers, json):
        self.request = {"url": url, "headers": headers, "json": json}
        return FakeResponse(self.payload)


class AdvertisingTests(unittest.IsolatedAsyncioTestCase):
    async def test_extended_endpoint_auth_and_request_contract(self):
        payload = {
            "tasks": [
                {"url": "https://telegram.me/sponsor", "resource_id": "-100123", "completed": True},
                {"url": "https://telegram.me/second", "resource_id": "-100456", "completed": False},
            ],
            "completed": False,
            "skip": False,
        }
        session = FakeSession(payload)
        with patch("utils.advertising.aiohttp.ClientSession", return_value=session):
            result = await AdvertisingClient("integration-token").get_tasks(123456789)

        self.assertEqual(session.request["url"], "https://botohub.me/get-tasks-extended")
        self.assertEqual(session.request["headers"]["Auth"], "integration-token")
        self.assertEqual(session.request["json"], {
            "chat_id": 123456789,
            "max_op": 6,
            "only_has_check": True,
        })
        self.assertEqual(len(result["tasks"]), 2)
        self.assertTrue(result["tasks"][0]["completed"])
        self.assertFalse(result["tasks"][1]["completed"])


if __name__ == "__main__":
    unittest.main()