"""Unified Industrial Equipment Session + v1 External SDK REST & WebSocket Control Routes."""
from __future__ import annotations

import threading
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .comparison import resolve_model
from .equipment_sim import EQUIPMENT_SPECS, EquipmentSession
from .policies import DecisionPolicy


class EquipmentResetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    equipment_id: str = Field(default="sorting_line", min_length=1, max_length=48)
    seed: int = Field(default=0, ge=0, le=99999)
    provider: Literal["baseline", "jev", "minicpm", "local", "chat", "claude"] = "baseline"
    profile_id: str | None = Field(default=None, min_length=1, max_length=64)
    preview: bool = True
    threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    speed: float = Field(default=1.5, ge=0.25, le=4.0)
    max_cycles: int | None = Field(default=None, ge=1, le=200)
    target: int | None = Field(default=None, ge=1, le=50)


class EquipmentControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    episode_id: str | None = Field(default=None, min_length=1, max_length=64)


class EquipmentActuateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: str = Field(min_length=1, max_length=64)
    episode_id: str | None = Field(default=None, min_length=1, max_length=64)


class EstopInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engaged: bool = True


class SdkResetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    env_id: str = Field(min_length=1, max_length=96)
    seed: int = Field(default=0, ge=0, le=99999)
    control_mode: Literal["skills", "incremental", "continuous_tcp"] = "skills"
    safety_preview: bool = True
    strict_interlock: bool = False
    max_steps: int | None = Field(default=None, ge=1, le=200)


class SdkStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["direct", "policy"] = "direct"
    action: str | dict[str, Any] | None = None
    provider: Literal["baseline", "jev", "minicpm", "local", "chat", "claude"] = "baseline"
    profile_id: str | None = Field(default=None, min_length=1, max_length=64)


def register_industrial_routes(app: FastAPI, public_result) -> None:
    from kense_sim.env import list_environments, make as make_env

    app.state.equipment_lock = threading.Lock()
    app.state.equipment_session = EquipmentSession("sorting_line")
    app.state.sdk_lock = threading.Lock()
    app.state.sdk_env = make_env("equipment/sorting_line-v0")

    def check_equip_episode(expected: str | None, session: EquipmentSession) -> None:
        if expected is not None and expected != session.id:
            raise HTTPException(409, "设备会话已被重置，请刷新状态后重试。")

    # ------------------------------------------------------------------
    # 1. Web Workbench Industrial Equipment Control Endpoints
    # ------------------------------------------------------------------
    @app.get("/api/equipment/catalog")
    def equipment_catalog():
        return public_result({
            "equipment": [
                {
                    "id": s.id,
                    "name": s.name,
                    "category": s.category,
                    "subtitle": s.subtitle,
                    "goal": s.goal,
                    "metric_name": s.metric_name,
                    "metric_unit": s.metric_unit,
                    "default_target": s.default_target,
                    "max_cycles": s.max_cycles,
                }
                for s in EQUIPMENT_SPECS.values()
            ]
        })

    @app.get("/api/equipment/state")
    def equipment_state():
        with app.state.equipment_lock:
            snap = app.state.equipment_session.snapshot()
        return public_result(snap)

    @app.post("/api/equipment/reset")
    def equipment_reset(setup: EquipmentResetInput):
        if setup.equipment_id not in EQUIPMENT_SPECS:
            raise HTTPException(422, f"未知工业装备 '{setup.equipment_id}'")
        with app.state.lock:
            try:
                selected = resolve_model(
                    setup.provider,
                    app.state.connections,
                    profile_id=setup.profile_id,
                    profiles=app.state.model_profiles,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None

        with app.state.equipment_lock:
            prev = app.state.equipment_session
            try:
                new_sess = EquipmentSession(
                    equipment_id=setup.equipment_id,
                    seed=setup.seed,
                    provider=setup.provider,
                    preview=setup.preview,
                    threshold=setup.threshold,
                    speed=setup.speed,
                    max_cycles=setup.max_cycles,
                    target=setup.target,
                    connection=selected["connection"],
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            prev.stop()
            app.state.equipment_session = new_sess
            snap = new_sess.snapshot()
        return public_result(snap)

    @app.post("/api/equipment/control/{action}")
    def equipment_control(
        action: Literal["start", "step", "pause", "stop"],
        options: EquipmentControlInput = EquipmentControlInput(),
    ):
        with app.state.equipment_lock:
            sess = app.state.equipment_session
            check_equip_episode(options.episode_id, sess)
            try:
                if action == "step":
                    if sess.status == "running":
                        sess.pause()
                    snap = sess.step_once()
                elif action == "start":
                    sess.start(single_step=False, threshold=options.threshold)
                    snap = sess.snapshot()
                elif action == "pause":
                    sess.pause()
                    snap = sess.snapshot()
                else:
                    sess.stop()
                    snap = sess.snapshot()
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
        return public_result(snap)

    @app.post("/api/equipment/actuate")
    def equipment_actuate(payload: EquipmentActuateInput):
        with app.state.equipment_lock:
            sess = app.state.equipment_session
            check_equip_episode(payload.episode_id, sess)
            if sess.status == "running":
                sess.pause()
            try:
                snap = sess.actuate_manual(payload.action)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        return public_result(snap)

    @app.post("/api/equipment/estop")
    def equipment_estop(payload: EstopInput):
        with app.state.equipment_lock:
            snap = app.state.equipment_session.set_estop(payload.engaged)
        return public_result(snap)

    @app.get("/api/equipment/export")
    def equipment_export():
        with app.state.equipment_lock:
            sess = app.state.equipment_session
            data = sess.export()
        return JSONResponse(
            public_result(data),
            headers={"Content-Disposition": f'attachment; filename="kense-equipment-{sess.id}.json"'},
        )

    # ------------------------------------------------------------------
    # 2. Standardized v1 External Model / Agent SDK REST Endpoints
    # ------------------------------------------------------------------
    @app.get("/api/v1/environments")
    def sdk_list_environments(domain: Literal["mujoco", "equipment"] | None = Query(default=None)):
        return public_result({
            "protocol": "kense.industrial.v1",
            "environments": list_environments(domain=domain),
        })

    @app.post("/api/v1/env/reset")
    def sdk_env_reset(payload: SdkResetInput):
        with app.state.sdk_lock:
            try:
                env = make_env(
                    payload.env_id,
                    seed=payload.seed,
                    control_mode=payload.control_mode,
                    safety_preview=payload.safety_preview,
                    strict_interlock=payload.strict_interlock,
                    max_steps=payload.max_steps,
                )
                obs, info = env.reset(seed=payload.seed)
                app.state.sdk_env = env
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return public_result({
                "env_id": env.spec.env_id,
                "observation": obs,
                "info": info,
                "openai_tools": env.to_openai_tools(),
            })

    @app.post("/api/v1/env/step")
    def sdk_env_step(payload: SdkStepInput):
        policy_obj: DecisionPolicy | None = None
        try:
            with app.state.sdk_lock:
                env = app.state.sdk_env
                decision_meta = None
                if payload.mode == "policy" or payload.action is None:
                    info_now = env.action_info()
                    valid = info_now.get("valid_actions") or {}
                    if not valid:
                        raise HTTPException(409, "当前无可用动作（可能处于急停或已完工）")
                    base = info_now.get("baseline_action") or next(iter(valid))
                    if payload.provider == "baseline":
                        chosen_action: str | dict[str, Any] = base
                        decision_meta = {"choice": base, "provider": "baseline", "model_call": False}
                    else:
                        with app.state.lock:
                            selected = resolve_model(
                                payload.provider,
                                app.state.connections,
                                profile_id=payload.profile_id,
                                profiles=app.state.model_profiles,
                            )
                        policy_obj = DecisionPolicy(payload.provider, selected["connection"])
                        decision_meta = policy_obj.choose(
                            env.observe(),
                            f"Control '{env.spec.name}' toward goal: {env.spec.goal}",
                            valid,
                            base,
                            [],
                        )
                        chosen_action = decision_meta["choice"]
                else:
                    chosen_action = payload.action

                try:
                    obs, reward, terminated, truncated, info = env.step(chosen_action)
                except Exception as exc:
                    raise HTTPException(422, str(exc)) from None

                return public_result({
                    "env_id": env.spec.env_id,
                    "observation": obs,
                    "reward": reward,
                    "terminated": terminated,
                    "truncated": truncated,
                    "info": info,
                    "decision": decision_meta,
                    "openai_tools": env.to_openai_tools(),
                })
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        finally:
            if policy_obj is not None:
                policy_obj.close()

    @app.post("/api/v1/env/estop")
    def sdk_env_estop(payload: EstopInput):
        with app.state.sdk_lock:
            res = app.state.sdk_env.emergency_stop(payload.engaged)
            obs = app.state.sdk_env.observe()
            info = app.state.sdk_env.action_info()
        return public_result({**res, "observation": obs, "info": info})

    @app.get("/api/v1/env/state")
    def sdk_env_state():
        with app.state.sdk_lock:
            env = app.state.sdk_env
            return public_result({
                "env_id": env.spec.env_id,
                "steps": env.steps,
                "max_steps": env.max_steps,
                "estop": env.estop,
                "observation": env.observe(),
                "info": env.action_info(),
                "openai_tools": env.to_openai_tools(),
            })

    # ------------------------------------------------------------------
    # 3. Real-Time Full-Duplex WebSocket Control Channel (`/ws/v1/control`)
    # ------------------------------------------------------------------
    @app.websocket("/ws/v1/control")
    async def ws_control(ws: WebSocket):
        origin = ws.headers.get("origin")
        host_port = ws.url.port
        allowed_origins = {
            f"http://127.0.0.1:{host_port}",
            f"http://localhost:{host_port}",
            "http://127.0.0.1",
            "http://localhost",
        }
        if origin and origin not in allowed_origins:
            await ws.close(code=1008)
            return

        await ws.accept()
        ws_env = make_env("equipment/sorting_line-v0")
        await ws.send_json({
            "ok": True,
            "protocol": "kense.industrial.ws.v1",
            "env_id": ws_env.spec.env_id,
        })
        try:
            while True:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    await ws.send_json({"ok": False, "error": "Message must be a JSON object"})
                    continue
                op = msg.get("op")
                try:
                    if op == "list":
                        await ws.send_json({"ok": True, "op": "list", "environments": list_environments(msg.get("domain"))})
                    elif op == "reset":
                        ws_env = make_env(
                            str(msg.get("env_id", "equipment/sorting_line-v0")),
                            seed=int(msg.get("seed", 0)),
                            control_mode=str(msg.get("control_mode", "skills")),
                            safety_preview=bool(msg.get("safety_preview", True)),
                            strict_interlock=bool(msg.get("strict_interlock", False)),
                        )
                        obs, info = ws_env.reset(seed=int(msg.get("seed", 0)))
                        await ws.send_json(public_result({
                            "ok": True,
                            "op": "reset",
                            "env_id": ws_env.spec.env_id,
                            "observation": obs,
                            "info": info,
                        }))
                    elif op == "step":
                        obs, reward, terminated, truncated, info = ws_env.step(msg.get("action"))
                        await ws.send_json(public_result({
                            "ok": True,
                            "op": "step",
                            "observation": obs,
                            "reward": reward,
                            "terminated": terminated,
                            "truncated": truncated,
                            "info": info,
                        }))
                    elif op == "policy_step":
                        info_now = ws_env.action_info()
                        valid = info_now.get("valid_actions") or {}
                        if not valid:
                            raise ValueError("No valid actions available")
                        base = info_now.get("baseline_action") or next(iter(valid))
                        prov = str(msg.get("provider", "baseline"))
                        if prov == "baseline":
                            act = base
                        else:
                            with app.state.lock:
                                sel = resolve_model(prov, app.state.connections, profiles=app.state.model_profiles)
                            pol = DecisionPolicy(prov, sel["connection"])
                            try:
                                act = pol.choose(ws_env.observe(), ws_env.spec.goal, valid, base, [])["choice"]
                            finally:
                                pol.close()
                        obs, reward, terminated, truncated, info = ws_env.step(act)
                        await ws.send_json(public_result({
                            "ok": True,
                            "op": "policy_step",
                            "action": act,
                            "observation": obs,
                            "reward": reward,
                            "terminated": terminated,
                            "truncated": truncated,
                            "info": info,
                        }))
                    elif op == "estop":
                        res = ws_env.emergency_stop(bool(msg.get("engaged", True)))
                        await ws.send_json(public_result({
                            "ok": True,
                            "op": "estop",
                            **res,
                            "observation": ws_env.observe(),
                            "info": ws_env.action_info(),
                        }))
                    elif op == "state":
                        await ws.send_json(public_result({
                            "ok": True,
                            "op": "state",
                            "env_id": ws_env.spec.env_id,
                            "observation": ws_env.observe(),
                            "info": ws_env.action_info(),
                        }))
                    else:
                        await ws.send_json({"ok": False, "error": f"Unknown op '{op}'"})
                except Exception as exc:
                    await ws.send_json(public_result({"ok": False, "op": op, "error": str(exc)}))
        except WebSocketDisconnect:
            return
