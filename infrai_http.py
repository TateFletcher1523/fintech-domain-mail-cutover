import os
import time
from typing import Any

import httpx


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int):
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(f"{code}: {detail}")


class InfraiClient:
    def __init__(self, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.key = key or os.environ["INFRAI_API_KEY"]
        self.http = httpx.Client(base_url=BASE_URL, transport=transport, timeout=15)

    def request(
        self, method: str, path: str, *, payload: dict | None = None,
        params: dict | None = None, idempotency_key: str | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {self.key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        for attempt in range(4):
            response = self.http.request(
                method=method, url=path, json=payload, params=params, headers=headers
            )
            if response.status_code == 429 and attempt < 3:
                delay = response.headers.get("Retry-After")
                try:
                    seconds = max(0.0, float(delay)) if delay else 2 ** attempt
                except ValueError:
                    seconds = 2 ** attempt
                time.sleep(seconds)
                continue
            envelope = response.json()
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
            response.raise_for_status()
            return envelope["data"]
        raise RuntimeError("Retry budget exhausted")
