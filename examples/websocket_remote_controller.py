#!/usr/bin/env python3
"""Full-duplex WebSocket industrial equipment controller example.

Start the server first:
    kense-sim serve --port 8090

Then run this remote controller:
    python examples/websocket_remote_controller.py
"""
from __future__ import annotations

import asyncio

from kense_sim import KenseWebSocketClient


async def main() -> None:
    ws_url = "ws://127.0.0.1:8090/ws/v1/control"
    async with KenseWebSocketClient(ws_url) as ctrl:
        state = await ctrl.reset("equipment/sorting_line-v0", seed=0)
        print("Connected ->", state["env_id"], "| Goal:", state["observation"]["goal"])
        while True:
            step = await ctrl.policy_step(provider="baseline")
            obs = step["observation"]
            print(
                f"  action={step['action']:<18} completed={obs['completed']}/{obs['target']} "
                f"sim_s={obs['sim_seconds']}s"
            )
            if step["terminated"] or step["truncated"]:
                print("Episode finished: success =", step["terminated"])
                break


if __name__ == "__main__":
    asyncio.run(main())
