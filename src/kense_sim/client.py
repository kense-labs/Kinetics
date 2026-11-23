"""HTTP REST & WebSocket SDK clients for remote industrial simulation & control."""
from __future__ import annotations

import json
from typing import Any

import httpx


class KenseSimClient:
    """Synchronous HTTP REST client matching the Gym-style `reset` / `step` / `emergency_stop` API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8090", *, timeout: float = 30.0, client: Any = None):
        self.base_url = base_url.rstrip("/")
        self._external_client = client is not None
        self._http = client if client is not None else httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        if not self._external_client:
            self._http.close()

    def __enter__(self) -> "KenseSimClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return path if self._external_client else f"{self.base_url}{path}"

    def list_environments(self, domain: str | None = None) -> list[dict[str, Any]]:
        params = {"domain": domain} if domain else {}
        resp = self._http.get(self._url("/api/v1/environments"), params=params)
        resp.raise_for_status()
        return resp.json()["environments"]

    def reset(
        self,
        env_id: str,
        *,
        seed: int = 0,
        control_mode: str = "skills",
        safety_preview: bool = True,
        strict_interlock: bool = False,
        max_steps: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload: dict[str, Any] = {
            "env_id": env_id,
            "seed": seed,
            "control_mode": control_mode,
            "safety_preview": safety_preview,
            "strict_interlock": strict_interlock,
        }
        if max_steps is not None:
            payload["max_steps"] = max_steps
        resp = self._http.post(self._url("/api/v1/env/reset"), json=payload)
        resp.raise_for_status()
        body = resp.json()
        return body["observation"], body["info"]

    def step(self, action: str | dict[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        resp = self._http.post(self._url("/api/v1/env/step"), json={"action": action})
        resp.raise_for_status()
        body = resp.json()
        return (
            body["observation"],
            float(body["reward"]),
            bool(body["terminated"]),
            bool(body["truncated"]),
            body["info"],
        )

    def policy_step(self, provider: str = "baseline", profile_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": "policy", "provider": provider}
        if profile_id:
            payload["profile_id"] = profile_id
        resp = self._http.post(self._url("/api/v1/env/step"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def emergency_stop(self, engaged: bool = True) -> dict[str, Any]:
        resp = self._http.post(self._url("/api/v1/env/estop"), json={"engaged": engaged})
        resp.raise_for_status()
        return resp.json()

    def state(self) -> dict[str, Any]:
        resp = self._http.get(self._url("/api/v1/env/state"))
        resp.raise_for_status()
        return resp.json()


class KenseWebSocketClient:
    """Async full-duplex WebSocket controller over `ws://<host>:<port>/ws/v1/control`."""

    def __init__(self, ws_url: str = "ws://127.0.0.1:8090/ws/v1/control"):
        self.ws_url = ws_url
        self._ws: Any = None

    async def __aenter__(self) -> "KenseWebSocketClient":
        import websockets

        self._ws = await websockets.connect(self.ws_url)
        # Consume initial welcome frame
        await self._ws.recv()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def send_op(self, op: str, **kwargs: Any) -> dict[str, Any]:
        await self._ws.send(json.dumps({"op": op, **kwargs}))
        raw = await self._ws.recv()
        data = json.loads(raw)
        if not data.get("ok", True):
            raise RuntimeError(data.get("error", "WebSocket command failed"))
        return data

    async def reset(self, env_id: str, seed: int = 0, **kwargs: Any) -> dict[str, Any]:
        return await self.send_op("reset", env_id=env_id, seed=seed, **kwargs)

    async def step(self, action: str | dict[str, Any]) -> dict[str, Any]:
        return await self.send_op("step", action=action)

    async def policy_step(self, provider: str = "baseline") -> dict[str, Any]:
        return await self.send_op("policy_step", provider=provider)

    async def emergency_stop(self, engaged: bool = True) -> dict[str, Any]:
        return await self.send_op("estop", engaged=engaged)
