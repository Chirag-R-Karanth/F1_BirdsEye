from __future__ import annotations
import asyncio
import os
from typing import Any
import httpx

BASE = "https://api.openf1.org/v1"
TOKEN_URL = "https://api.openf1.org/token"

class OpenF1Error(RuntimeError):
    pass

class OpenF1Client:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=30, headers={"accept": "application/json"})
        self.token: str | None = None
        self.token_expires = 0.0
        self.username = os.getenv("OPENF1_USER")
        self.password = os.getenv("OPENF1_PASS")
        self._sem = asyncio.Semaphore(3)

    async def close(self) -> None:
        await self.client.aclose()

    async def authenticate(self) -> None:
        if not self.username or not self.password:
            raise OpenF1Error("OPENF1_USER and OPENF1_PASS are required for live mode")
        r = await self.client.post(TOKEN_URL, data={"username": self.username, "password": self.password})
        if r.status_code != 200:
            raise OpenF1Error(f"OpenF1 authentication failed: {r.status_code} - {r.text[:300]}")
        data = r.json()
        self.token = data["access_token"]
        self.token_expires = asyncio.get_running_loop().time() + float(data.get("expires_in", 3600)) - 60

    async def _headers(self) -> dict[str, str]:
        if self.token is None or asyncio.get_running_loop().time() >= self.token_expires:
            await self.authenticate()
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, endpoint: str, params: dict[str, Any] | None = None, auth: bool = False) -> list[dict[str, Any]]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        async with self._sem:
            for attempt in range(4):
                try:
                    headers = await self._headers() if auth else None
                    r = await self.client.get(f"{BASE}/{endpoint.lstrip('/')}", params=params, headers=headers)
                    if r.status_code == 401 and auth:
                        self.token = None
                        continue
                    if r.status_code == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    return data if isinstance(data, list) else [data]
                except (httpx.HTTPError, OpenF1Error):
                    if attempt == 3:
                        raise
                    await asyncio.sleep(0.75 * (attempt + 1))
        return []
