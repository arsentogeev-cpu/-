import aiohttp


class FlyerAPIError(RuntimeError):
    pass


class FlyerClient:
    API_URL = "https://api.flyerhubs.com"
    TASK_STATUSES = {"unavailable", "incomplete", "abort", "waiting", "complete"}

    def __init__(self, key: str):
        self.key = key.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    async def _post(self, method: str, payload: dict) -> dict:
        if not self.enabled:
            raise FlyerAPIError("Не задан ключ Flyer")
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self.API_URL}/{method}", json={"key": self.key, **payload}) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        if not isinstance(data, dict):
            raise FlyerAPIError("Flyer вернул ответ неверного формата")
        if data.get("error"):
            raise FlyerAPIError(str(data["error"]))
        return data

    async def get_me(self) -> dict:
        data = await self._post("get_me", {})
        if data.get("status") is not True:
            raise FlyerAPIError("Ключ Flyer неактивен")
        if data.get("type") != "tasks":
            raise FlyerAPIError("Ключ Flyer должен иметь тип tasks")
        return data

    async def get_tasks(self, user_id: int, language_code: str | None = None, limit: int = 6) -> list[dict]:
        payload = {"user_id": user_id, "limit": max(1, min(limit, 10))}
        if language_code:
            payload["language_code"] = language_code
        data = await self._post("get_tasks", payload)
        raw_tasks = data.get("result")
        if raw_tasks is None:
            raise FlyerAPIError("Flyer не вернул список заданий")
        if not isinstance(raw_tasks, list):
            raise FlyerAPIError("В ответе Flyer поле result должно быть массивом")

        tasks = []
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            signature = task.get("signature")
            raw_links = task.get("links")
            if not isinstance(signature, str) or not signature:
                continue
            if not isinstance(raw_links, list):
                continue
            links = [link for link in raw_links if isinstance(link, str) and link.startswith("https://")]
            status = task.get("status")
            if status is not None and status not in self.TASK_STATUSES:
                raise FlyerAPIError(f"Flyer вернул неизвестный статус задания: {status}")
            tasks.append({"signature": signature, "links": links, "status": status})
        return tasks

    async def check_task(self, signature: str) -> str | None:
        data = await self._post("check_task", {"signature": signature})
        status = data.get("result")
        if status is not None and status not in self.TASK_STATUSES:
            raise FlyerAPIError(f"Flyer вернул неизвестный статус задания: {status}")
        return status