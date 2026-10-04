import aiohttp


class AdvertisingClient:
    API_URL = "https://botohub.me/get-tasks-extended"
    MAX_TASKS = 6

    def __init__(self, token: str):
        self.token = token.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    @staticmethod
    def parse_response(data: object) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Botohub вернул ответ неверного формата")
        raw_tasks = data.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise ValueError("В ответе Botohub поле tasks должно быть массивом")
        tasks = []
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            url = task.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            resource_id = task.get("resource_id")
            tasks.append({
                "url": url,
                "resource_id": str(resource_id).strip() if resource_id else url,
                "completed": task.get("completed") is True,
            })
        return {
            "tasks": tasks,
            "completed": data.get("completed") is True,
            "skip": data.get("skip") is True,
            "fake": data.get("fake") is True,
        }

    async def get_tasks(self, user_id: int) -> dict:
        if not self.enabled:
            raise RuntimeError("Не задан токен Botohub")
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {"Auth": self.token, "Content-Type": "application/json"}
        payload = {"chat_id": user_id, "max_op": self.MAX_TASKS, "only_has_check": True}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.API_URL, headers=headers, json=payload) as response:
                response.raise_for_status()
                return self.parse_response(await response.json())
