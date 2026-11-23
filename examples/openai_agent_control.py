#!/usr/bin/env python3
"""Connect any OpenAI-compatible LLM (GPT / Qwen / DeepSeek / vLLM / Ollama) to control equipment.

Usage:
    export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    export OPENAI_API_KEY="sk-..."
    export OPENAI_MODEL="qwen-plus"
    python examples/openai_agent_control.py equipment/sts_crane-v0
"""
from __future__ import annotations

import json
import os
import sys

import httpx
import kense_sim


def llm_tool_policy(base_url: str, api_key: str, model: str):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def choose_action(obs: dict, info: dict) -> str:
        env_spec = obs.get("equipment_name") or obs.get("env_id")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "actuate_industrial_system",
                    "description": f"Operate {env_spec}. Goal: {obs.get('goal')}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": list(info["valid_actions"].keys())},
                        },
                        "required": ["action"],
                    },
                },
            }
        ]
        messages = [
            {
                "role": "system",
                "content": "You are an industrial automation controller. Call actuate_industrial_system with the safest progress action.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "observation": obs,
                        "valid_actions": info["valid_actions"],
                        "interlock_blocked": info["rejected_actions"],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        resp = httpx.post(
            url,
            headers=headers,
            json={"model": model, "messages": messages, "tools": tools, "tool_choice": "required"},
            timeout=30.0,
        )
        resp.raise_for_status()
        tool_call = resp.json()["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        return args["action"]

    return choose_action


def main() -> int:
    env_id = sys.argv[1] if len(sys.argv) > 1 else "equipment/sts_crane-v0"
    base_url = os.getenv("OPENAI_BASE_URL", "")
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "")

    if not (base_url and model):
        print("OPENAI_BASE_URL / OPENAI_MODEL not set — running dry-run with built-in baseline policy.")
        print("Set OPENAI_BASE_URL, OPENAI_API_KEY, and OPENAI_MODEL to use a live LLM.")
        res = kense_sim.run_episode(env_id, policy="baseline", seed=0)
    else:
        policy_fn = llm_tool_policy(base_url, api_key, model)
        res = kense_sim.run_episode(env_id, policy=policy_fn, seed=0)

    print(json.dumps({k: res[k] for k in ("env_id", "success", "steps", "total_reward", "sim_seconds")}, indent=2))
    return 0 if res["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
