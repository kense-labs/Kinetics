"""Unified Gym-style industrial simulation & decision-control environments.

Bridges both MuJoCo 3D physics robotic arms (Panda, OpenArm, UR5e, xArm7, Kinova Gen3)
and 11 industrial equipment digital twins (sorting line, STS crane, forklift, tower crane,
AS/RS stacker crane, KR210, iiwa cell, AGV truck, wind turbine, planetary gearbox,
and dark-factory floor) behind one standardized observation-interlock-actuation API.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

import numpy as np

from embodied_jev.equipment_sim import EQUIPMENT_SPECS, EquipmentWorld
from embodied_jev.incremental import baseline_choice as inc_baseline, incremental_candidates
from embodied_jev.physics import ROBOTS, TASKS, RobotWorld
from embodied_jev.planning import (
    PHASES,
    PHASE_GUIDANCE,
    baseline_phase,
    candidates as skill_candidates,
    eligible_phases,
)
from embodied_jev.policies import DecisionPolicy


class SafetyInterlockError(RuntimeError):
    """Raised when an action violates a physical or process safety interlock in strict mode."""


@dataclass(frozen=True)
class EnvSpec:
    env_id: str
    domain: str           # "mujoco" | "equipment"
    system_id: str        # robot id or equipment id
    task_id: str
    name: str
    goal: str
    max_steps: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "env_id": self.env_id,
            "domain": self.domain,
            "system_id": self.system_id,
            "task_id": self.task_id,
            "name": self.name,
            "goal": self.goal,
            "max_steps": self.max_steps,
        }


def build_registry() -> dict[str, EnvSpec]:
    reg: dict[str, EnvSpec] = {}
    for robot_id, rspec in ROBOTS.items():
        for task_id in rspec.tasks:
            tinfo = TASKS[task_id]
            eid = f"mujoco/{robot_id}-{task_id}-v0"
            reg[eid] = EnvSpec(
                env_id=eid,
                domain="mujoco",
                system_id=robot_id,
                task_id=task_id,
                name=f"{rspec.display} · {tinfo['name']}",
                goal=tinfo["goal"],
                max_steps=int(tinfo.get("max_cycles", 36)),
            )
    for eq_id, espec in EQUIPMENT_SPECS.items():
        eid = f"equipment/{eq_id}-v0"
        reg[eid] = EnvSpec(
            env_id=eid,
            domain="equipment",
            system_id=eq_id,
            task_id="process_control",
            name=espec.name,
            goal=espec.goal,
            max_steps=espec.max_cycles,
        )
    return reg


ENV_REGISTRY: dict[str, EnvSpec] = build_registry()


def list_environments(domain: str | None = None) -> list[dict[str, Any]]:
    """Return metadata for all registered MuJoCo and industrial equipment environments."""
    items = [spec.to_dict() for spec in ENV_REGISTRY.values() if domain is None or spec.domain == domain]
    return items


class IndustrialEnv:
    """Gymnasium-compatible industrial control environment (`reset`, `step`, `emergency_stop`)."""

    def __init__(
        self,
        spec: EnvSpec,
        seed: int = 0,
        control_mode: str = "skills",
        safety_preview: bool = True,
        strict_interlock: bool = False,
        max_steps: int | None = None,
    ):
        if control_mode not in {"skills", "incremental", "continuous_tcp"}:
            raise ValueError("control_mode must be 'skills', 'incremental', or 'continuous_tcp'")
        if spec.domain == "equipment" and control_mode != "skills":
            raise ValueError("Equipment environments use discrete process-control actions (control_mode='skills')")
        self.spec = spec
        self.seed = int(seed)
        self.control_mode = control_mode
        self.safety_preview = bool(safety_preview)
        self.strict_interlock = bool(strict_interlock)
        self.max_steps = int(max_steps or spec.max_steps)
        self.steps = 0
        self.estop = False
        self.robot_world: RobotWorld | None = None
        self.equip_world: EquipmentWorld | None = None
        self._init_world(self.seed)

    def _init_world(self, seed: int) -> None:
        self.seed = int(seed)
        self.steps = 0
        self.estop = False
        if self.spec.domain == "mujoco":
            self.robot_world = RobotWorld(self.spec.task_id, self.seed, robot=self.spec.system_id)
            self.equip_world = None
        else:
            self.equip_world = EquipmentWorld(self.spec.system_id, seed=self.seed)
            self.robot_world = None

    def reset(self, *, seed: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        self._init_world(self.seed if seed is None else int(seed))
        return self.observe(), self.action_info()

    def emergency_stop(self, engaged: bool = True) -> dict[str, Any]:
        """Engage or release hardware-style Emergency Stop interlock."""
        self.estop = bool(engaged)
        if self.equip_world is not None:
            self.equip_world.estop = self.estop
        return {"estop": self.estop, "env_id": self.spec.env_id}

    def observe(self) -> dict[str, Any]:
        if self.spec.domain == "equipment":
            assert self.equip_world is not None
            return self.equip_world.observe()
        assert self.robot_world is not None
        raw = self.robot_world.observe()
        return {
            "domain": "mujoco",
            "env_id": self.spec.env_id,
            "robot_id": self.spec.system_id,
            "task_id": self.spec.task_id,
            "goal": self.spec.goal,
            "estop": self.estop,
            "unsafe_contacts": int(self.robot_world.unsafe_contacts),
            **raw,
        }

    def action_info(self) -> dict[str, Any]:
        """Compute currently offered actions, safety-admitted actions, rejections, and baseline."""
        if self.estop:
            return {
                "estop": True,
                "valid_actions": {},
                "admitted_actions": [],
                "rejected_actions": {"*": "E-Stop engaged"},
                "baseline_action": None,
            }

        if self.spec.domain == "equipment":
            assert self.equip_world is not None
            cands = self.equip_world.candidates(preview=self.safety_preview)
            valid = {c.id: f"{c.label} — {c.description}" for c in cands if c.admitted}
            rejected = {c.id: c.rejection for c in cands if not c.admitted and c.rejection}
            base = self.equip_world.baseline_action()
            return {
                "estop": False,
                "valid_actions": valid,
                "admitted_actions": list(valid),
                "rejected_actions": rejected,
                "baseline_action": base if base in valid else (next(iter(valid), None)),
                "candidates": [c.serialise() for c in cands],
            }

        assert self.robot_world is not None
        obs = self.robot_world.observe()
        if self.control_mode == "incremental":
            opts = incremental_candidates(obs)
            valid = {
                o.id: f"{o.label} (target={np.round(o.target, 4).tolist()}, gripper={o.gripper or 'keep'})"
                for o in opts if o.admitted
            }
            rejected = {o.id: o.rejection for o in opts if not o.admitted and o.rejection}
            base = inc_baseline(obs, opts)
            return {
                "estop": False,
                "control_mode": "incremental",
                "valid_actions": valid,
                "admitted_actions": list(valid),
                "rejected_actions": rejected,
                "baseline_action": base,
            }

        if self.control_mode == "continuous_tcp":
            return {
                "estop": False,
                "control_mode": "continuous_tcp",
                "schema": {
                    "target_tcp": "[x_m, y_m, z_m]",
                    "gripper": "'open' | 'close' | null",
                    "seconds": "float (0.2 .. 3.0)",
                },
                "valid_actions": {"continuous_tcp": "Direct Cartesian TCP setpoint dict"},
                "admitted_actions": ["continuous_tcp"],
                "rejected_actions": {},
                "baseline_action": None,
            }

        # Default 'skills' phase-level control
        phases = eligible_phases(self.robot_world, obs)
        valid: dict[str, str] = {}
        rejected: dict[str, str] = {}
        serialized_cands = []
        for ph in phases:
            if ph == "finish":
                valid["finish"] = f"{PHASES['finish']} — {PHASE_GUIDANCE['finish']}"
                continue
            opts = skill_candidates(self.robot_world.clone(), ph, preview=self.safety_preview, observation=obs)
            legal = [c for c in opts if c.admitted and c.id != "hold"]
            chosen = legal[0] if legal else opts[0]
            serialized_cands.append(chosen.serialise())
            if legal:
                valid[ph] = f"{PHASES[ph]} — {PHASE_GUIDANCE[ph]}"
            else:
                rejected[ph] = opts[0].rejection or "Safety preview rejected motion"
        base = baseline_phase(self.robot_world, obs)
        return {
            "estop": False,
            "control_mode": "skills",
            "eligible_phases": phases,
            "valid_actions": valid,
            "admitted_actions": list(valid),
            "rejected_actions": rejected,
            "baseline_action": base if base in valid else (next(iter(valid), None)),
            "candidates": serialized_cands,
        }

    def step(self, action: str | dict[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        """Execute one control action and return `(obs, reward, terminated, truncated, info)`."""
        if self.estop:
            msg = "急停联锁激活中 (E-Stop Engaged)：禁止执行动作"
            if self.strict_interlock:
                raise SafetyInterlockError(msg)
            return self.observe(), -1.0, False, False, {**self.action_info(), "interlock_rejected": True, "rejection_reason": msg}

        if self.spec.domain == "equipment":
            return self._step_equipment(action)
        return self._step_mujoco(action)

    def _step_equipment(self, action: str | dict[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        assert self.equip_world is not None
        act_id = action.get("action") if isinstance(action, dict) else action
        if not isinstance(act_id, str):
            raise ValueError("Equipment action must be an action ID string or {'action': '<id>'}")
        prev_completed = self.equip_world.completed
        try:
            obs = self.equip_world.apply_action(act_id)
        except ValueError as exc:
            if self.strict_interlock:
                raise SafetyInterlockError(str(exc)) from exc
            info = self.action_info()
            info.update(interlock_rejected=True, rejection_reason=str(exc), attempted_action=act_id)
            return self.observe(), -0.5, False, self.steps >= self.max_steps, info

        self.steps += 1
        delta_progress = self.equip_world.completed - prev_completed
        terminated = self.equip_world.success()
        truncated = not terminated and self.steps >= self.max_steps
        reward = float(delta_progress) + (2.0 if terminated else -0.02)
        info = self.action_info()
        info.update(interlock_rejected=False, executed_action=act_id, step=self.steps)
        return obs, reward, terminated, truncated, info

    def _step_mujoco(self, action: str | dict[str, Any]) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        assert self.robot_world is not None
        obs_before = self.robot_world.observe()
        placed_before = sum(bool(x) for x in (obs_before.get("placed") or []))

        try:
            if isinstance(action, dict) and "target_tcp" in action:
                target = [float(v) for v in action["target_tcp"]]
                if len(target) != 3 or not all(np.isfinite(target)):
                    raise ValueError("target_tcp must be 3 finite coordinates [x, y, z]")
                gripper = action.get("gripper")
                seconds = float(action.get("seconds", 0.8))
                if not 0.1 <= seconds <= 4.0:
                    raise ValueError("seconds must be in [0.1, 4.0]")
                if self.safety_preview:
                    shadow = self.robot_world.clone()
                    bad0 = shadow.unsafe_contacts
                    for _ in shadow.motion(target, gripper, seconds, emit=False):
                        pass
                    if shadow.unsafe_contacts > bad0:
                        raise ValueError("预演检测到机械臂与台面/障碍物发生碰撞，安全联锁已拦截该位姿")
                bad0 = self.robot_world.unsafe_contacts
                for _ in self.robot_world.motion(target, gripper, seconds, emit=False):
                    if self.robot_world.unsafe_contacts > bad0:
                        raise ValueError("执行期检测到碰撞接触，已紧急中止")
                executed_id = "continuous_tcp"

            elif self.control_mode == "incremental":
                act_id = action.get("action") if isinstance(action, dict) else action
                opts = {o.id: o for o in incremental_candidates(obs_before)}
                if act_id not in opts:
                    raise ValueError(f"Unknown incremental action '{act_id}'")
                chosen = opts[act_id]
                if not chosen.admitted:
                    raise ValueError(chosen.rejection or "Action outside workspace bounds")
                bad0 = self.robot_world.unsafe_contacts
                for _ in self.robot_world.motion(chosen.target, chosen.gripper, chosen.seconds, emit=False):
                    if self.robot_world.unsafe_contacts > bad0:
                        raise ValueError("执行期检测到碰撞接触")
                executed_id = str(act_id)

            else:
                act_id = action.get("action") if isinstance(action, dict) else action
                if not isinstance(act_id, str):
                    raise ValueError("Skill action must be a phase string")
                if act_id == "finish":
                    if not self.robot_world.success():
                        raise ValueError("物理完工条件尚未满足，不能执行 finish")
                    self.steps += 1
                    obs_after = self.observe()
                    info = self.action_info()
                    info.update(interlock_rejected=False, executed_action="finish", step=self.steps)
                    return obs_after, 2.0, True, False, info

                opts = skill_candidates(self.robot_world.clone(), act_id, preview=self.safety_preview, observation=obs_before)
                legal = [c for c in opts if c.admitted and c.id != "hold"]
                if not legal:
                    reason = opts[0].rejection if opts else "无可用安全动作"
                    raise ValueError(reason or "安全预演拦截了该阶段动作")
                chosen = legal[0]
                bad0 = self.robot_world.unsafe_contacts
                for _ in self.robot_world.motion(chosen.target, chosen.gripper, chosen.seconds, emit=False):
                    if self.robot_world.unsafe_contacts > bad0:
                        raise ValueError("执行期检测到碰撞接触，已停止")
                executed_id = act_id

        except ValueError as exc:
            if self.strict_interlock:
                raise SafetyInterlockError(str(exc)) from exc
            info = self.action_info()
            info.update(interlock_rejected=True, rejection_reason=str(exc), attempted_action=action)
            return self.observe(), -0.5, False, self.steps >= self.max_steps, info

        self.steps += 1
        obs_after = self.observe()
        placed_after = sum(bool(x) for x in (obs_after.get("placed") or []))
        terminated = bool(self.robot_world.success())
        truncated = not terminated and self.steps >= self.max_steps
        reward = float(placed_after - placed_before) + (2.0 if terminated else -0.02)
        info = self.action_info()
        info.update(interlock_rejected=False, executed_action=executed_id, step=self.steps)
        return obs_after, reward, terminated, truncated, info

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Export current valid actions as an OpenAI Function-Calling / Tool schema."""
        info = self.action_info()
        allowed = list(info.get("valid_actions", {}).keys())
        descriptions = "\n".join(f"- {k}: {v}" for k, v in info.get("valid_actions", {}).items())
        return [
            {
                "type": "function",
                "function": {
                    "name": "actuate_industrial_system",
                    "description": (
                        f"Execute one safety-verified control action on '{self.spec.name}'. "
                        f"Goal: {self.spec.goal}\nAvailable actions:\n{descriptions}"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": allowed,
                                "description": "Admitted industrial control action identifier.",
                            },
                            "rationale": {
                                "type": "string",
                                "maxLength": 200,
                                "description": "Brief operational reason grounded in current telemetry.",
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

    def build_decision_prompt(self) -> dict[str, str]:
        """Build a clean system + user prompt pair for any external LLM / VLA decision agent."""
        obs = self.observe()
        info = self.action_info()
        return {
            "system": (
                "You are an industrial equipment decision controller. Inspect the live telemetry and "
                "safety interlock status, and respond with JSON {\"choice\": \"<action_id>\", \"probabilities\": {...}} "
                "selecting strictly from valid_actions."
            ),
            "user": json.dumps(
                {
                    "env_id": self.spec.env_id,
                    "goal": self.spec.goal,
                    "observation": obs,
                    "valid_actions": info["valid_actions"],
                    "rejected_by_safety_interlock": info["rejected_actions"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        }


def make(
    env_id: str,
    *,
    seed: int = 0,
    control_mode: str = "skills",
    safety_preview: bool = True,
    strict_interlock: bool = False,
    max_steps: int | None = None,
) -> IndustrialEnv:
    """Instantiate a MuJoCo robot or industrial equipment environment by ID."""
    if env_id not in ENV_REGISTRY:
        # Support short aliases like "sorting_line" or "ur5e-weld"
        if f"equipment/{env_id}-v0" in ENV_REGISTRY:
            env_id = f"equipment/{env_id}-v0"
        elif f"mujoco/{env_id}-v0" in ENV_REGISTRY:
            env_id = f"mujoco/{env_id}-v0"
        else:
            raise ValueError(f"Unknown environment '{env_id}'. Call kense_sim.list_environments() to inspect valid IDs.")
    return IndustrialEnv(
        ENV_REGISTRY[env_id],
        seed=seed,
        control_mode=control_mode,
        safety_preview=safety_preview,
        strict_interlock=strict_interlock,
        max_steps=max_steps,
    )


PolicyFn = Callable[[dict[str, Any], dict[str, Any]], str | dict[str, Any]]


def run_episode(
    env: IndustrialEnv | str,
    policy: str | PolicyFn | DecisionPolicy = "baseline",
    *,
    seed: int = 0,
    connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a full closed-loop episode with 'baseline', a DecisionPolicy provider name, or custom callable."""
    instance = make(env, seed=seed) if isinstance(env, str) else env
    obs, info = instance.reset(seed=seed)
    owned_policy: DecisionPolicy | None = None
    if isinstance(policy, str) and policy != "baseline":
        owned_policy = DecisionPolicy(policy, connection)

    total_reward = 0.0
    trace: list[dict[str, Any]] = []
    terminated = False
    truncated = False

    try:
        while not (terminated or truncated):
            valid = info.get("valid_actions") or {}
            if not valid:
                break
            base = info.get("baseline_action") or next(iter(valid))
            if policy == "baseline":
                action: str | dict[str, Any] = base
            elif callable(policy):
                action = policy(obs, info)
            else:
                dp = owned_policy if owned_policy is not None else policy
                assert isinstance(dp, DecisionPolicy)
                decision = dp.choose(
                    obs,
                    f"Control '{instance.spec.name}' toward goal: {instance.spec.goal}",
                    valid,
                    base,
                    trace[-6:],
                )
                action = decision["choice"]

            obs, reward, terminated, truncated, info = instance.step(action)
            total_reward += reward
            trace.append(
                {
                    "step": instance.steps,
                    "action": action,
                    "reward": round(reward, 4),
                    "interlock_rejected": info.get("interlock_rejected", False),
                    "sim_seconds": obs.get("sim_seconds"),
                }
            )
    finally:
        if owned_policy is not None:
            owned_policy.close()

    return {
        "env_id": instance.spec.env_id,
        "domain": instance.spec.domain,
        "seed": seed,
        "success": terminated,
        "truncated": truncated,
        "steps": instance.steps,
        "total_reward": round(total_reward, 3),
        "sim_seconds": obs.get("sim_seconds"),
        "final_observation": obs,
        "trace": trace,
    }
