"""End-to-end test suite for Kense Industrial Sim SDK, safety interlocks, REST/WS APIs, and CAD-only catalog."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from embodied_jev.equipment_sim import EQUIPMENT_SPECS
from embodied_jev.policies import DecisionPolicy
from embodied_jev.server import create_app
import kense_sim
from kense_sim import KenseSimClient, SafetyInterlockError


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REAL_CAD_EQUIPMENT = {"sorting_line", "forklift", "kr210", "robot_cell", "voron_printer"}


def test_only_genuine_cad_equipment_registered():
    assert set(EQUIPMENT_SPECS) == EXPECTED_REAL_CAD_EQUIPMENT


@pytest.mark.parametrize("equipment_id", sorted(EQUIPMENT_SPECS))
def test_all_industrial_equipment_complete_closed_loop(equipment_id: str):
    res = kense_sim.run_episode(f"equipment/{equipment_id}-v0", policy="baseline", seed=0)
    assert res["success"] is True
    assert res["truncated"] is False
    assert res["final_observation"]["interlock_trips"] == 0
    assert res["final_observation"]["completed"] >= res["final_observation"]["target"]


@pytest.mark.parametrize(
    "env_id",
    [
        "mujoco/panda-insert-v0",
        "mujoco/ur5e-weld-v0",
        "mujoco/xarm7-palletize-v0",
        "mujoco/gen3-glue-v0",
    ],
)
def test_mujoco_industrial_arms_via_unified_gym_sdk(env_id: str):
    res = kense_sim.run_episode(env_id, policy="baseline", seed=0)
    assert res["success"] is True
    assert res["final_observation"]["unsafe_contacts"] == 0


def test_mujoco_incremental_and_continuous_tcp_modes():
    env_inc = kense_sim.make("mujoco/panda-transfer-v0", control_mode="incremental")
    obs, info = env_inc.reset(seed=0)
    assert info["admitted_actions"]
    obs2, _, _, _, info2 = env_inc.step(info["baseline_action"])
    assert info2["interlock_rejected"] is False
    assert isinstance(obs2["tcp"], list)

    env_tcp = kense_sim.make("mujoco/panda-transfer-v0", control_mode="continuous_tcp")
    obs, _ = env_tcp.reset(seed=0)
    target = [obs["tcp"][0], obs["tcp"][1], min(0.28, obs["tcp"][2] + 0.03)]
    obs3, _, _, _, info3 = env_tcp.step({"target_tcp": target, "gripper": "open", "seconds": 0.4})
    assert info3["interlock_rejected"] is False
    assert obs3["unsafe_contacts"] == 0


def test_equipment_safety_interlocks_and_estop():
    # 1. Forklift high-mast travel interlock
    env = kense_sim.make("equipment/forklift-v0", seed=0, strict_interlock=False)
    env.reset(seed=0)
    env.step("drive_to_dock")
    env.step("engage_and_tilt")
    env.step("transport_to_rack")
    env.step("elevate_to_beam")  # Mast is now at 1.10m (>= 0.18m)
    obs, reward, term, _, info = env.step("drive_to_dock")
    assert info["interlock_rejected"] is True
    assert "高位禁行" in info["rejection_reason"]
    assert reward < 0
    assert term is False

    # 2. Voron 2.4 cold-extrusion interlock in strict mode
    env_strict = kense_sim.make("equipment/voron_printer-v0", seed=0, strict_interlock=True)
    env_strict.reset(seed=0)
    with pytest.raises(SafetyInterlockError, match="防冷挤出"):
        env_strict.step("extrude_part_layers")

    # 3. Hardware Emergency Stop interlock
    env.emergency_stop(True)
    _, _, _, _, estop_info = env.step("place_and_lower")
    assert estop_info["interlock_rejected"] is True
    assert estop_info["estop"] is True
    env.emergency_stop(False)
    _, _, _, _, ok_info = env.step("place_and_lower")
    assert ok_info["interlock_rejected"] is False


def test_openai_tool_schema_and_custom_callable_agent():
    env = kense_sim.make("equipment/sorting_line-v0", seed=1)
    _, info = env.reset(seed=1)
    tools = env.to_openai_tools()
    assert len(tools) == 1
    fn = tools[0]["function"]
    assert fn["name"] == "actuate_industrial_system"
    assert set(fn["parameters"]["properties"]["action"]["enum"]) == set(info["valid_actions"])

    prompt = env.build_decision_prompt()
    assert "sorting_line" in prompt["user"]

    res = kense_sim.run_episode(env, policy=lambda _obs, inf: inf["baseline_action"], seed=1)
    assert res["success"] is True


def test_mocked_chat_decision_model_drives_industrial_equipment(monkeypatch):
    secret = "sk-industrial-secret-do-not-leak"

    def fake_post(url, **kwargs):
        payload = kwargs["json"]
        user_msg = json.loads(next(m["content"] for m in payload["messages"] if m["role"] == "user"))
        criteria = list(user_msg["decision"]["criteria"].keys())
        obs = user_msg["state"]["observation"]
        tel = obs["telemetry"]
        if obs["completed"] >= obs["target"]:
            choice = "finish"
        elif not tel["pallet_loaded"]:
            choice = "drive_to_dock" if tel["chassis_z_m"] > -0.4 else "engage_and_tilt"
        elif tel["chassis_z_m"] < 0.4:
            choice = "transport_to_rack"
        else:
            choice = "elevate_to_beam" if tel["fork_lift_m"] < 0.95 else "place_and_lower"
        assert choice in criteria
        body = {
            "model": "qwen-industrial-planner",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"choice": choice})}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8},
        }
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(DecisionPolicy, "_post", staticmethod(fake_post))
    conn = {"url": "https://api.example.invalid/v1/chat/completions", "model": "qwen-industrial-planner", "key": secret, "json_mode": True}
    res = kense_sim.run_episode("equipment/forklift-v0", policy="chat", seed=0, connection=conn)
    assert res["success"] is True
    assert secret not in json.dumps(res)


def test_rest_sdk_client_and_equipment_workbench_endpoints():
    with TestClient(create_app()) as tc:
        cat = tc.get("/api/equipment/catalog")
        assert cat.status_code == 200
        assert len(cat.json()["equipment"]) == 5

        rst = tc.post("/api/equipment/reset", json={"equipment_id": "kr210", "seed": 0})
        assert rst.status_code == 200
        ep_id = rst.json()["id"]

        bad = tc.post("/api/equipment/actuate", json={"action": "spot_weld_cycle", "episode_id": ep_id})
        assert bad.status_code == 422
        assert "夹具" in bad.json()["detail"]

        st = tc.post("/api/equipment/control/step", json={"episode_id": ep_id})
        assert st.status_code == 200
        assert st.json()["cycles"] == 1

        tc.post("/api/equipment/estop", json={"engaged": True})
        blocked_step = tc.post("/api/equipment/control/step", json={"episode_id": ep_id})
        assert blocked_step.status_code == 409
        tc.post("/api/equipment/estop", json={"engaged": False})

        exp = tc.get("/api/equipment/export")
        assert exp.status_code == 200
        assert exp.json()["schema"] == "kense.industrial.equipment_episode.v1"

        sdk = KenseSimClient(client=tc)
        envs = sdk.list_environments(domain="equipment")
        assert len(envs) == 5
        obs, info = sdk.reset("equipment/voron_printer-v0", seed=0)
        assert obs["equipment_id"] == "voron_printer"
        _, _, _, _, info2 = sdk.step(info["baseline_action"])
        assert info2["interlock_rejected"] is False
        pol = sdk.policy_step(provider="baseline")
        assert pol["observation"]["sim_seconds"] > 0


def test_websocket_full_duplex_control_and_origin_guard():
    app = create_app()
    with TestClient(app) as tc:
        with pytest.raises(Exception):
            with tc.websocket_connect("/ws/v1/control", headers={"Origin": "https://evil.example"}):
                pass

        with tc.websocket_connect("/ws/v1/control") as ws:
            hello = ws.receive_json()
            assert hello["ok"] is True
            assert hello["protocol"] == "kense.industrial.ws.v1"

            ws.send_json({"op": "reset", "env_id": "equipment/voron_printer-v0", "seed": 0})
            r_reset = ws.receive_json()
            assert r_reset["ok"] is True
            assert r_reset["observation"]["equipment_id"] == "voron_printer"

            while True:
                ws.send_json({"op": "policy_step", "provider": "baseline"})
                step_msg = ws.receive_json()
                assert step_msg["ok"] is True
                if step_msg["terminated"] or step_msg["truncated"]:
                    assert step_msg["terminated"] is True
                    break


def test_strict_cad_only_assets_curated():
    twin_dir = REPO_ROOT / "frontend" / "public" / "twin-assets"
    glbs = {p.name for p in twin_dir.glob("*.glb")}
    expected_glbs = {f"{eid}.glb" for eid in EXPECTED_REAL_CAD_EQUIPMENT}
    assert glbs == expected_glbs
    assert (twin_dir / "robots" / "panda" / "model.xml").exists()
    assert not (REPO_ROOT / "frontend" / "twin" / "builders").exists()
