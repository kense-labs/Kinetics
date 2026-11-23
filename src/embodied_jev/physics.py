from __future__ import annotations

import copy
import hashlib
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

from .scenarios import SCENE_DEFAULTS, validate_scene_config

ASSETS_ROOT = Path(__file__).parent / "assets"
ASSETS = ASSETS_ROOT / "panda"  # Kept for backwards compatibility.
HOME = np.array([0, -0.45, 0, -2.15, 0, 1.75, 0.7854])
DOWN = np.diag([1., -1., -1.])
DT = 0.002
TRAVEL_Z = 0.22
BELT_SPEED = 0.15  # m/s, 输送机带速(克制的真实线速)

def _drift_on_belt(world, x_range, belt_top, axis, sign, stop_coord, pause_zone=None, spacing=0.082):
    """Kinematic belt drive: released parts ride the belt toward the end stop,
    queueing nose-to-tail (each part clamps to the one ahead). The line pauses
    while the gripper works the pick zone (metering-stop style)."""
    start = getattr(world, "start_time", None)
    if start is None or float(world.data.time) <= start:
        return  # 皮带随回合启动(初始化静置期不动)
    if pause_zone is not None:
        p = world.position
        if abs(p[0] - pause_zone[0]) < .18 and abs(p[1] - pause_zone[1]) < .18 and p[2] < .26:
            return  # 到位停线
    # 带上件按行进方向排序(前件先走)
    riders = []
    for i in range(len(world.cube_ids)):
        if (world.closed or world.attached) and world._locked_index == i:
            continue  # 夹持中的件不动
        pos = world.data.xpos[world.cube_ids[i]]
        if not (x_range[0] <= pos[0] <= x_range[1]) or abs(pos[2] - belt_top) > .035:
            continue
        riders.append((sign * float(pos[axis]), i))
    riders.sort()
    lead = sign * stop_coord
    for _, i in riders:
        pos = world.data.xpos[world.cube_ids[i]]
        qadr = world.cube_qadrs[i]
        dadr = world.cube_dofs[i]
        limit = sign * lead - spacing      # 前件尾净距
        coord = float(pos[axis])
        nxt = min(limit, sign * stop_coord) if sign > 0 else max(limit, sign * stop_coord)
        nxt = min(limit, stop_coord) if False else nxt
        target_coord = coord + sign * BELT_SPEED * DT
        if sign * (target_coord - nxt) > 0:
            target_coord = nxt
            world.data.qvel[dadr:dadr + 6] = 0
        else:
            world.data.qvel[dadr + axis] = sign * BELT_SPEED
        if sign * (coord - nxt) < 0:
            world.data.qpos[qadr + axis] = target_coord
        else:
            world.data.qvel[dadr:dadr + 6] = 0
        lead = pos[axis]  # 下一件以这件为前件

def _depalletize_tick(world):
    _drift_on_belt(world, (0.36, 0.52), 0.146, axis=1, sign=-1, stop_coord=-0.336)
    # 投放闩锁: 松手且落在带面上即永久记为已归位(随后随带运走)
    for i in range(len(world.cube_ids)):
        if i not in world._belt_latched:
            pos = world.data.xpos[world.cube_ids[i]]
            on_belt = (0.36 <= pos[0] <= 0.52) and (-0.34 <= pos[1] <= 0.05) \
                      and abs(pos[2] - 0.146) < .035 and not (world.closed or world.attached)
            if on_belt:
                world._belt_latched.add(i)
        world.placed[i] = i in world._belt_latched   # 闩锁永久保持(纸箱随带运走)

def _kitting_tick(world):
    _drift_on_belt(world, (0.40, 0.48), 0.088, axis=1, sign=+1, stop_coord=0.038,
                   pause_zone=(0.44, 0.04), spacing=0.042)

MACHINING_TIME = 2.5  # s, 卡盘加工节拍

def _tending_tick(world):
    """机床 I/O 动作链: 滑门到位开关 / 卡盘装夹 / 加工节拍 / 状态旗 / 完工改目标。"""
    m = world.model
    if not hasattr(world, "_machine"):
        world._machine = {
            "door_act": m.actuator("door_ctrl").id,
            "flag_act": [m.actuator(f"flag_ctrl_{i}").id for i in range(2)],
            "machining": [False, False], "machined": [False, False], "timer": [0.0, 0.0],
            "outbox_ids": [m.geom("outbox").id, m.geom("outbox1").id],
            "chuck_id": m.geom("support").id,
            "clamped_pose": [None, None],
            "chuck_target": np.array([.42, .16, .109]),
        }
    mc = world._machine
    tcp = world.position
    # 滑门: 到位区即开; 且只要夹持中的件目标是卡盘(装料意图明确)就提前开,
    # 否则臂速快过门速会在门口刮门(预演实测)
    in_zone = (tcp[0] > .28 and -.02 < tcp[1] < .28 and tcp[2] < .36)
    li = world._locked_index
    held_to_chuck = (li is not None and (world.closed or world.attached)
                     and np.linalg.norm(world.targets[li] - mc["chuck_target"]) < .01)
    world.data.ctrl[mc["door_act"]] = .20 if (in_zone or held_to_chuck) else 0.
    for i in range(len(world.cube_ids)):
        if mc["machined"][i]:
            continue
        pos = world.data.xpos[world.cube_ids[i]]
        in_chuck = (np.linalg.norm(pos[:2] - mc["chuck_target"][:2]) < .025
                    and abs(pos[2] - mc["chuck_target"][2]) < .012 and world.placed[i]
                    and not (world.closed or world.attached))
        if in_chuck and not mc["machining"][i]:
            mc["machining"][i] = True   # 卡盘夹紧 + 红灯(旗低位)
            mc["timer"][i] = 0.0
        if mc["machining"][i]:
            mc["timer"][i] += DT
            if mc["timer"][i] >= MACHINING_TIME:
                mc["machining"][i] = False
                mc["machined"][i] = True  # 完工: 绿灯(旗升起) + 目标改成品盒
                world.targets[i] = np.array([.33, .05 - .07 * i, .0295])
                world.support_ids[i] = mc["outbox_ids"][i]
        world.data.ctrl[mc["flag_act"][i]] = .035 if mc["machined"][i] else 0.
        # 磁力卡盘夹持保持: 件在盘面上且未被夹爪抓握时, 盘面把它钉住(防卸料抓偏带倒)
        held_now = (world.closed or world.attached) and world._locked_index == i
        if in_chuck and not held_now and not world.placed[i]:
            pass  # 还在进料/找正途中, 不夹
        elif in_chuck and not held_now:
            qadr = world.cube_qadrs[i]
            dadr = world.cube_dofs[i]
            if mc["clamped_pose"][i] is None:
                mc["clamped_pose"][i] = world.data.qpos[qadr:qadr + 7].copy()
            else:
                world.data.qpos[qadr:qadr + 7] = mc["clamped_pose"][i]
                world.data.qvel[dadr:dadr + 6] = 0
        else:
            mc["clamped_pose"][i] = None

TRACE_CFG = {
    "weld": {"dwell": 0.5, "standoff": 0.002, "xy_tol": 0.012, "z_tol": 0.008},
    "glue": {"dwell": 0.3, "standoff": 0.002, "xy_tol": 0.010, "z_tol": 0.006},
}


def _trace_tick(world):
    """焊接/涂胶共用引擎: 工装标记钉死在原位(工装件); TCP 对 active 标记
    带工艺间隙驻留满节拍即完成该点(标记变绿), 按序推进; 全部完成后
    placed 全真, 由稳定计时驱动 success。"""
    cfg = TRACE_CFG[world.task]
    if not hasattr(world, "_trace"):
        world._trace = {"pin": [None] * len(world.cube_ids),
                        "done": [False] * len(world.cube_ids),
                        "dwell": [0.0] * len(world.cube_ids)}
    tr = world._trace
    tcp = world.position
    active = world.active_index
    for i in range(len(world.cube_ids)):
        qadr, dadr = world.cube_qadrs[i], world.cube_dofs[i]
        if tr["pin"][i] is None:
            tr["pin"][i] = world.data.qpos[qadr:qadr + 7].copy()
        world.data.qpos[qadr:qadr + 7] = tr["pin"][i]
        world.data.qvel[dadr:dadr + 6] = 0
        if tr["done"][i]:
            world.placed[i] = True
            continue
        pos = world.data.xpos[world.cube_ids[i]]
        dwell_z = pos[2] + world.cube_half_z[i] + cfg["standoff"]
        if i == active and np.linalg.norm(tcp[:2] - pos[:2]) < cfg["xy_tol"] \
                and abs(tcp[2] - dwell_z) < cfg["z_tol"]:
            tr["dwell"][i] += DT
            if tr["dwell"][i] >= cfg["dwell"]:
                tr["done"][i] = True
                world.placed[i] = True
                for g in world.cube_geom_sets[i]:
                    world.model.geom_rgba[g] = (.15, .80, .40, 1.)   # 工艺确认: 焊点/胶点变绿
        else:
            tr["dwell"][i] = 0.
            world.placed[i] = False


def _palletize_tick(world):
    """码垛下线: 纸箱随带向尾端挡停积攒排队(取件区到位停线);
    码上托盘且稳定的件闩锁完工(与拆垛同一闩锁语义, 方向相反)。"""
    _drift_on_belt(world, (0.36, 0.52), 0.146, axis=1, sign=-1, stop_coord=-0.336,
                   pause_zone=(0.44, -0.32), spacing=0.092)
    for i in range(len(world.cube_ids)):
        if i not in world._belt_latched:
            pos = world.data.xpos[world.cube_ids[i]]
            tgt = world.targets[i]
            speed = np.linalg.norm(world.data.qvel[world.cube_dofs[i]:world.cube_dofs[i] + 3])
            if (np.linalg.norm(pos[:2] - tgt[:2]) < .03 and abs(pos[2] - tgt[2]) < .025
                    and speed < .05 and not (world.closed or world.attached)):
                world._belt_latched.add(i)
        world.placed[i] = i in world._belt_latched


TASK_HOOKS = {"depalletize": _depalletize_tick, "kitting": _kitting_tick, "tending": _tending_tick,
              "weld": _trace_tick, "glue": _trace_tick, "palletize": _palletize_tick}

TASKS = {
    "transfer": {"name": "搬运入盘", "goal": "把红色方块放进蓝色托盘，松开夹爪并向上撤离。", "target_z": 0.026},
    "stack": {"name": "方块堆叠", "goal": "把红色方块叠在蓝色方块上，松开夹爪并向上撤离。", "target_z": 0.060},
    "barrier": {"name": "越障搬运", "goal": "越过中间的障碍，把红色方块放进蓝色托盘，松开夹爪并撤离。", "target_z": 0.026},
    "insert": {"name": "精密插装", "goal": "把红色销轴从桌面夹起，插入黄色基座的方孔中，松开夹爪并向上撤离。", "target_z": 0.045, "time_scale": 1.8},
    "kitting": {"name": "精密摆盘", "goal": "把直振送料器上的四个精密件依次摆入防静电托盘的 2×2 料位，全部摆好后撤离。", "target_z": 0.0345, "travel_z": 0.28, "time_scale": 1.2, "max_cycles": 60, "down_yaw": 90.0},
    "depalletize": {"name": "拆垛上料", "goal": "把托盘上的三个纸箱从上到下依次搬上辊筒输送机，每次吸附顶面抓取，全部搬完后撤离。", "target_z": 0.146, "travel_z": 0.30, "time_scale": 1.6, "max_cycles": 45},
    "tending": {"name": "机床上下料", "goal": "把毛坯装入机床卡盘(滑门自动开关)，等待加工完成(红灯)，卸下成品放入成品盒，两件全部完成后撤离。", "target_z": 0.109, "time_scale": 1.25, "max_cycles": 70},
    "sort": {"name": "双物分拣", "goal": "把红色方块放进蓝色托盘、绿色方块放进黄色托盘，一次一个，全部放好后向上撤离。", "target_z": 0.026},
    "weld": {"name": "焊接打点", "goal": "工装板上的四个铜焊柱: 焊枪(TCP)依次移到每个焊柱上方, 下探到 2 毫米工艺间隙驻留打点, 焊点变绿为完成, 全部完成后撤离。", "target_z": 0.032, "grasp_above": 0.011, "travel_z": 0.26, "time_scale": 1.3, "max_cycles": 40},
    "glue": {"name": "涂胶轨迹", "goal": "壳体密封槽上的六个轨迹标记: 胶枪(TCP)按顺序下探到 2 毫米工艺间隙逐点驻留, 过点变绿, 全部完成后撤离。", "target_z": 0.028, "grasp_above": 0.005, "travel_z": 0.26, "time_scale": 1.4, "max_cycles": 50},
    "palletize": {"name": "码垛下线", "goal": "纸箱随辊筒输送机排到尾端挡停, 吸盘依次码上木托盘: 先左、后右、再叠顶, 全部码好后撤离。", "target_z": 0.16, "travel_z": 0.30, "time_scale": 1.6, "max_cycles": 45},
}


class PandaSpec:
    """The stock Franka Panda mounted at the near edge of the table."""

    tasks = ("insert", "tending", "stack", "transfer")
    # transfer 保留给 Panda: 工作台基线任务, 测试与 API 默认会话都依赖它
    # kitting excluded: Panda 从排队队列里取件时, 前件与后件接触拖带导致搬运途中
    # 滑脱(实测 preview 里件在 carry 中段掉落)——队列工况给 UR5e/Gen3
    required_finger_groups = 2
    suction = False
    grasp_above = None
    contact_bodies = {"left": "left_finger", "right": "right_finger"}
    key = "panda"
    display = "Franka Panda"
    end_effector = "平行夹爪"
    assets = ASSETS
    xml_file = "panda.xml"
    meshdir = "assets"
    model_title = "EmbodiedJev - Xingzhi"
    arm_joints = tuple(f"joint{i}" for i in range(1, 8))
    arm_actuators = tuple(f"actuator{i}" for i in range(1, 8))
    home = HOME
    backup_homes = ()
    gripper_actuator = "actuator8"
    gripper_open = 255.
    gripper_closed = 0.
    finger_joints = ("finger_joint1", "finger_joint2")
    finger_open_qpos = .04
    hand_body = "hand"
    left_finger = "left_finger"
    right_finger = "right_finger"
    forbidden_bodies = {"hand", "left_finger", "right_finger", "link5", "link6", "link7"}
    tcp_pos = "0 0 0.1034"
    wrist_cam_pos = ".045 0 .025"
    workspace_min = np.array([.20, -.32, .020])
    workspace_max = np.array([.65, .34, .42])
    initial_target = np.array([.38, -.08, TRAVEL_Z])
    down = DOWN
    travel_z = TRAVEL_Z
    external_camera = {"lookat": (.43, 0, .035), "distance": 1., "azimuth": 180., "elevation": -65.}

    def mount(self, root):
        """The Panda scene is self-contained in panda.xml; nothing to add."""


class OpenArmSpec:
    """Enactic OpenArm v1 (7-DoF humanoid arm + parallel-jaw gripper) on a pedestal.

    The vendored official MJCF (enactic/openarm_mujoco, Apache-2.0) is used
    byte-identically; every workbench adaptation lives in this class:

    * The arm is welded on a 22 cm pedestal at (0.15, 0, 0.22) so its shoulder
      (z = 0.3425 m) matches the Panda shoulder height the shared tabletop
      workspace was laid out for. A straight-down grasp with the stock joint
      limits (wrist roll ±45°) only converges across the whole workspace from
      this elevated mount (verified by a full grid sweep: max IK residual
      0.1 mm on every key task pose).
    * The grasp frame is rotated 180° about the vertical versus the Panda's
      (down = Rz(pi) · DOWN): the OpenArm wrist reaches finger-down naturally
      from its home keyframe with the opening axis along +Y; the Panda
      orientation is out of reach for the wrist limits.
    * The TCP site sits at the measured fingertip plane (hand +Z 0.0955 m).
    * Gripper semantics: finger_ctrl is a position servo on the split tendon,
      ctrlrange -0.005..0.044 — closed = -0.005 (force-biased), open = 0.044.
    """

    key = "openarm"
    display = "Enactic OpenArm"
    end_effector = "平行夹爪"
    assets = ASSETS_ROOT / "openarm"
    xml_file = "openarm.xml"
    meshdir = "meshes"
    model_title = "EmbodiedJev - Xingzhi - Enactic OpenArm"
    arm_joints = tuple(f"openarm_joint{i}" for i in range(1, 8))
    arm_actuators = tuple(f"joint{i}_ctrl" for i in range(1, 8))
    home = np.array([0, 0, 0, 1.570796, 0, 0, 0])  # official "home" keyframe
    # Deterministic restart seeds for solve_ik (never triggered on the twelve
    # key task poses from home; kept as a safety net for custom scenes).
    backup_homes = (
        np.zeros(7),
        np.array([0, -.5, 0, 1.2, 0, .5, 0]),
    )
    gripper_actuator = "finger_ctrl"
    gripper_open = .044
    gripper_closed = -.005
    finger_joints = ("openarm_finger_joint1", "openarm_finger_joint2")
    finger_open_qpos = .044
    tasks = ("sort", "stack", "transfer")
    # kitting excluded: OpenArm's ±45deg wrist + 30kp servo drops the carried
    # part on the long feeder->tray swing (documented boundary)
    required_finger_groups = 2
    suction = False
    grasp_above = None
    contact_bodies = {"left": "openarm_left_finger", "right": "openarm_right_finger"}
    hand_body = "openarm_hand"
    left_finger = "openarm_left_finger"
    right_finger = "openarm_right_finger"
    forbidden_bodies = {"openarm_hand", "openarm_left_finger", "openarm_right_finger",
                      "openarm_link5", "openarm_link6", "openarm_link7"}
    tcp_pos = "0 0 0.0955"  # measured fingertip plane of the stock fingers
    wrist_cam_pos = ".035 0 .03"
    workspace_min = np.array([.22, -.30, .020])
    workspace_max = np.array([.55, .30, .42])
    initial_target = np.array([.38, -.08, TRAVEL_Z])
    # Grasp orientation: fingers down (site -Z), opening axis +Y — the pose the
    # OpenArm wrist actually reaches from home (j7 at its +90° end).
    down = np.diag([-1., 1., -1.])
    travel_z = TRAVEL_Z
    external_camera = {"lookat": (.43, 0, .035), "distance": 1.05, "azimuth": 150., "elevation": -60.}

    mount_pos = (0.15, 0, 0.22)
    pedestal_radius = 0.048
    pedestal_half_height = 0.11

    def mount(self, root):
        """Weld the base onto the pedestal station (added to the base body, so
        the riser can never collide with itself) and record the station pose."""
        base = root.find(".//body[@name='openarm_link0']")
        base.set("pos", " ".join(map(str, self.mount_pos)))
        # The pedestal is part of the base body: a real collision column from
        # the table top up to the base plate, like OpenArm's tabletop mounts.
        ET.SubElement(base, "geom", name="openarm_pedestal", type="cylinder",
                      size=f"{self.pedestal_radius} {self.pedestal_half_height}",
                      pos=f"0 0 {-self.pedestal_half_height}", rgba=".16 .17 .19 1",
                      friction="1.2 .01 .001")


def _mount_panda_hand(root, wrist_name, pos, quat):
    """Mount the Panda parallel-jaw hand onto another arm's wrist body.

    Ports the hand subtree, its slide/tendon/equality gripper drive and the
    meshes/materials it needs, with every class and asset renamed with a ph_
    prefix so the graft can never collide with the host model's names.
    """
    panda_root = ET.parse(ASSETS / "panda.xml").getroot()
    class_map = {"visual": "ph_visual", "collision": "ph_collision", "finger": "ph_finger",
                 "fingertip_pad_collision_1": "ph_pad1", "fingertip_pad_collision_2": "ph_pad2",
                 "fingertip_pad_collision_3": "ph_pad3", "fingertip_pad_collision_4": "ph_pad4",
                 "fingertip_pad_collision_5": "ph_pad5"}
    mat_map = {"off_white": "ph_off_white", "black": "ph_black", "white": "ph_white"}
    root.find("default").append(ET.fromstring("""<default class="ph_root">
      <default class="ph_visual"><geom type="mesh" contype="0" conaffinity="0" group="2"/></default>
      <default class="ph_collision"><geom type="mesh" group="3" friction="1.8 .02 .002"/></default>
      <default class="ph_finger"><joint axis="0 1 0" type="slide" range="0 0.04" armature="0.1" damping="1"/></default>
      <default class="ph_pad1"><geom type="box" group="3" size="0.0085 0.004 0.0085" pos="0 0.0055 0.0445" friction="1.8 .02 .002" solref="0.004 1" solimp="0.95 0.99 0.001"/></default>
      <default class="ph_pad2"><geom solref="0.004 1" solimp="0.95 0.99 0.001" type="box" group="3" size="0.003 0.002 0.003" pos="0.0055 0.002 0.05" friction="1.8 .02 .002"/></default>
      <default class="ph_pad3"><geom solref="0.004 1" solimp="0.95 0.99 0.001" type="box" group="3" size="0.003 0.002 0.003" pos="-0.0055 0.002 0.05" friction="1.8 .02 .002"/></default>
      <default class="ph_pad4"><geom solref="0.004 1" solimp="0.95 0.99 0.001" type="box" group="3" size="0.003 0.002 0.0035" pos="0.0055 0.002 0.0395" friction="1.8 .02 .002"/></default>
      <default class="ph_pad5"><geom solref="0.004 1" solimp="0.95 0.99 0.001" type="box" group="3" size="0.003 0.002 0.0035" pos="-0.0055 0.002 0.0395" friction="1.8 .02 .002"/></default>
      <default class="ph_act"><general dyntype="none" biastype="affine"/></default>
    </default>"""))
    asset = root.find("asset")
    if asset is None:
        asset = ET.SubElement(root, "asset")
    for mat in panda_root.findall(".//asset/material"):
        if mat.get("name") in mat_map:
            mat.set("name", mat_map[mat.get("name")])
            if mat.get("class"):
                del mat.attrib["class"]
            asset.append(mat)
    for mesh in panda_root.findall(".//asset/mesh"):
        f = mesh.get("file") or ""
        if "hand" in f or "finger" in f:
            mesh.set("file", "panda/assets/" + f)
            mesh.set("name", "ph_" + (mesh.get("name") or f.replace("/", "_").split(".")[0]))
            asset.append(mesh)
    hand = copy.deepcopy(panda_root.find(".//body[@name='hand']"))
    hand.set("pos", pos)
    hand.set("quat", quat)
    for element in hand.iter():
        if element.get("class") in class_map:
            element.set("class", class_map[element.get("class")])
        if element.get("material") in mat_map:
            element.set("material", mat_map[element.get("material")])
        if element.get("mesh"):
            element.set("mesh", "ph_" + element.get("mesh"))
    root.find(f".//body[@name='{wrist_name}']").append(hand)
    # The grafted hand wraps around the wrist body: exclude their mutual contacts,
    # else the palm collision mesh fights the flange (measured: wrist servo rail
    # saturation and 0.3 rad droop).
    contact_root = root.find("contact")
    if contact_root is None:
        contact_root = ET.SubElement(root, "contact")
    for pair in ((wrist_name, "hand"), ("hand", "left_finger"), ("hand", "right_finger")):
        contact_root.append(ET.fromstring(f'<exclude body1="{pair[0]}" body2="{pair[1]}"/>'))
    tendon_root = root.find("tendon")
    if tendon_root is None:
        tendon_root = ET.SubElement(root, "tendon")
    tendon_root.append(ET.fromstring(
        '<fixed name="ph_split"><joint joint="finger_joint1" coef="0.5"/>'
        '<joint joint="finger_joint2" coef="0.5"/></fixed>'))
    equality_root = root.find("equality")
    if equality_root is None:
        equality_root = ET.SubElement(root, "equality")
    equality_root.append(ET.fromstring(
        '<joint joint1="finger_joint1" joint2="finger_joint2" solimp="0.95 0.99 0.001" solref="0.005 1"/>'))
    # Stronger clamp than the Panda stock tendon servo: 1.6 N default grip
    # micro-slips 80 g blanks on long carries (measured 0.7 mm/s creep).
    root.find("actuator").append(ET.fromstring(
        '<general class="ph_act" name="actuator8" tendon="ph_split" forcerange="-100 100" '
        'ctrlrange="0 255" gainprm="0.08 0 0" biasprm="0 -100 -10"/>'))


class UR5eSpec:
    """Universal Robots UR5e (Menagerie, ROS-Industrial license) + Panda parallel jaw.

    The stock UR5e ships toolless; the workbench's grasp semantics need a
    two-finger hand, so the proven Panda gripper is grafted onto the wrist_3
    flange (same mounting pattern as the G1 integration). Home/seeds were swept
    over the shared workspace: every key task pose converges to <=0.1 mm with
    the deterministic multi-restart below.
    """

    key = "ur5e"
    display = "UR5e 协作臂 + 平行夹爪"
    end_effector = "平行夹爪(嫁接)"
    assets = ASSETS_ROOT / "ur5e"
    xml_file = "ur5e.xml"
    meshdir = "assets"
    model_title = "EmbodiedJev - Xingzhi - UR5e"
    arm_joints = ("shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
                  "wrist_1_joint", "wrist_2_joint", "wrist_3_joint")
    arm_actuators = ("shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3")
    home = np.array([0, -2.2, 2.0, -1.3, -1.57, 0])          # elbow-up ready pose
    backup_homes = (np.zeros(6),
                    np.array([0, -1.57, 1.57, -1.57, -1.57, 0]),
                    np.array([0, -1.57, 1.57, -1.57, 1.57, 0]))
    gripper_actuator = "actuator8"
    gripper_open = 255.
    gripper_closed = 0.
    finger_joints = ("finger_joint1", "finger_joint2")
    finger_open_qpos = .04
    tasks = ("tending", "weld", "transfer")
    # sort excluded: the pedestal-mounted UR5e reaches the far yellow tray only
    # through table-grazing configs (IK veto rejects them; grip slips in loops)
    required_finger_groups = 2
    suction = False
    grasp_above = None
    contact_bodies = {"left": "left_finger", "right": "right_finger"}
    hand_body = "hand"
    left_finger = "left_finger"
    right_finger = "right_finger"
    forbidden_bodies = {"hand", "left_finger", "right_finger",
                        "wrist_1_link", "wrist_2_link", "wrist_3_link",
                        "forearm_link", "upper_arm_link"}
    tcp_pos = "0 0 0.1034"
    wrist_cam_pos = ".045 0 .025"
    workspace_min = np.array([.20, -.32, .020])
    workspace_max = np.array([.62, .34, .42])
    initial_target = np.array([.38, -.08, TRAVEL_Z])
    down = DOWN
    travel_z = TRAVEL_Z
    external_camera = {"lookat": (.35, 0, .18), "distance": 1.45, "azimuth": 195., "elevation": -32.}
    mount_pos = (0.05, 0, 0.25)
    pedestal_half_height = 0.125
    _robot_links = {"base", "shoulder_link", "upper_arm_link", "forearm_link",
                    "wrist_1_link", "wrist_2_link", "wrist_3_link",
                    "hand", "left_finger", "right_finger"}
    _adjacent = {frozenset(p) for p in (
        ("base", "shoulder_link"),
        ("shoulder_link", "upper_arm_link"),
        ("upper_arm_link", "forearm_link"), ("forearm_link", "wrist_1_link"),
        ("wrist_1_link", "wrist_2_link"), ("wrist_2_link", "wrist_3_link"),
        ("wrist_3_link", "hand"), ("hand", "left_finger"), ("hand", "right_finger"),
        ("left_finger", "right_finger"))}
    _proximal = {"upper_arm_link", "forearm_link"}

    def ik_pose_ok(self, model, data):
        """Veto IK solutions with self-collisions or table/cube contact on the
        proximal links. The UR5e's ±2pi wrists wrap into folded poses that pass
        naive IK but jam the forearm into the hand or the table (measured: the
        servo then fights the contact and drifts 10 cm off target)."""
        for contact in data.contact[:data.ncon]:
            if contact.dist > .0005:
                continue
            b1 = model.body(model.geom_bodyid[int(contact.geom1)]).name or ""
            b2 = model.body(model.geom_bodyid[int(contact.geom2)]).name or ""
            if b1 in self._robot_links and b2 in self._robot_links:
                if frozenset((b1, b2)) not in self._adjacent:
                    return False
                continue
            names = {model.geom(int(contact.geom1)).name or "",
                     model.geom(int(contact.geom2)).name or ""}
            robot_side = (b1 in self._robot_links) or (b2 in self._robot_links)
            if robot_side and names & {"table", "barrier", "machine_body", "fixture_boss",
                                       "conveyor_frame", "pallet_deck"}:
                return False
            if ("cube_geom" in names) and (b1 in self._proximal or b2 in self._proximal):
                return False
        return True

    def mount(self, root):
        """UR5e on a 25 cm pedestal stand at the table edge (swept: only h=0.25,
        x=0.05 keeps every key task pose reachable with zero table contacts —
        the stock elbow-up home otherwise swings the forearm through the table),
        plus the gripper graft and asset path fixes."""
        compiler = root.find("compiler")
        compiler.set("meshdir", str(ASSETS_ROOT))
        for mesh in root.findall(".//asset/mesh"):
            f = mesh.get("file")
            if f and not f.startswith(("ur5e/", "panda/")):
                mesh.set("file", "ur5e/assets/" + f)
        base = root.find(".//body[@name='base']")
        base.set("pos", " ".join(map(str, self.mount_pos)))
        ET.SubElement(base, "geom", name="ur5e_pedestal", type="cylinder",
                      size=f"0.07 {self.pedestal_half_height}",
                      pos=f"0 0 {-self.pedestal_half_height}", rgba=".16 .17 .19 1",
                      friction="1.2 .01 .001")
        _mount_panda_hand(root, "wrist_3_link", "0 0.1 0", "-0.70710678 0.70710678 0 0")  # attachment_site


class XArm7Spec:
    """UFACTORY xArm7 (Menagerie) with the stock gripper replaced by a vacuum
    suction tool for carton depalletizing.

    The suction pad is a single-contact grip: pad touch + vacuum on attaches the
    carton kinematically (same convention as the drone payload hook). The stock
    xArm gripper subtree is removed and its actuator dropped.
    """

    key = "xarm7"
    display = "xArm7 + 真空吸盘"
    end_effector = "真空吸盘"
    assets = ASSETS_ROOT / "xarm7"
    xml_file = "xarm7.xml"
    meshdir = "assets"
    model_title = "EmbodiedJev - Xingzhi - xArm7 suction"
    arm_joints = tuple(f"joint{i}" for i in range(1, 8))
    arm_actuators = tuple(f"act{i}" for i in range(1, 8))
    home = np.array([0, -0.5, -0.2, 0.6, 0, 1.2, 0])
    backup_homes = (np.zeros(7), np.array([0, -0.9, 0.3, 0.9, 0.4, 1.0, 0]))
    gripper_actuator = None
    gripper_open = 0.
    gripper_closed = 0.
    finger_joints = ()
    finger_open_qpos = 0.
    tasks = ("depalletize", "palletize")    # 真空吸盘专职物流上下线
    required_finger_groups = 0    # vacuum: no finger contacts required
    suction = True
    grasp_above = 0.039        # pad face nominal 1 mm press onto the carton top
    contact_bodies = {}        # vacuum seal is proximity-checked, not contact-counted
    hand_body = "suction_tool"
    left_finger = "suction_tool"
    right_finger = "suction_tool"
    forbidden_bodies = {"suction_tool", "link5", "link6", "link7"}
    tcp_pos = "0 0 0"          # tcp site is placed at the pad face by mount()
    wrist_cam_pos = "0 0 .12"
    workspace_min = np.array([.20, -.32, .020])
    workspace_max = np.array([.62, .34, .42])
    initial_target = np.array([.38, -.08, TRAVEL_Z])
    down = DOWN
    travel_z = TRAVEL_Z
    external_camera = {"lookat": (.40, 0, .10), "distance": 1.35, "azimuth": 175., "elevation": -40.}
    mount_pos = (0.05, 0, 0.25)
    pedestal_half_height = 0.125
    _robot_links = {"link_base", *[f"link{i}" for i in range(1, 8)], "suction_tool"}
    _adjacent = {frozenset(p) for p in (
        ("link_base", "link1"), ("link1", "link2"), ("link2", "link3"), ("link3", "link4"),
        ("link4", "link5"), ("link5", "link6"), ("link6", "link7"), ("link7", "suction_tool"))}
    _proximal = {"link2", "link3", "link4", "link5"}

    def ik_pose_ok(self, model, data):
        """Same self/table collision veto as UR5e (see UR5eSpec)."""
        for contact in data.contact[:data.ncon]:
            if contact.dist > .0005:
                continue
            b1 = model.body(model.geom_bodyid[int(contact.geom1)]).name or ""
            b2 = model.body(model.geom_bodyid[int(contact.geom2)]).name or ""
            if b1 in self._robot_links and b2 in self._robot_links:
                if frozenset((b1, b2)) not in self._adjacent:
                    return False
                continue
            robot_side = (b1 in self._robot_links) or (b2 in self._robot_links)
            names = {model.geom(int(contact.geom1)).name or "",
                     model.geom(int(contact.geom2)).name or ""}
            if robot_side and names & {"table", "barrier", "machine_body", "fixture_boss",
                                       "conveyor_frame", "pallet_deck"}:
                return False
            if ("cube_geom" in names) and (b1 in self._proximal or b2 in self._proximal):
                return False
        return True

    def mount(self, root):
        """Pedestal stand + swap the stock jaw gripper for the vacuum tool."""
        compiler = root.find("compiler")
        compiler.set("meshdir", str(ASSETS_ROOT))
        for mesh in root.findall(".//asset/mesh"):
            f = mesh.get("file")
            if f and not f.startswith("xarm7/"):
                mesh.set("file", "xarm7/assets/" + f)
        base = root.find(".//body[@name='link_base']")
        base.set("pos", " ".join(map(str, self.mount_pos)))
        ET.SubElement(base, "geom", name="xarm_pedestal", type="cylinder",
                      size=f"0.08 {self.pedestal_half_height}",
                      pos=f"0 0 {-self.pedestal_half_height}", rgba=".16 .17 .19 1",
                      friction="1.2 .01 .001")
        # tool materials (the jaw-gripper graft helper is not used here)
        asset = root.find("asset")
        if asset is None:
            asset = ET.SubElement(root, "asset")
        existing = {m.get("name") for m in asset.findall("material")}
        if "ph_black" not in existing:
            asset.append(ET.fromstring('<material name="ph_black" rgba="0.25 0.25 0.25 1" specular="0.5" shininess="0.25"/>'))
        if "ph_off_white" not in existing:
            asset.append(ET.fromstring('<material name="ph_off_white" rgba="0.901961 0.921569 0.929412 1" specular="0.5" shininess="0.25"/>'))
        link7 = root.find(".//body[@name='link7']")
        # remove the stock gripper subtree and its actuator
        gripper_base = link7.find("body[@name='xarm_gripper_base_link']")
        if gripper_base is not None:
            link7.remove(gripper_base)
        for actuator in list(root.find("actuator")):
            if (actuator.get("name") or "") == "gripper":
                root.find("actuator").remove(actuator)
        # and the stock gripper's contact-exclusion pairs
        removed = {"xarm_gripper_base_link", "left_outer_knuckle", "left_finger",
                   "left_inner_knuckle", "right_outer_knuckle", "right_finger",
                   "right_inner_knuckle"}
        contact_root = root.find("contact")
        if contact_root is not None:
            for excl in list(contact_root):
                if (excl.get("body1") in removed) or (excl.get("body2") in removed):
                    contact_root.remove(excl)
        removed_joints = {"left_driver_joint", "left_finger_joint", "left_inner_knuckle_joint",
                          "right_driver_joint", "right_finger_joint", "right_inner_knuckle_joint"}
        equality_root = root.find("equality")
        if equality_root is not None:
            for eq in list(equality_root):
                if (eq.get("joint1") in removed_joints) or (eq.get("joint2") in removed_joints) \
                        or (eq.get("body1") in removed) or (eq.get("body2") in removed):
                    equality_root.remove(eq)
        tendon_root = root.find("tendon")
        if tendon_root is not None:
            for tendon in list(tendon_root):
                if any(j.get("joint") in removed_joints for j in tendon.findall("joint")):
                    tendon_root.remove(tendon)
        # vacuum tool on the flange (link_tcp frame: pos 0 0 .172)
        tool = ET.fromstring(
            '<body name="suction_tool" pos="0 0 .172">'
            '  <inertial pos="0 0 .045" mass="0.22" diaginertia="0.0001 0.0001 0.00006"/>'
            '  <geom name="suction_flange" class="visual" type="cylinder" size="0.026 0.010" pos="0 0 0.010" material="ph_black"/>'
            '  <geom name="suction_bellows_1" class="visual" type="cylinder" size="0.020 0.012" pos="0 0 0.034" material="ph_off_white"/>'
            '  <geom name="suction_bellows_2" class="visual" type="cylinder" size="0.016 0.012" pos="0 0 0.056" material="ph_off_white"/>'
            '  <geom name="suction_pad" type="cylinder" size="0.030 0.006" pos="0 0 0.074" material="ph_black" friction="2.0 .03 .002" margin="0.002"/>'
            '  <site name="tcp" pos="0 0 0.080" size=".004" rgba="0 0 0 0"/>'
            '</body>')
        link7.append(tool)

class Gen3Spec:
    """Kinova Gen3 (Menagerie) + Panda parallel jaw: carton palletizing.

    Gen3's twist joints (1/3/5/7) are continuous (no range in MJCF) — the IK
    clip respects jnt_limited now. The stock model ships toolless; the Panda
    hand mounts at the bracelet's pinch_site. No pedestal needed: the 890 mm
    reach converges the whole workspace from the table edge.
    """

    key = "gen3"
    display = "Kinova Gen3 + 平行夹爪"
    end_effector = "平行夹爪(嫁接)"
    assets = ASSETS_ROOT / "gen3"
    xml_file = "gen3.xml"
    meshdir = "assets"
    model_title = "EmbodiedJev - Xingzhi - Kinova Gen3"
    arm_joints = tuple(f"joint_{i}" for i in range(1, 8))
    arm_actuators = tuple(f"joint_{i}" for i in range(1, 8))
    home = np.array([0, -0.5, -0.2, 0.6, 0, 1.2, 0])
    backup_homes = (np.zeros(7), np.array([0, -0.9, 0.3, 0.9, 0.4, 1.0, 0]),
                    np.array([.5, -.4, -.4, 1.2, -.3, .9, .5]))
    gripper_actuator = "actuator8"
    gripper_open = 255.
    gripper_closed = 0.
    finger_joints = ("finger_joint1", "finger_joint2")
    finger_open_qpos = .04
    tasks = ("kitting", "glue", "barrier")
    # tending excluded: cylindrical blanks roll out of flat pads during carry
    # (real shops use V-block grippers for rounds; documented boundary)
    required_finger_groups = 2
    suction = False
    grasp_above = None        # 4cm 件: 默认包心抓取(验证包络)
    contact_bodies = {"left": "left_finger", "right": "right_finger"}
    hand_body = "hand"
    left_finger = "left_finger"
    right_finger = "right_finger"
    forbidden_bodies = {"hand", "left_finger", "right_finger", "bracelet_link",
                        "spherical_wrist_1_link", "spherical_wrist_2_link", "forearm_link"}
    tcp_pos = "0 0 0.1034"
    wrist_cam_pos = ".045 0 .025"
    workspace_min = np.array([.20, -.32, .020])
    workspace_max = np.array([.62, .34, .42])
    initial_target = np.array([.38, -.08, TRAVEL_Z])
    down = DOWN
    travel_z = TRAVEL_Z
    external_camera = {"lookat": (.42, 0, .05), "distance": 1.3, "azimuth": 175., "elevation": -42.}
    _robot_links = {"base_link", "shoulder_link", "half_arm_1_link", "half_arm_2_link",
                    "forearm_link", "spherical_wrist_1_link", "spherical_wrist_2_link",
                    "bracelet_link", "hand", "left_finger", "right_finger"}
    _adjacent = {frozenset(p) for p in (
        ("base_link", "shoulder_link"), ("shoulder_link", "half_arm_1_link"),
        ("half_arm_1_link", "half_arm_2_link"), ("half_arm_2_link", "forearm_link"),
        ("forearm_link", "spherical_wrist_1_link"),
        ("spherical_wrist_1_link", "spherical_wrist_2_link"),
        ("spherical_wrist_2_link", "bracelet_link"), ("bracelet_link", "hand"),
        ("hand", "left_finger"), ("hand", "right_finger"), ("left_finger", "right_finger"))}
    _proximal = {"half_arm_1_link", "half_arm_2_link", "forearm_link"}

    def ik_pose_ok(self, model, data):
        for contact in data.contact[:data.ncon]:
            if contact.dist > .0005:
                continue
            b1 = model.body(model.geom_bodyid[int(contact.geom1)]).name or ""
            b2 = model.body(model.geom_bodyid[int(contact.geom2)]).name or ""
            if b1 in self._robot_links and b2 in self._robot_links:
                if frozenset((b1, b2)) not in self._adjacent:
                    return False
                continue
            robot_side = (b1 in self._robot_links) or (b2 in self._robot_links)
            names = {model.geom(int(contact.geom1)).name or "",
                     model.geom(int(contact.geom2)).name or ""}
            if robot_side and names & {"table", "barrier", "machine_body", "fixture_boss",
                                       "conveyor_frame", "pallet_deck"}:
                return False
            if ("cube_geom" in names) and (b1 in self._proximal or b2 in self._proximal):
                return False
        return True

    def mount(self, root):
        compiler = root.find("compiler")
        compiler.set("meshdir", str(ASSETS_ROOT))
        for mesh in root.findall(".//asset/mesh"):
            f = mesh.get("file")
            if f and not f.startswith(("gen3/", "panda/")):
                mesh.set("file", "gen3/assets/" + f)
        _mount_panda_hand(root, "bracelet_link", "0 0 -0.061525", "0 1 0 0")  # pinch_site


ROBOTS = {"panda": PandaSpec(), "openarm": OpenArmSpec(), "ur5e": UR5eSpec(), "xarm7": XArm7Spec(),
          "gen3": Gen3Spec()}
DEFAULT_ROBOT_ENV = "EMBODIED_JEV_ROBOT"


def resolve_robot(robot=None):
    if robot is None:
        robot = os.environ.get(DEFAULT_ROBOT_ENV, "panda")
    if robot not in ROBOTS:
        raise ValueError(f"Unknown robot '{robot}'; available: {sorted(ROBOTS)}")
    return ROBOTS[robot]


def build_scene(task="transfer", seed=0, scene_config=None, robot=None):
    """Compatibility wrapper: the stock single-object signature (xml, target, source)."""
    xml, targets, sources = _build_scene_parts(task, seed, scene_config, robot)
    return xml, targets[0], sources[0]


def _build_scene_parts(task="transfer", seed=0, scene_config=None, robot=None):
    spec = resolve_robot(robot)
    scene_config = validate_scene_config(task, scene_config)
    root = ET.parse(spec.assets / spec.xml_file).getroot()
    root.set("model", spec.model_title)
    root.find("compiler").set("meshdir", str(spec.assets / spec.meshdir))
    root.find("option").set("timestep", str(DT))
    root.remove(root.find("keyframe"))
    spec.mount(root)
    hand = root.find(f".//body[@name='{spec.hand_body}']")
    if hand.find("site[@name='tcp']") is None:
        ET.SubElement(hand, "site", name="tcp", pos=spec.tcp_pos, size=".004", rgba="0 0 0 0")
    # Camera follows the hand and looks along the fingers toward the workspace.
    # MuJoCo cameras look along local -Z; these axes turn it toward hand +Z.
    ET.SubElement(hand, "camera", name="wrist_camera", pos=spec.wrist_cam_pos,
                  xyaxes="1 0 0 0 -1 0", fovy="80")
    for geom in root.findall(".//default[@class='collision']//geom"):
        geom.set("friction", "1.8 .02 .002")
    targets, sources = _add_world_objects(root, task, seed, scene_config)
    xml = ET.tostring(root, encoding="unicode")
    return xml, targets, sources


def _add_world_objects(root, task, seed, scene_config):
    """Task furniture and graspable objects. Returns (targets, sources) — one
    entry per graspable body ("cube", plus "cube2" for sort)."""
    world = root.find("worldbody")
    ET.SubElement(world, "geom", name="table", type="box", pos=".32 0 -.025", size=".55 .43 .025",
                  rgba=".81 .84 .85 1", friction="1 .01 .001")
    if task == "insert":
        # Precision insertion: a standing peg (shaft + stabilising disc, both
        # narrow enough to enter the pocket) and a socket block whose inner
        # opening (36 mm) clears the peg disc (26 mm) by 5 mm per side.
        rng = np.random.default_rng(seed)
        source = np.array([.43, -.17, .039])
        if scene_config["source_xy"] is None:
            source[:2] += rng.uniform(-.025, .025, 2)
        else:
            source[:2] = scene_config["source_xy"]
        peg = ET.SubElement(world, "body", name="cube", pos=" ".join(map(str, source)))
        ET.SubElement(peg, "freejoint", name="cube_joint")
        ET.SubElement(peg, "geom", name="cube_geom", type="box", size=".008 .008 .033", mass=".07",
                      rgba=".88 .19 .19 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
        ET.SubElement(peg, "geom", name="cube_base", type="cylinder", size=".013 .0025", pos="0 0 -.0355",
                      rgba=".55 .55 .58 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
        target = np.array([*scene_config["target_xy"], TASKS[task]["target_z"]])
        target_geometries = [ET.SubElement(world, "geom", name="support", type="box", pos=".43 .18 .003",
                      size=".018 .018 .003", rgba=".93 .66 .15 1", friction="1.2 .01 .001")]
        for i, (x, y, sx, sy) in enumerate([(.408, .18, .002, .022), (.452, .18, .002, .022),
                             (.43, .158, .022, .002), (.43, .202, .022, .002)]):
            target_geometries.append(ET.SubElement(world, "geom", name=f"tray_wall_{i}", type="box", pos=f"{x} {y} .0185", size=f"{sx} {sy} .0125",
                          rgba=".76 .52 .10 1"))
        offset = target[:2] - np.asarray(SCENE_DEFAULTS["target_xy"])
        if np.any(offset):
            for geom in target_geometries:
                position = np.fromstring(geom.get("pos"), sep=" ")
                position[:2] += offset
                geom.set("pos", " ".join(map(str, position)))
        return [target], [source]
    if task == "kitting":
        # 精密摆盘: 直振送料器上四个精密件 -> 防静电托盘 2x2 料位。
        # 3.5 cm 件在 Panda 夹爪验证包络内; 料位间隙 2.5mm/侧(与 insert 同款精密语义)。
        feed_x = .44
        ET.SubElement(world, "geom", name="conveyor_frame", type="box", pos=f"{feed_x} -.13 .030",
                      size=".05 .24 .030", rgba=".30 .32 .35 1", friction="1 .01 .001")
        ET.SubElement(world, "geom", name="feeder_rail", type="box", pos=f"{feed_x} -.13 .064",
                      size=".030 .24 .004", rgba=".58 .60 .63 1", friction="1.0 .01 .001")
        # 取料挡停: 件排队顶到挡停, 取走前件后队列前进
        # 挡停只挡件的下沿(低于夹爪垫面): 手指从上方自由包夹
        ET.SubElement(world, "geom", name="feeder_stop", type="box", pos=f"{feed_x} .06 .078",
                      size=".035 .004 .011", rgba=".85 .45 .10 1", friction="1.6 .01 .001")
        sources = []
        for i, sy in enumerate((.04, -.042, -.124, -.206)):   # 队列: 前件顶挡停
            pos = np.array([feed_x, sy, .088])
            sources.append(pos)
            name = "cube" if i == 0 else f"cube{i + 1}"
            part = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(part, "freejoint", name="cube_joint" if i == 0 else f"{name}_joint")
            ET.SubElement(part, "geom", name="cube_geom" if i == 0 else f"{name}_geom",
                          type="box", size=".020 .020 .020", mass=".08",
                          rgba=".30 .34 .42 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
        # 防静电托盘 + 2x2 料位(浅穴 + 蓝框标识)
        tray_x, tray_y = .43, .18
        ET.SubElement(world, "geom", name="pallet_deck", type="box", pos=f"{tray_x} {tray_y} .006",
                      size=".105 .105 .006", rgba=".16 .17 .19 1", friction="1.4 .01 .001")
        targets = []
        for i, (dx, dy) in enumerate(((-.045, -.045), (.045, -.045), (-.045, .045), (.045, .045))):
            targets.append(np.array([tray_x + dx, tray_y + dy, TASKS[task]["target_z"]]))
            ET.SubElement(world, "geom", name="support" if i == 0 else f"support{i + 1}", type="box",
                          pos=f"{tray_x + dx} {tray_y + dy} .013", size=".023 .023 .0015",
                          rgba=".12 .47 .74 1", friction="1.6 .01 .001")
            for k, (wx, wy, sx, sy) in enumerate(((tray_x+dx-.024, tray_y+dy, .001, .024),
                                                   (tray_x+dx+.024, tray_y+dy, .001, .024),
                                                   (tray_x+dx, tray_y+dy-.024, .024, .001),
                                                   (tray_x+dx, tray_y+dy+.024, .024, .001))):
                ET.SubElement(world, "geom", name=f"kit{i}_wall_{k}", type="box",
                              pos=f"{wx} {wy} .014", size=f"{sx} {sy} .002", rgba=".20 .50 .85 1",
                              contype="0", conaffinity="0")
        return targets, sources
    if task == "depalletize":
        # 拆垛上料: 木托盘上三个纸箱(底层两个、顶上一个), 吸盘逐个搬上辊筒输送机。
        # 固定布局; 活跃对象按高度优先(自然从上到下)。
        pallet_x, pallet_y = .43, .18
        # 木托盘: 9 脚块 + 面板
        for bx in (-.052, 0., .052):
            for by in (-.052, 0., .052):
                ET.SubElement(world, "geom", name=f"pallet_block_{bx}_{by}", type="box",
                              pos=f"{pallet_x+bx} {pallet_y+by} .045", size=".016 .016 .045",
                              rgba=".42 .30 .17 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="pallet_deck", type="box", pos=f"{pallet_x} {pallet_y} .105",
                      size=".075 .075 .015", rgba=".55 .42 .26 1", friction="1.2 .01 .001")
        # 纸箱(棕+胶带): 底层两个、顶上一个
        box_specs = [("cube", (pallet_x-.043, pallet_y, .165)), ("cube2", (pallet_x+.043, pallet_y, .165)),
                     ("cube3", (pallet_x, pallet_y, .245))]
        sources = []
        for name, pos in box_specs:
            sources.append(np.array(pos))
            carton = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(carton, "freejoint", name=f"{name}_joint" if name != "cube" else "cube_joint")
            ET.SubElement(carton, "geom", name=f"{name}_geom" if name != "cube" else "cube_geom",
                          type="box", size=".04 .04 .04", mass=".40",
                          rgba=".64 .46 .29 1", friction="1.6 .02 .002", condim="6", solref=".006 1")
            ET.SubElement(carton, "geom", name=f"{name}_tape", type="box", size=".041 .010 .041",
                          pos="0 0 0", rgba=".86 .80 .62 1", contype="0", conaffinity="0", group="2")
        # 辊筒输送机: 框架 + 辊筒 + 三个停靠位
        conv_y = -.14
        ET.SubElement(world, "geom", name="conveyor_frame", type="box", pos=".44 -.14 .045",
                      size=".16 .09 .045", rgba=".30 .32 .35 1", friction="1 .01 .001")
        for i in range(8):
            ET.SubElement(world, "geom", name=f"conveyor_roller_{i}", type="cylinder",
                          pos=f"{.295+i*.055} {conv_y} .092", size=".014 .082",
                          quat="0.7071 0 0.7071 0", rgba=".58 .60 .63 1",
                          friction="1.0 .01 .001", contype="0", conaffinity="0")
        # 皮带面(活面): 投放区在带面前段, 纸箱上带后随带运往尾端挡停排队
        ET.SubElement(world, "geom", name="conveyor_belt", type="box", pos=".44 -.14 .105",
                      size=".075 .26 .0015", rgba=".16 .17 .19 1", friction="0.9 .01 .001")
        ET.SubElement(world, "geom", name="belt_stop", type="box", pos=".44 -.378 .125",
                      size=".08 .006 .02", rgba=".85 .45 .10 1", friction="1.6 .01 .001")
        targets = [np.array([.44, -.12, TASKS[task]["target_z"]]),
                   np.array([.44, -.12, TASKS[task]["target_z"]]),
                   np.array([.44, -.12, TASKS[task]["target_z"]])]  # 投放区同位(带上排队)
        for i, tgt in enumerate(targets):
            ET.SubElement(world, "geom", name="support" if i == 0 else f"support{i+1}", type="box",
                          pos=f"{tgt[0]} {tgt[1]} .107", size=".05 .03 .001",
                          rgba=".20 .50 .85 1", contype="0", conaffinity="0", group="2")
        return targets, sources
    if task == "tending":
        # 机床上下料 v2(工业动作链): 毛坯料盘 -> 门禁 -> 立式卡盘(装夹/加工/绿灯)
        # -> 卸成品 -> 成品盒。滑门随机器人到位开关; 加工 2.5s。
        # 平面布局: 机器人工位(x<0.36) | 滑门(x=0.36) | 卡盘+机床(x>0.36)
        sources = [np.array([.30, -.16, .029]), np.array([.34, -.10, .029])]
        for name, joint, geom, pos in (
                ("cube", "cube_joint", "cube_geom", sources[0]),
                ("cube2", "cube2_joint", "cube2_geom", sources[1])):
            blank = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(blank, "freejoint", name=joint)
            ET.SubElement(blank, "geom", name=geom, type="box", size=".016 .016 .021", mass=".08",
                          rgba=".62 .63 .68 1", friction="1.8 .02 .002", condim="6", solref=".004 1", solimp="0.95 0.99 0.001")
        ET.SubElement(world, "geom", name="blank_tray", type="box", pos=".32 -.13 .004",
                      size=".08 .08 .004", rgba=".35 .38 .42 1", friction="1.2 .01 .001")
        # 立式卡盘(凸台式): 毛坯端面坐卡盘面上, 三爪只箍底缘——夹爪从上部包夹,
        # 不存在深穴(深穴会让张开的手指先碰壁, 实测)
        ET.SubElement(world, "geom", name="fixture_boss", type="box", pos=".42 .16 .0315",
                      size=".045 .045 .0315", rgba=".35 .38 .42 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="chuck_body", type="cylinder", pos=".42 .16 .074",
                      size=".024 .014", rgba=".28 .29 .32 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="support", type="box", pos=".42 .16 .0885",
                      size=".021 .021 .0005", rgba=".93 .66 .15 1", friction="1.6 .01 .001")
        # 成品盒(两个料位)
        for i, (ox, oy) in enumerate(((.33, .05), (.33, -.02))):
            ET.SubElement(world, "geom", name=f"outbox{i}" if i else "outbox", type="box",
                          pos=f"{ox} {oy} .004", size=".032 .032 .004", rgba=".20 .50 .85 1",
                          friction="1.4 .01 .001")
            for k, (wx, wy, sx, sy) in enumerate(((ox-.033, oy, .001, .034), (ox+.033, oy, .001, .034),
                                                   (ox, oy-.033, .034, .001), (ox, oy+.033, .034, .001))):
                ET.SubElement(world, "geom", name=f"outbox{i}_wall_{k}", type="box",
                              pos=f"{wx} {wy} .010", size=f"{sx} {sy} .006", rgba=".12 .47 .74 1")
        # 机床罩壳 + 滑门(竖版安全门, 沿 Y 滑到罩壳右侧停靠) + 双色状态旗
        ET.SubElement(world, "geom", name="machine_body", type="box", pos=".64 .16 .13",
                      size=".11 .16 .13", rgba=".23 .25 .28 1", friction="1 .01 .001")
        ET.SubElement(world, "geom", name="machine_window", type="box", pos=".529 .16 .20",
                      size=".002 .08 .05", rgba=".55 .75 .85 .45", contype="0", conaffinity="0")
        door = ET.SubElement(world, "body", name="door_panel", pos=".34 .16 .20")
        ET.SubElement(door, "joint", name="door_joint", type="slide", axis="0 1 0",
                      range="0 .20", damping="8", armature="0.5", frictionloss="0.5")
        ET.SubElement(door, "inertial", mass="1.2", pos="0 0 0",
                      diaginertia="0.01 0.01 0.01")
        ET.SubElement(door, "geom", name="door_panel_geom", type="box", pos="0 0 0",
                      size=".004 .12 .14", rgba=".45 .68 .80 .55", friction="1 .01 .001")
        ET.SubElement(door, "geom", name="door_frame", type="box", pos="0 0 -.135",
                      size=".008 .125 .008", rgba=".35 .38 .42 1", friction="1 .01 .001")
        # 双色状态旗(机床顶部): 加工中=低位, 加工完=升起
        for i in range(2):
            flag = ET.SubElement(world, "body", name=f"flag_{i}", pos=f"{.60 + .08 * i} .08 .275")
            ET.SubElement(flag, "joint", name=f"flag_joint_{i}", type="slide", axis="0 0 1",
                          range="0 .035", damping="2", armature="0.02")
            ET.SubElement(flag, "inertial", mass="0.05", pos="0 0 0", diaginertia="1e-5 1e-5 1e-5")
            ET.SubElement(flag, "geom", name=f"flag_geom_{i}", type="cylinder", pos="0 0 0",
                          size=".007 .018", rgba=".85 .20 .18 1", contype="0", conaffinity="0")
        targets = [np.array([.42, .16, .109]), np.array([.42, .16, .109])]  # 首轮都进卡盘
        # 机床执行器: 滑门伺服 + 双状态旗伺服
        act = root.find("actuator")
        act.append(ET.fromstring('<position name="door_ctrl" joint="door_joint" kp="8" kv="3" ctrlrange="0 .20" forcerange="-30 30"/>'))
        for i in range(2):
            act.append(ET.fromstring(f'<position name="flag_ctrl_{i}" joint="flag_joint_{i}" kp="12" kv="3" ctrlrange="0 .035" forcerange="-5 5"/>'))
        return targets, sources
    if task == "sort":
        # Two-cube sorting: red -> blue tray, green -> yellow tray. Fixed layout
        # (no jitter): the decision loop handles the objects one at a time.
        sources = [np.array([.41, -.20, .021]), np.array([.47, -.12, .021])]
        cube = ET.SubElement(world, "body", name="cube", pos=" ".join(map(str, sources[0])))
        ET.SubElement(cube, "freejoint", name="cube_joint")
        ET.SubElement(cube, "geom", name="cube_geom", type="box", size=".02 .02 .02", mass=".06",
                      rgba=".88 .19 .19 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
        cube2 = ET.SubElement(world, "body", name="cube2", pos=" ".join(map(str, sources[1])))
        ET.SubElement(cube2, "freejoint", name="cube2_joint")
        ET.SubElement(cube2, "geom", name="cube2_geom", type="box", size=".02 .02 .02", mass=".06",
                      rgba=".15 .55 .25 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
        targets = [np.array([.43, .20, TASKS[task]["target_z"]]), np.array([.28, .08, TASKS[task]["target_z"]])]
        for prefix, centre, floor_rgba, wall_rgba in (
                ("", (.43, .20), ".10 .44 .72 1", ".12 .47 .74 1"),
                ("2", (.28, .08), ".93 .66 .15 1", ".76 .52 .10 1")):
            cx, cy = centre
            ET.SubElement(world, "geom", name=f"support{prefix}", type="box", pos=f"{cx} {cy} .003",
                          size=".07 .07 .003", rgba=floor_rgba, friction="1.2 .01 .001")
            for i, (x, y, sx, sy) in enumerate([(cx-.076, cy, .006, .082), (cx+.076, cy, .006, .082),
                                 (cx, cy-.076, .07, .006), (cx, cy+.076, .07, .006)]):
                ET.SubElement(world, "geom", name=f"tray{prefix}_wall_{i}", type="box", pos=f"{x} {y} .012",
                              size=f"{sx} {sy} .012", rgba=wall_rgba)
        return targets, sources
    if task == "weld":
        # 焊接打点: 钢工装板上 2x2 铜焊柱, 焊枪(TCP 指尖面)带 2mm 工艺间隙
        # 逐点驻留; 焊柱是工装件(钩子钉死), 打点完成后变绿。
        plate_x, plate_y = .40, .05
        ET.SubElement(world, "geom", name="weld_plate", type="box", pos=f"{plate_x} {plate_y} .006",
                      size=".11 .08 .006", rgba=".34 .36 .40 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="weld_seam", type="box", pos=f"{plate_x} {plate_y} .0125",
                      size=".095 .065 .0006", rgba=".22 .24 .27 1", contype="0", conaffinity="0")
        sources, targets = [], []
        for i, (dx, dy) in enumerate(((-.032, -.022), (.032, -.022), (.032, .022), (-.032, .022))):
            sx, sy = plate_x + dx, plate_y + dy
            pos = np.array([sx, sy, .021])
            sources.append(pos)
            targets.append(np.array([sx, sy, .032]))   # 驻留点: 柱顶 +2mm 工艺间隙
            name = "cube" if i == 0 else f"cube{i + 1}"
            stud = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(stud, "freejoint", name="cube_joint" if i == 0 else f"{name}_joint")
            ET.SubElement(stud, "geom", name="cube_geom" if i == 0 else f"{name}_geom",
                          type="cylinder", size=".007 .009", mass=".02",
                          rgba=".80 .48 .22 1", friction="1.2 .01 .001")
            ET.SubElement(world, "geom", name="support" if i == 0 else f"support{i + 1}",
                          type="cylinder", pos=f"{sx} {sy} .0125", size=".012 .0005",
                          rgba=".20 .50 .85 1", contype="0", conaffinity="0", group="2")
        return targets, sources
    if task == "glue":
        # 涂胶轨迹: 壳体顶面矩形密封槽路径上 6 个轨迹标记, 胶枪(TCP)按序
        # 带 2mm 间隙驻留过点, 过点变绿; 标记是工装件(钩子钉死)。
        shell_x, shell_y = .42, .08
        ET.SubElement(world, "geom", name="glue_housing", type="box", pos=f"{shell_x} {shell_y} .010",
                      size=".10 .065 .010", rgba=".74 .76 .79 1", friction="1.2 .01 .001")
        for k, (gx, gy, sx, sy) in enumerate(((shell_x, shell_y - .018, .040, .003),
                                              (shell_x, shell_y + .018, .040, .003),
                                              (shell_x - .04, shell_y, .003, .018),
                                              (shell_x + .04, shell_y, .003, .018))):
            ET.SubElement(world, "geom", name=f"glue_groove_{k}", type="box",
                          pos=f"{gx} {gy} .0205", size=f"{sx} {sy} .0006",
                          rgba=".30 .32 .35 1", contype="0", conaffinity="0", group="2")
        sources, targets = [], []
        for i, (ux, uy) in enumerate(((-1., -1.), (0., -1.), (1., -1.),
                                      (1., 1.), (0., 1.), (-1., 1.))):
            mx, my = shell_x + .04 * ux, shell_y + .018 * uy
            pos = np.array([mx, my, .023])
            sources.append(pos)
            targets.append(np.array([mx, my, .028]))   # 驻留点: 标记顶 +2mm 工艺间隙
            name = "cube" if i == 0 else f"cube{i + 1}"
            dot = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(dot, "freejoint", name="cube_joint" if i == 0 else f"{name}_joint")
            ET.SubElement(dot, "geom", name="cube_geom" if i == 0 else f"{name}_geom",
                          type="cylinder", size=".005 .003", mass=".01",
                          rgba=".13 .52 .95 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="support", type="box", pos=f"{shell_x} {shell_y} .0205",
                      size=".002 .002 .0005", rgba="0 0 0 0", contype="0", conaffinity="0", group="4")
        return targets, sources
    if task == "palletize":
        # 码垛下线(拆垛逆流程): 纸箱在辊筒输送机上游排队, 随带向尾端挡停
        # 积攒; 吸盘逐个码上木托盘(先左、后右、再叠顶), 码稳闩锁完工。
        pallet_x, pallet_y = .43, .18
        for bx in (-.052, 0., .052):
            for by in (-.052, 0., .052):
                ET.SubElement(world, "geom", name=f"pallet_block_{bx}_{by}", type="box",
                              pos=f"{pallet_x + bx} {pallet_y + by} .045", size=".016 .016 .045",
                              rgba=".42 .30 .17 1", friction="1.2 .01 .001")
        ET.SubElement(world, "geom", name="pallet_deck", type="box", pos=f"{pallet_x} {pallet_y} .105",
                      size=".075 .075 .015", rgba=".55 .42 .26 1", friction="1.2 .01 .001")
        conv_y = -.14
        ET.SubElement(world, "geom", name="conveyor_frame", type="box", pos=".44 -.14 .045",
                      size=".16 .09 .045", rgba=".30 .32 .35 1", friction="1 .01 .001")
        for i in range(8):
            ET.SubElement(world, "geom", name=f"conveyor_roller_{i}", type="cylinder",
                          pos=f"{.295 + i * .055} {conv_y} .092", size=".014 .082",
                          quat="0.7071 0 0.7071 0", rgba=".58 .60 .63 1",
                          friction="1.0 .01 .001", contype="0", conaffinity="0")
        ET.SubElement(world, "geom", name="conveyor_belt", type="box", pos=".44 -.14 .105",
                      size=".075 .26 .0015", rgba=".16 .17 .19 1", friction="0.9 .01 .001")
        ET.SubElement(world, "geom", name="belt_stop", type="box", pos=".44 -.378 .125",
                      size=".08 .006 .02", rgba=".85 .45 .10 1", friction="1.6 .01 .001")
        box_specs = [("cube", (.44, -.26, .146)), ("cube2", (.44, -.16, .146)), ("cube3", (.44, -.06, .146))]
        sources = []
        for name, pos in box_specs:
            sources.append(np.array(pos))
            carton = ET.SubElement(world, "body", name=name, pos=" ".join(map(str, pos)))
            ET.SubElement(carton, "freejoint", name=f"{name}_joint" if name != "cube" else "cube_joint")
            ET.SubElement(carton, "geom", name=f"{name}_geom" if name != "cube" else "cube_geom",
                          type="box", size=".04 .04 .04", mass=".40",
                          rgba=".64 .46 .29 1", friction="1.6 .02 .002", condim="6", solref=".006 1")
            ET.SubElement(carton, "geom", name=f"{name}_tape", type="box", size=".041 .010 .041",
                          pos="0 0 0", rgba=".86 .80 .62 1", contype="0", conaffinity="0", group="2")
        targets = [np.array([pallet_x - .043, pallet_y, .16]),
                   np.array([pallet_x + .043, pallet_y, .16]),
                   np.array([pallet_x, pallet_y, .24])]
        for i, tgt in enumerate(targets[:2]):   # 托盘码位标识(贴面板, 视觉)
            ET.SubElement(world, "geom", name="support" if i == 0 else f"support{i + 1}", type="box",
                          pos=f"{tgt[0]} {tgt[1]} .121", size=".045 .045 .001",
                          rgba=".20 .50 .85 1", contype="0", conaffinity="0", group="2")
        return targets, sources
    rng = np.random.default_rng(seed)
    source = np.array([.43, -.17, .021])
    if scene_config["source_xy"] is None:
        source[:2] += rng.uniform(-.025, .025, 2)
    else:
        source[:2] = scene_config["source_xy"]
    cube = ET.SubElement(world, "body", name="cube", pos=" ".join(map(str, source)))
    ET.SubElement(cube, "freejoint", name="cube_joint")
    ET.SubElement(cube, "geom", name="cube_geom", type="box", size=".02 .02 .02", mass=".06",
                  rgba=".88 .19 .19 1", friction="1.8 .02 .002", condim="6", solref=".006 1")
    target = np.array([*scene_config["target_xy"], TASKS[task]["target_z"]])
    target_geometries = []
    if task == "stack":
        target_geometries.append(ET.SubElement(world, "geom", name="support", type="box", pos=".43 .18 .02", size=".03 .03 .02",
                      rgba=".10 .44 .72 1", friction="1.2 .01 .001"))
    else:
        target_geometries.append(ET.SubElement(world, "geom", name="support", type="box", pos=".43 .18 .003", size=".07 .07 .003",
                      rgba=".10 .44 .72 1", friction="1.2 .01 .001"))
        for i, (x, y, sx, sy) in enumerate([(.354, .18, .006, .082), (.506, .18, .006, .082),
                             (.43, .104, .07, .006), (.43, .256, .07, .006)]):
            target_geometries.append(ET.SubElement(world, "geom", name=f"tray_wall_{i}", type="box", pos=f"{x} {y} .012", size=f"{sx} {sy} .012",
                          rgba=".12 .47 .74 1"))
    offset = target[:2] - np.asarray(SCENE_DEFAULTS["target_xy"])
    if np.any(offset):
        for geom in target_geometries:
            position = np.fromstring(geom.get("pos"), sep=" ")
            position[:2] += offset
            geom.set("pos", " ".join(map(str, position)))
    if task == "barrier":
        barrier = ET.SubElement(world, "geom", name="barrier", type="box", pos=".43 0 .055", size=".115 .018 .055",
                      rgba=".93 .66 .15 1")
        if scene_config["barrier_height"] != SCENE_DEFAULTS["barrier_height"]:
            half_height = scene_config["barrier_height"] / 2
            barrier.set("pos", f".43 0 {half_height}")
            barrier.set("size", f".115 .018 {half_height}")
    return [target], [source]


class RobotWorld:
    def __init__(self, task="transfer", seed=0, scene_config=None, robot=None):
        if task not in TASKS:
            raise ValueError("Unknown task")
        self.spec = resolve_robot(robot)
        self.task, self.seed = task, seed
        custom_scene = scene_config is not None
        self.scene_config = validate_scene_config(task, scene_config)
        self.scene_name = self.scene_config["name"]
        xml, self.targets, self.sources = _build_scene_parts(task, seed, self.scene_config, robot=self.spec.key)
        # Normalise every absolute asset path so the hash is identical on any machine.
        self.scene_hash = hashlib.sha256(
            xml.replace(str(ASSETS), "ASSETS")
               .replace(str(ASSETS_ROOT / "openarm"), "ASSETS")
               .replace(str(ASSETS_ROOT), "ASSETS_ROOT").encode()).hexdigest()
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.arm_q = np.array([self.model.jnt_qposadr[self.model.joint(name).id]
                               for name in self.spec.arm_joints])
        self.arm_dof = np.array([self.model.jnt_dofadr[self.model.joint(name).id]
                                 for name in self.spec.arm_joints])
        self.ranges = np.array([self.model.jnt_range[self.model.joint(name).id]
                                for name in self.spec.arm_joints], dtype=float)
        # Continuous joints (Gen3's twist joints carry no range): keep them
        # unclamped in IK instead of freezing them at [0, 0].
        for i, name in enumerate(self.spec.arm_joints):
            if not self.model.jnt_limited[self.model.joint(name).id]:
                self.ranges[i] = [-np.inf, np.inf]
        self.arm_ctrl = np.array([self.model.actuator(name).id for name in self.spec.arm_actuators])
        self.gripper_ctrl = (self.model.actuator(self.spec.gripper_actuator).id
                             if self.spec.gripper_actuator else None)
        self.tcp = self.model.site("tcp").id
        # Graspable objects: one per object body, matched index-wise with
        # targets/sources. "sort" adds cube2; every other task has just "cube".
        # Graspable objects: "cube", plus cube2/cube3/... for multi-object tasks
        # (sort uses two, depalletizing stacks three or more).
        self.object_names = ["cube"]
        for n in range(2, 9):
            if mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"cube{n}") < 0:
                break
            self.object_names.append(f"cube{n}")
        self.cube_ids = [self.model.body(name).id for name in self.object_names]
        self.cube_geoms = [self.model.geom("cube_geom" if i == 0 else f"{name}_geom").id
                           for i, name in enumerate(self.object_names)]
        self.cube_dofs = [self.model.jnt_dofadr[self.model.joint("cube_joint" if i == 0 else f"{name}_joint").id]
                          for i, name in enumerate(self.object_names)]
        self.cube_qadrs = [self.model.jnt_qposadr[self.model.joint("cube_joint" if i == 0 else f"{name}_joint").id]
                           for i, name in enumerate(self.object_names)]
        self.cube_half_z = [float(self.model.geom_size[g][2] if int(self.model.geom_type[g]) == int(mujoco.mjtGeom.mjGEOM_BOX)
                                  else self.model.geom_size[g][1]) for g in self.cube_geoms]
        # support<i+1> 缺失时回退共享 "support"(如上下料首轮共用卡盘)
        def _support_id(i):
            name = "support" if i == 0 else f"support{i + 1}"
            return self.model.geom(name).id if mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_GEOM, name) >= 0 else self.model.geom("support").id
        self.support_ids = [_support_id(i) for i in range(len(self.object_names))]
        self.placed = [False] * len(self.cube_ids)
        self._support_live = [False] * len(self.cube_ids)
        self._pad_contact = False
        self.attached = False
        self._locked_index = None
        self._belt_latched = set()
        self._last_candidate = None
        # Every geom of an object body counts for contact semantics (the insert
        # peg rests on its disc "cube_base", not the grasped shaft "cube_geom").
        # Single-geom tasks keep the exact stock behaviour.
        self.cube_geom_sets = [{g for g in range(self.model.ngeom)
                                if int(self.model.geom_bodyid[g]) == bid}
                               for bid in self.cube_ids]
        # Backwards-compatible aliases for the first object.
        self.cube_id, self.cube_geom, self.cube_dof = self.cube_ids[0], self.cube_geoms[0], self.cube_dofs[0]
        self.support_id = self.support_ids[0]
        self.target_geom_ids = [i for i in range(self.model.ngeom)
                               if self.model.geom(i).name == "support" or
                               (self.model.geom(i).name or "").startswith("tray_wall_")]
        # Contact bodies that count as "grip": two fingers for jaw grippers,
        # the pad alone for the suction tool.
        self.contact_bodies = {label: self.model.body(name).id
                               for label, name in self.spec.contact_bodies.items()}
        self.closed = False
        self.stable_seconds = 0.
        self.contact_seconds = 0.
        self.max_lift = 0.
        self.unsafe_contacts = 0
        self.steps = 0
        self.data.qpos[self.arm_q] = self.spec.home
        self.data.ctrl[self.arm_ctrl] = self.spec.home
        if self.gripper_ctrl is not None:
            self.data.ctrl[self.gripper_ctrl] = self.spec.gripper_open
        for name in self.spec.finger_joints:
            self.data.qpos[self.model.jnt_qposadr[self.model.joint(name).id]] = self.spec.finger_open_qpos
        down_yaw = TASKS[self.task].get("down_yaw")
        self.down = (np.array([[0., 1., 0.], [1., 0., 0.], [0., 0., -1.]])
                     if abs(down_yaw - 90.) < 1e-6 else self.spec.down) if down_yaw is not None else self.spec.down
        mujoco.mj_forward(self.model, self.data)
        q, err = self.solve_ik(self.spec.initial_target)
        if err > .004:
            raise RuntimeError(f"Initial IK failed: {err}")
        self.data.qpos[self.arm_q] = q
        self.data.ctrl[self.arm_ctrl] = q
        mujoco.mj_forward(self.model, self.data)
        for _ in range(250):
            self.tick()
        self.steps = 0
        self.start_time = float(self.data.time)
        if custom_scene:
            self._check_scene_reachability()

    def _check_scene_reachability(self):
        # Endpoint checks reject obviously infeasible presets. They do not certify
        # a whole path: candidate rollouts and live contact checks still run.
        if self.unsafe_contacts:
            raise ValueError("自定义场景初始状态存在机械臂与台面或障碍接触")
        for cube_i, target_i in zip(self._all_cubes(), self.targets):
            targets = [cube_i + [0, 0, .14], cube_i + [0, 0, .001],
                       np.r_[cube_i[:2], TRAVEL_Z], np.r_[target_i[:2], TRAVEL_Z],
                       target_i + [0, 0, .003]]
            for target in targets:
                q, error = self.solve_ik(target)
                if error > .004:
                    raise ValueError("自定义场景关键位姿不可达，请将源方块或目标移近工作区中心")
                shadow = self.clone()
                shadow.data.qpos[self.arm_q] = q
                mujoco.mj_forward(shadow.model, shadow.data)
                if shadow.contacts()[2]:
                    raise ValueError("自定义场景关键位姿与台面或障碍相交，请调整坐标或障碍高度")

    @property
    def position(self):
        return self.data.site_xpos[self.tcp].copy()

    def _all_cubes(self):
        return [self.data.xpos[bid].copy() for bid in self.cube_ids]

    @property
    def active_index(self):
        """Highest unplaced object (natural top-down de-stacking order), locked
        while one is held: switching the active object mid-grasp retargets the
        whole phase machinery and scatters the scene (measured: carton fell off
        the pallet)."""
        if self._locked_index is not None:
            return self._locked_index
        return self._candidate_index()

    def _candidate_index(self):
        unplaced = [i for i, done in enumerate(self.placed) if not done]
        if not unplaced:
            return len(self.placed) - 1
        # Highest first (top-down de-stacking), with 4 cm hysteresis so the
        # press of a failed/real grasp can never flip the target mid-phase.
        best = max(unplaced, key=lambda i: self.data.xpos[self.cube_ids[i]][2])
        if self._last_candidate in unplaced:
            z_best = self.data.xpos[self.cube_ids[best]][2]
            z_cur = self.data.xpos[self.cube_ids[self._last_candidate]][2]
            if z_best - z_cur < .04:
                return self._last_candidate
        self._last_candidate = best
        return best

    @property
    def cube(self):
        return self.data.xpos[self.cube_ids[self.active_index]].copy()

    @property
    def target(self):
        return self.targets[self.active_index]

    @property
    def source(self):
        return self.sources[self.active_index]

    def contacts(self):
        fingers, forbidden = set(), False
        support_flags = [False] * len(self.cube_ids)
        active = self.active_index
        for contact in self.data.contact[:self.data.ncon]:
            if contact.dist > .0005:
                continue
            g1, g2 = int(contact.geom1), int(contact.geom2)
            b1, b2 = int(self.model.geom_bodyid[g1]), int(self.model.geom_bodyid[g2])
            for index in range(len(self.cube_ids)):
                if g1 not in self.cube_geom_sets[index] and g2 not in self.cube_geom_sets[index]:
                    continue
                other = g2 if g1 in self.cube_geom_sets[index] else g1
                if other == self.support_ids[index]:
                    support_flags[index] = True
                if index == active:
                    body = int(self.model.geom_bodyid[other])
                    for label, body_id in self.contact_bodies.items():
                        if body == body_id:
                            fingers.add(label)
            # Ignore the mounted base, finger/object contacts and permitted support contact.
            for body, other_geom in [(b1, g2), (b2, g1)]:
                name = self.model.body(body).name or ""
                other_name = self.model.geom(other_geom).name or ""
                if name in self.spec.forbidden_bodies and other_name in {"table", "barrier", "machine_body", "fixture_boss"}:
                    forbidden = True
        self._pad_contact = "pad" in fingers
        self._support_live = support_flags
        return fingers, support_flags[active], forbidden

    def tick(self):
        self.data.qfrc_applied[self.arm_dof] = self.data.qfrc_bias[self.arm_dof]
        mujoco.mj_step(self.model, self.data)
        self.steps += 1
        fingers, support, forbidden = self.contacts()
        self.unsafe_contacts += int(forbidden)
        gripping = self.attached if self.spec.suction else (len(fingers) == self.spec.required_finger_groups and self.closed)
        self.contact_seconds = self.contact_seconds + DT if gripping else 0.
        for i in range(len(self.cube_ids)):
            speed = np.linalg.norm(self.data.qvel[self.cube_dofs[i]:self.cube_dofs[i] + 3])
            on_target = np.linalg.norm(self._all_cubes()[i][:2] - self.targets[i][:2]) < .025
            # Resting test only — no gripper term: in multi-object tasks the
            # gripper closes on the NEXT object while earlier ones stay placed.
            self.placed[i] = bool(self._support_live[i] and on_target and speed < .025)
        if self.spec.suction:
            self._suction_tick(fingers)
        if self._locked_index is not None:
            if not self.closed and not self.attached:
                self._locked_index = None
        elif self.attached or (self.closed and 0 < self.spec.required_finger_groups <= len(fingers)):
            # 夹持确立才锁定: 吸盘看挂载, 夹爪看指触; 否则锁定会抢错对象
            self._locked_index = self._candidate_index()
        task_hook = TASK_HOOKS.get(self.task)
        if task_hook is not None:
            task_hook(self)
        self.stable_seconds = self.stable_seconds + DT if all(self.placed) and not self.closed else 0.
        self.max_lift = max(self.max_lift, float(self.cube[2] - self.source[2]))
        if not np.isfinite(self.data.qpos).all():
            raise RuntimeError("MuJoCo state became non-finite")

    def _suction_tick(self, fingers):
        """Vacuum tool: pad contact + vacuum on -> kinematic attach (the same
        convention as the drone payload hook); vacuum off -> release. The load
        weight is not fed back into the arm (documented simplification)."""
        pad = self.contact_bodies["pad"] if "pad" in self.contact_bodies else self.model.body("suction_tool").id
        cube_id = self.cube_ids[self.active_index]
        cube_pos = self.data.xpos[cube_id]
        pad_pos = self.data.site_xpos[self.tcp]
        top_gap = float(pad_pos[2] - (cube_pos[2] + self.cube_half_z[self.active_index]))
        xy_gap = float(np.linalg.norm(pad_pos[:2] - cube_pos[:2]))
        seal = -.01 <= top_gap <= .004 and xy_gap < .03
        if self.closed and not self.attached and seal:
            # capture the pad->object transform at the moment of suction contact
            R = self.data.xmat[pad].reshape(3, 3)
            self._attach_rel_pos = R.T @ (self.data.xpos[cube_id] - self.data.xpos[pad])
            qc = np.empty(4); mujoco.mju_mat2Quat(qc, self.data.xmat[cube_id])
            qp = np.empty(4); mujoco.mju_mat2Quat(qp, self.data.xmat[pad])
            qp_inv = np.empty(4); mujoco.mju_negQuat(qp_inv, qp)
            rel = np.empty(4); mujoco.mju_mulQuat(rel, qp_inv, qc)
            self._attach_rel_quat = rel
            self.attached = True
        elif not self.closed and self.attached:
            self.attached = False
        if self.attached:
            R = self.data.xmat[pad].reshape(3, 3)
            qadr = self.cube_qadrs[self.active_index]
            dadr = self.cube_dofs[self.active_index]
            self.data.qpos[qadr:qadr + 3] = self.data.xpos[pad] + R @ self._attach_rel_pos
            qp = np.empty(4); mujoco.mju_mat2Quat(qp, self.data.xmat[pad])
            qc = np.empty(4); mujoco.mju_mulQuat(qc, qp, self._attach_rel_quat)
            self.data.qpos[qadr + 3:qadr + 7] = qc
            # continuity: object inherits the pad velocity (free flight after release)
            pad_vel = np.zeros(6)
            mujoco.mj_objectVelocity(self.model, self.data, mujoco.mjtObj.mjOBJ_BODY, pad, pad_vel, 0)
            self.data.qvel[dadr:dadr + 6] = pad_vel

    def success(self):
        return bool(self.stable_seconds >= .4 and not self.closed and self.position[2] >= .17)

    def solve_ik(self, target):
        d = mujoco.MjData(self.model)
        d.qpos[:] = self.data.qpos
        target = np.asarray(target)
        q_desired = np.empty(4)
        mujoco.mju_mat2Quat(q_desired, self.down.flatten())
        q, err = self._dls(d, target, d.qpos[self.arm_q], q_desired)
        if err <= .004 and self._ik_pose_ok(q):
            return q, err
        # Warm start fell into a local minimum (happens on cross-body targets for
        # robots with limited wrist dexterity). Deterministic multi-restart: try
        # the fixed backup seeds and keep the converged solution closest to the
        # current pose, so executed joint paths stay short and smooth.
        best_q, best_err, best_dist = q, err, np.inf
        for seed in self.spec.backup_homes:
            q2, err2 = self._dls(d, target, np.asarray(seed, dtype=float), q_desired)
            if err2 <= .004:
                if not self._ik_pose_ok(q2):
                    continue
                dist = float(np.linalg.norm(q2 - self.data.qpos[self.arm_q]))
                if dist < best_dist:
                    best_q, best_err, best_dist = q2, err2, dist
            elif err2 < best_err and best_dist is np.inf:
                best_q, best_err = q2, err2
        return best_q, best_err

    def _ik_pose_ok(self, q):
        """Optional per-spec veto for IK solutions (e.g. self-collision check)."""
        checker = getattr(self.spec, "ik_pose_ok", None)
        if checker is None:
            return True
        d = mujoco.MjData(self.model)
        d.qpos[:] = self.data.qpos
        d.qpos[self.arm_q] = q
        mujoco.mj_forward(self.model, d)
        return checker(self.model, d)

    def _dls(self, d, target, seed, q_desired):
        d.qpos[self.arm_q] = seed
        jp, jr = np.zeros((3, self.model.nv)), np.zeros((3, self.model.nv))
        q_current, q_inverse, q_error, rotation = np.empty(4), np.empty(4), np.empty(4), np.empty(3)
        for _ in range(180):
            mujoco.mj_forward(self.model, d)
            error = target - d.site_xpos[self.tcp]
            mujoco.mju_mat2Quat(q_current, d.site_xmat[self.tcp])
            mujoco.mju_negQuat(q_inverse, q_current)
            mujoco.mju_mulQuat(q_error, q_desired, q_inverse)
            mujoco.mju_quat2Vel(rotation, q_error, 1.)
            if np.linalg.norm(error) < .0004 and np.linalg.norm(rotation) < .004:
                break
            mujoco.mj_jacSite(self.model, d, jp, jr, self.tcp)
            jac = np.vstack([jp[:, self.arm_dof], jr[:, self.arm_dof]])
            delta = jac.T @ np.linalg.solve(jac @ jac.T + .002 * np.eye(6), np.r_[error, rotation])
            d.qpos[self.arm_q] = np.clip(d.qpos[self.arm_q] + np.clip(delta, -.15, .15), self.ranges[:, 0], self.ranges[:, 1])
        return d.qpos[self.arm_q].copy(), float(np.linalg.norm(error))

    def clone(self):
        other = object.__new__(RobotWorld)
        other.__dict__ = self.__dict__.copy()
        other.data = copy.copy(self.data)
        other.scene_config = copy.deepcopy(self.scene_config)
        other.targets = [t.copy() for t in self.targets]
        other.sources = [s.copy() for s in self.sources]
        other.placed = list(self.placed)
        other._belt_latched = set(self._belt_latched)
        other._last_candidate = self._last_candidate
        other._locked_index = self._locked_index
        if hasattr(self, "_machine"):
            mc = self._machine
            other._machine = {k: (list(v) if isinstance(v, list) else v) for k, v in mc.items()
                              if k != "chuck_target"}
            other._machine["chuck_target"] = mc["chuck_target"].copy()
        if hasattr(self, "_trace"):
            tr = self._trace
            other._trace = {"pin": [None if p is None else p.copy() for p in tr["pin"]],
                            "done": list(tr["done"]), "dwell": list(tr["dwell"])}
        return other

    def perturb(self, kind, delta_xy):
        """Explicit evaluation intervention, only while physics/rendering is idle.

        This is an external displacement, never a robot action. It is logged by
        Session and resets the independent success accumulator.
        """
        if len(self.cube_ids) > 1:
            raise ValueError("多物体任务不支持位置扰动")
        delta = np.asarray(delta_xy, dtype=float)
        if delta.shape != (2,) or not np.isfinite(delta).all() or np.any(np.abs(delta) > .06):
            raise ValueError("扰动位移必须是两个不超过 0.06 米的有限数字")
        if kind == "target_shift":
            config = dict(self.scene_config, target_xy=(self.target[:2] + delta).tolist())
            validate_scene_config(self.task, config)
            before = self.target.copy()
            for gid in self.target_geom_ids:
                self.model.geom_pos[gid, :2] += delta
            self.targets[0][:2] += delta
            after = self.target.copy()
        elif kind == "object_shift":
            if self.contacts()[0]:
                raise ValueError("物体已有夹爪接触，不能施加位置扰动；请提前扰动时刻")
            before = self.cube
            point = before[:2] + delta
            config = dict(self.scene_config, source_xy=point.tolist(), target_xy=self.target[:2].tolist())
            validate_scene_config(self.task, config)
            address = self.model.jnt_qposadr[self.model.joint("cube_joint").id]
            self.data.qpos[address:address + 2] += delta
            self.data.qvel[self.cube_dof:self.cube_dof + 6] = 0
            after = np.r_[point, before[2]]
        else:
            raise ValueError("Unknown intervention")
        self.placed = [False] * len(self.cube_ids)
        self.stable_seconds = 0.
        mujoco.mj_forward(self.model, self.data)
        return {"kind": kind, "delta_xy": delta.tolist(), "before": before.tolist(), "after": after.tolist(),
                "source": "explicit external evaluation intervention"}

    def motion(self, target=None, gripper=None, seconds=.6, emit=True):
        target = self.position if target is None else np.asarray(target, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            raise ValueError("Target must contain three finite coordinates")
        if gripper not in {None, "open", "close"} or not np.isfinite(seconds) or not 0 < seconds <= 10:
            raise ValueError("Invalid gripper command or motion duration")
        if np.any(target < self.spec.workspace_min) or np.any(target > self.spec.workspace_max):
            raise ValueError("Target outside workspace")
        q, error = self.solve_ik(target)
        if error > .004:
            raise ValueError(f"Unreachable target ({error:.4f} m)")
        start = self.data.ctrl[self.arm_ctrl].copy()
        if gripper is not None:
            self.closed = gripper == "close"
            if self.gripper_ctrl is not None:
                self.data.ctrl[self.gripper_ctrl] = self.spec.gripper_closed if self.closed else self.spec.gripper_open
        count = max(1, int(seconds / DT))
        for i in range(1, count + 1):
            t = min(1., i / (count * .75))
            blend = t ** 3 * (10 - 15 * t + 6 * t * t)
            self.data.ctrl[self.arm_ctrl] = start + (q - start) * blend
            self.tick()
            if i % 20 == 0 or i == count:
                yield self.frame() if emit else None

    def observe(self):
        fingers, support, forbidden = self.contacts()
        return {"task": TASKS[self.task]["goal"], "task_id": self.task,
                "source": "MuJoCo geometry and contacts", "units": "metres",
                "scene_name": self.scene_name, "scene_config": copy.deepcopy(self.scene_config),
                "robot": self.spec.display,
                "tcp": self.position.round(5).tolist(), "object": self.cube.round(5).tolist(),
                "relative_geometry": {
                    "tcp_object_xy_distance_m": round(float(np.linalg.norm(self.position[:2] - self.cube[:2])), 4),
                    "tcp_above_object_m": round(float(self.position[2] - self.cube[2]), 4),
                    "object_destination_xy_distance_m": round(float(np.linalg.norm(self.cube[:2] - self.target[:2])), 4),
                    "object_above_destination_m": round(float(self.cube[2] - self.target[2]), 4),
                    "travel_tcp_height_m": TASKS[self.task].get("travel_z", self.spec.travel_z),
                    "grasp_above_m": TASKS[self.task].get("grasp_above",
                                       self.spec.grasp_above if self.spec.grasp_above is not None else 0.001),
                    "motion_time_scale": TASKS[self.task].get("time_scale", 1.0),
                },
                "destination": self.target.tolist(), "gripper": "closed" if self.closed else "open",
                "finger_contacts": sorted(fingers), "held": (self.attached if self.spec.suction else len(fingers) == self.spec.required_finger_groups and self.closed),
                "grasp_secured": self.contact_seconds >= .16, "support_contact": support,
                "stable_seconds": round(self.stable_seconds, 3), "success": bool(self.success()),
                "forbidden_contact": forbidden, "max_lift_m": round(self.max_lift, 4),
                **({"objects": [p.round(5).tolist() for p in self._all_cubes()],
                    "destinations": [t.round(5).tolist() for t in self.targets],
                    "placed": [bool(x) for x in self.placed],
                    "active_object": self.object_names[self.active_index]}
                   if len(self.cube_ids) > 1 else {}),
                "sim_seconds": round(float(self.data.time) - getattr(self, "start_time", 0), 3)}

    def frame(self):
        mujoco.mj_forward(self.model, self.data)
        return {"time": float(self.data.time), "qpos": self.data.qpos.tolist(),
                "positions": self.data.geom_xpos.round(5).tolist(),
                "rotations": self.data.geom_xmat.round(6).tolist(), "observation": self.observe()}

    def scene(self):
        geometries = []
        for i in range(self.model.ngeom):
            if int(self.model.geom_group[i]) == 3:
                continue
            material = int(self.model.geom_matid[i])
            color = self.model.mat_rgba[material] if material >= 0 else self.model.geom_rgba[i]
            geometries.append({"id": i, "name": self.model.geom(i).name or "", "type": int(self.model.geom_type[i]),
                               "size": self.model.geom_size[i].tolist(), "color": color.tolist(),
                               "mesh": int(self.model.geom_dataid[i])})
        mesh_ids = {g["mesh"] for g in geometries if g["type"] == int(mujoco.mjtGeom.mjGEOM_MESH)}
        meshes = {}
        for i in mesh_ids:
            va, vn = self.model.mesh_vertadr[i], self.model.mesh_vertnum[i]
            fa, fn = self.model.mesh_faceadr[i], self.model.mesh_facenum[i]
            meshes[str(i)] = {"vertices": self.model.mesh_vert[va:va + vn].tolist(),
                              "faces": self.model.mesh_face[fa:fa + fn].tolist()}
        return {"geometries": geometries, "meshes": meshes, "target": self.target.tolist(),
                "task": self.task, "seed": self.seed, "scene_hash": self.scene_hash,
                "scene_name": self.scene_name, "scene_config": copy.deepcopy(self.scene_config)}
