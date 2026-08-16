from __future__ import annotations

from typing import Any

import httpx


class SovereignAgentsHttpClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _url(self, value: str) -> str:
        return value if value.startswith("https://") else self.base_url + value

    def get_text(self, url: str) -> str:
        response = httpx.get(self._url(url), timeout=self.timeout, follow_redirects=False)
        response.raise_for_status()
        return response.text

    def get_json(self, path: str) -> dict[str, Any]:
        response = httpx.get(self._url(path), timeout=self.timeout, follow_redirects=False)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Protocol JSON resource must be an object")
        return value

    def get_bytes(self, path: str) -> bytes:
        response = httpx.get(self._url(path), timeout=self.timeout, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 10_000_000:
            raise ValueError("Protocol resource is too large")
        return response.content

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(self._url(path), json=body, timeout=self.timeout, follow_redirects=False)
        response.raise_for_status()
        return response.json()
