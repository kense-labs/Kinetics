from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .physics import TRAVEL_Z, RobotWorld

PHASES = {
    "approach": "移至物体上方", "descend": "下降对准", "grasp": "闭合夹爪",
    "lift": "抬升物体", "carry": "移向目标", "lower": "降低放置",
    "release": "松开夹爪", "withdraw": "向上撤离", "recover": "张开重试",
    "touch": "驻留作业", "finish": "完成",
}

PHASE_GUIDANCE = {
    "approach": "Move the open gripper to 0.14 m above the object, aligned in XY.",
    "descend": "Move the open gripper down to the object's height, ready to grasp it.",
    "grasp": "Close the fingers around the object at the current position.",
    "lift": "Raise the held object to the travel height, keeping the same XY position.",
    "carry": "Move the held object above the destination at travel height.",
    "lower": "Lower the held object onto the destination, keeping the fingers closed.",
    "release": "Open the fingers to release the object onto its destination support.",
    "withdraw": "Raise the empty open gripper away from the placed object.",
    "recover": "Open the empty fingers after an unsuccessful grasp.",
    "touch": "Hold the TCP at the current work point with process standoff until the weld/dispense beat completes (the marker turns green).",
    "finish": "Finish the task after physical success has been verified.",
}

TRACE_TASKS = ("weld", "glue")


def _trace_phases(s):
    """焊接/涂胶(无抓取): 按序 approach -> descend -> touch(驻留) -> 换下一点。
    只读观测字典, 不碰仿真器真值(视觉策略同享此路径)。"""
    if s["success"]:
        return ["finish"]
    p = np.asarray(s["tcp"], dtype=float)
    point = np.asarray(s["object"], dtype=float)
    travel_z = float(s.get("relative_geometry", {}).get("travel_tcp_height_m", TRAVEL_Z))
    placed = list(s.get("placed") or [])
    if placed and all(placed):
        return ["withdraw"] if p[2] < travel_z - .02 else ["finish"]
    if p[2] < travel_z - .05 and np.linalg.norm(p[:2] - point[:2]) > .05:
        return ["withdraw"]
    if np.linalg.norm(p[:2] - point[:2]) > .007:
        return ["approach"]
    work_z = point[2] + float(s.get("relative_geometry", {}).get("grasp_above_m", 0.001))
    if abs(p[2] - work_z) > .006:
        return ["descend", "approach"]
    return ["touch", "lift"]


def eligible_phases(world: RobotWorld, observation=None):
    s = world.observe() if observation is None else observation
    if s.get("task_id") in TRACE_TASKS:
        return _trace_phases(s)
    p, cube, target = (np.asarray(s[key], dtype=float) for key in ("tcp", "object", "destination"))
    closed = s["gripper"] == "closed"
    travel_z = s.get("relative_geometry", {}).get("travel_tcp_height_m", TRAVEL_Z)
    near_destination = np.linalg.norm(cube[:2] - target[:2]) < .025
    if s["success"]:
        return ["finish"]
    if not closed and near_destination and s["support_contact"]:
        return ["withdraw"]
    if s["held"]:
        if np.linalg.norm(p[:2] - target[:2]) < .012:
            return ["lower", "release"] if abs(cube[2] - target[2]) < .012 else ["lower", "carry"]
        if cube[2] < travel_z - .045:
            return ["lift"]
        return ["carry", "lift"]
    if closed:
        return ["recover", "grasp"]
    # Empty open gripper sitting low and far from the active object (e.g. right
    # after placing one object of a multi-object task): climb back to travel
    # height before crossing the scene, so the diagonal blend cannot sweep
    # through trays or already-placed objects.
    if p[2] < travel_z - .05 and np.linalg.norm(p[:2] - cube[:2]) > .05:
        return ["withdraw"]
    if np.linalg.norm(p[:2] - cube[:2]) > .007:
        return ["approach"]
    # Jaw grippers settle at the object centre; the suction pad settles at the
    # grasp plane (object top), so measure against the per-spec grasp height.
    grasp_z = cube[2] + float(s.get("relative_geometry", {}).get("grasp_above_m", 0.001))
    if abs(p[2] - grasp_z) > .006:
        return ["descend", "approach"]
    return ["grasp", "approach"]


def baseline_phase(world, observation=None):
    s = world.observe() if observation is None else observation
    eligible = eligible_phases(world, s)
    if "release" in eligible and abs(s["object"][2] - s["destination"][2]) < .012:
        return "release"
    return eligible[0]


def phase_options(world, phases, observation=None):
    """Describe planned effects without recommending or dropping any offered phase."""
    options = {}
    for phase in phases:
        option = candidates(world, phase, preview=False, observation=observation)[0]
        position = world.position if observation is None else np.asarray(observation["tcp"])
        delta = np.asarray(option.target) - position
        moves = []
        for axis, value in zip(("X", "Y", "Z"), delta):
            if abs(value) >= .002:
                moves.append(f"{axis} {value:+.3f} m")
        motion = ", ".join(moves) if moves else "no TCP displacement"
        fingers = option.gripper or "unchanged"
        options[phase] = f"{PHASE_GUIDANCE[phase]} Planned change: {motion}; fingers {fingers}."
    return options


@dataclass
class Candidate:
    id: str
    label: str
    phase: str
    target: list[float] | None
    gripper: str | None
    seconds: float
    admitted: bool = True
    rejection: str | None = None
    preview: dict | None = None

    def serialise(self):
        return asdict(self)


def candidates(world, phase, preview=True, observation=None):
    state = world.observe() if observation is None else observation
    p, cube, dest = (np.asarray(state[key], dtype=float) for key in ("tcp", "object", "destination"))
    travel_z = float(state.get("relative_geometry", {}).get("travel_tcp_height_m", TRAVEL_Z))
    if not np.isfinite(travel_z) or not .02 <= travel_z <= .42:
        raise ValueError("观测中的安全搬运高度超出工作区")
    target, grip, duration = p.copy(), None, .8
    # Per-task tempo: delicate tasks (insert) stretch every phase so pendulum
    # swing and servo transients settle before the next action.
    time_scale = float(state.get("relative_geometry", {}).get("motion_time_scale", 1.0))
    if not np.isfinite(time_scale) or not .5 <= time_scale <= 3.:
        raise ValueError("观测中的动作节奏系数无效")
    if phase == "approach":
        target = cube + [0, 0, .14]
        grip = "open"
    elif phase == "descend":
        # Jaw grippers wrap the object centre; the suction pad meets the top face.
        target = cube + [0, 0, float(state.get("relative_geometry", {}).get("grasp_above_m", .001))]
    elif phase == "grasp":
        grip, duration = "close", .65
    elif phase == "lift":
        target = np.r_[p[:2], travel_z]
        duration = 1.1
    elif phase == "carry":
        target = np.r_[dest[:2] + (p - cube)[:2], travel_z]
        duration = 1.6
    elif phase == "lower":
        target = dest + (p - cube) + [0, 0, .002]
        duration = 1.2
    elif phase in {"release", "recover"}:
        grip, duration = "open", .8
    elif phase == "touch":
        # 焊接/涂胶驻留: 保持位姿一个工艺节拍, 夹爪不动
        target, duration = p.copy(), .8
    elif phase == "withdraw":
        target = np.r_[p[:2], travel_z]
        duration = 1.0
    elif phase != "finish":
        raise ValueError("Unknown phase")
    duration *= time_scale
    result = [Candidate("direct", PHASES[phase], phase, target.tolist(), grip, duration)]
    if np.linalg.norm(target - p) > .03:
        result.append(Candidate("gentle", "减速执行", phase, target.tolist(), grip, duration * 1.5))
    result.append(Candidate("hold", "保持当前位姿", phase, p.tolist(), None, .3))
    if preview:
        for option in result:
            shadow = world.clone()
            before_bad = shadow.unsafe_contacts
            initial_z = shadow.cube[2]
            try:
                for _ in shadow.motion(option.target, option.gripper, option.seconds, emit=False):
                    pass
                state = shadow.observe()
                option.preview = {"tcp": state["tcp"], "object": state["object"], "held": state["held"],
                                  "support_contact": state["support_contact"],
                                  "target_error_m": round(float(np.linalg.norm(shadow.cube - shadow.target)), 4)}
                if shadow.unsafe_contacts > before_bad:
                    option.admitted, option.rejection = False, "预演发生机械臂与台面或障碍接触"
                elif phase in {"lift", "carry"} and (observation or world.observe())["held"] \
                        and not state["held"] and not state["support_contact"]:
                    # Losing bilateral contact while the object rests on its
                    # support is a clean set-down, not a dropped grasp.
                    option.admitted, option.rejection = False, "预演丢失双侧抓取接触"
                elif phase == "carry" and not world.spec.suction and shadow.cube[2] < initial_z - .045:
                    # Jaw grippers: object sagging during carry means a failing grasp.
                    # (Suction attach is kinematic and cannot sag; depalletizing
                    # legitimately carries DOWN from a high stack.)
                    option.admitted, option.rejection = False, "预演物体下落"
            except (ValueError, RuntimeError) as exc:
                option.admitted, option.rejection = False, str(exc)
            if observation is not None and observation.get("perception"):
                # This remains an explicit simulator safety filter. Do not give
                # visual policies the oracle's predicted positions or goal error.
                option.preview = {"source": "simulator_safety_filter", "safe": option.admitted}
    return result
