"""Deterministic kinematic & process-control simulation for genuine CAD industrial equipment.

Provides closed-loop observation, safety-interlock shadow preview, discrete action spaces,
emergency-stop (E-Stop) handling, 3D scene-graph actuator outputs, and DecisionPolicy
session execution exclusively for real engineering-CAD digital-twin equipment:
  1. sorting_line  — Industrial roller conveyor sorting line (330k-vertex CAD)
  2. forklift      — Counterbalance industrial forklift (161k-vertex PBR CAD)
  3. kr210         — KUKA KR210_L150 6-axis heavy robot workstation (197k-vertex CAD)
  4. robot_cell    — KUKA LBR iiwa 14 7-axis force-controlled cell (47k-vertex CAD)
  5. voron_printer — Voron 2.4r2 CoreXY additive manufacturing machine (7,433-part STEP CAD)
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import random
import threading
import uuid

from .policies import DecisionPolicy


@dataclass(frozen=True)
class EquipmentSpec:
    id: str
    name: str
    category: str
    subtitle: str
    goal: str
    metric_name: str
    metric_unit: str
    default_target: int
    max_cycles: int


EQUIPMENT_SPECS: dict[str, EquipmentSpec] = {
    "sorting_line": EquipmentSpec(
        id="sorting_line",
        name="智能视觉分拣流水线",
        category="产线物流 · 真机 CAD",
        subtitle="三联直辊筒动力输送线 + 光幕视觉识别 + 摆臂分流滑道",
        goal="扫描混流包裹并按 SKU 类型精准分流或直通，避免滑道满溢卡件",
        metric_name="已分拣包裹",
        metric_unit="件",
        default_target=6,
        max_cycles=36,
    ),
    "forklift": EquipmentSpec(
        id="forklift",
        name="平衡重式智能叉车",
        category="仓储搬运 · 真机 CAD",
        subtitle="37 万面 PBR 真机 CAD · 二级门架升降后倾 + 高位禁行防倾翻联锁",
        goal="在装卸月台叉取托盘，保持低位安全行驶至高位货架完成举升上架",
        metric_name="上架托盘",
        metric_unit="托",
        default_target=3,
        max_cycles=32,
    ),
    "kr210": EquipmentSpec(
        id="kr210",
        name="KUKA KR210 重载六轴工位",
        category="重载制造 · 真机 CAD",
        subtitle="210kg 重载六轴原厂 CAD · 全运动链驱动 + 气动夹具点焊联锁",
        goal="从上料台抓取毛坯装入焊接夹具，确认夹具锁紧后完成点焊并下料",
        metric_name="完工工件",
        metric_unit="件",
        default_target=3,
        max_cycles=32,
    ),
    "robot_cell": EquipmentSpec(
        id="robot_cell",
        name="KUKA iiwa 14 精密装配台",
        category="柔顺装配 · 真机 CAD",
        subtitle="LBR iiwa 14 原厂七轴 CAD · 阻抗柔顺插装过载保护",
        goal="拾取精密壳体对准工装巢位，在接触力阈值内完成柔顺压装归位",
        metric_name="装配总成",
        metric_unit="件",
        default_target=3,
        max_cycles=30,
    ),
    "voron_printer": EquipmentSpec(
        id="voron_printer",
        name="Voron 2.4 工业增材制造整机",
        category="增材制造 · 7433件 STEP CAD",
        subtitle="241MB 工程 STEP 直转 · CoreXY 飞行龙门四轴调平与防冷挤出联锁",
        goal="完成热床/喷头预热、CoreXY 回零与四轴龙门调平(QGL)，安全闭环打印工业结构件",
        metric_name="成型零件",
        metric_unit="件",
        default_target=3,
        max_cycles=32,
    ),
}


@dataclass
class EquipmentActionCandidate:
    id: str
    label: str
    description: str
    seconds: float
    admitted: bool = True
    rejection: str | None = None
    preview: dict | None = None

    def serialise(self) -> dict:
        return asdict(self)


class EquipmentWorld:
    """Deterministic discrete-event + continuous-coordinate industrial CAD equipment simulator."""

    def __init__(self, equipment_id: str, seed: int = 0, target_override: int | None = None):
        if equipment_id not in EQUIPMENT_SPECS:
            raise ValueError(f"Unknown CAD equipment '{equipment_id}'. Valid: {sorted(EQUIPMENT_SPECS)}")
        self.spec = EQUIPMENT_SPECS[equipment_id]
        self.equipment_id = equipment_id
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        self.target_count = int(target_override or self.spec.default_target)
        self.sim_seconds = 0.0
        self.completed = 0
        self.interlock_trips = 0
        self.estop = False
        self.finished = False
        self.last_action: str | None = None
        self.state = self._init_state()

    def clone(self) -> "EquipmentWorld":
        return copy.deepcopy(self)

    def _init_state(self) -> dict:
        eid = self.equipment_id
        if eid == "sorting_line":
            classes = ["divert" if (i + self.seed) % 2 == 1 else "standard" for i in range(self.target_count + 2)]
            return {
                "active_sku": classes[0],
                "queue": classes[1:],
                "scanned": False,
                "diverter_deg": 85.0,
                "chute_buffer": 0,
                "chute_capacity": 2,
                "belt_speed_mps": 0.85,
                "parcel_x_m": -2.5,
                "parcel_z_m": 0.0,
            }
        if eid == "forklift":
            return {
                "chassis_z_m": 0.0,
                "fork_lift_m": 0.04,
                "mast_tilt_deg": 0.0,
                "pallet_loaded": False,
            }
        if eid == "kr210":
            return {
                "pose_stage": "home",
                "joints_rad": [0.0, 0.05, 0.10, 0.0, 0.10, 0.0],
                "holding": False,
                "fixture_clamped": False,
                "part_welded": False,
            }
        if eid == "robot_cell":
            return {
                "pose_stage": "home",
                "joints_rad": [0.0, -0.25, 0.0, -1.35, 0.0, 0.95, 0.0],
                "jaw_open_m": 0.014,
                "holding": False,
                "aligned": False,
                "contact_force_n": 0.0,
            }
        if eid == "voron_printer":
            return {
                "nozzle_temp_c": 28.0,
                "bed_temp_c": 26.0,
                "homed": False,
                "qgl_leveled": False,
                "part_printed": False,
                "gantry_z_mm": 45.0,
                "tool_x_mm": 0.0,
                "tool_y_mm": 0.0,
            }
        raise AssertionError("Unhandled CAD equipment")

    def success(self) -> bool:
        return self.completed >= self.target_count and self.finished and not self.estop

    def action_catalog(self) -> dict[str, tuple[str, str, float]]:
        eid = self.equipment_id
        if eid == "sorting_line":
            return {
                "feed_and_scan": ("推进过检扫描", "驱动 39 辊动力输送线，送入来料包裹通过光幕视觉门架识别 SKU 类别。", 1.1),
                "divert_to_chute": ("摆臂拨入滑道", "摆动分拣拨杆横跨主线，将异常/专线包裹精准导入侧向分流滑道。", 1.2),
                "pass_mainline": ("收臂主线直通", "分拣拨杆收回至 85° 安全避让位，放行标准件沿主辊道直通出线。", 1.1),
                "discharge_chute": ("清空分流滑道", "排空分流滑道周转箱内已积攒的包裹，释放滑道缓存容量防卡件。", 0.9),
                "finish": ("完工确认", "确认当前批次包裹已全部分拣完毕且零堵线，闭环收尾。", 0.4),
            }
        if eid == "forklift":
            return {
                "drive_to_dock": ("低位驶往月台取货区", "保持门架低位 (<0.18m) 空载安全行驶至装卸月台取货工位 (z=-0.52m)。", 1.4),
                "engage_and_tilt": ("叉取托盘并门架后倾", "货叉插入标准托盘并微抬至 0.14m 低位行车高度，门架后倾 2.6° 稳固重心。", 1.2),
                "transport_to_rack": ("低位安全转运至货架", "满载保持低重心安全高度 (<0.18m)，平稳行驶至高位货架立柱位 (z=+0.52m)。", 1.6),
                "elevate_to_beam": ("门架举升至高层横梁", "底盘驻车制动锁止，二级液压门架平稳举升托盘至 1.10m 高层横梁高度。", 1.5),
                "place_and_lower": ("落托上架并降叉复位", "将托盘精准落放于货架横梁，退出货叉并降回 0.06m 安全待命高度。", 1.4),
                "finish": ("完工确认", "确认计划批次托盘已全部安全上架归位。", 0.4),
            }
        if eid == "kr210":
            return {
                "approach_feeder": ("六轴移至来料台", "驱动 210kg 重载六轴机械臂移至毛坯上料台抓取准备姿态。", 1.1),
                "grip_billet": ("气动夹爪抓取毛坯", "闭合重载气动平行夹爪，稳固夹持待焊金属毛坯件。", 0.7),
                "load_weld_fixture": ("装入工装并压紧锁死", "将毛坯放入焊接工装定位巢，触发气动夹具压紧锁死。", 1.3),
                "spot_weld_cycle": ("执行多点焊接轨迹", "确认工装夹具锁紧到位后，沿焊缝执行多点电阻点焊节拍。", 1.4),
                "unclamp_and_offload": ("松夹具并下料码放", "释放焊接工装夹具，抓取成型焊件移至下料架松爪码放。", 1.3),
                "finish": ("完工确认", "确认重载点焊工位当前批次工件全部完工。", 0.4),
            }
        if eid == "robot_cell":
            return {
                "pick_housing": ("拾取精密待装壳体", "七轴力控协作臂移至供料位，伺服平行夹爪轻柔抓取精密壳体。", 1.1),
                "align_above_nest": ("移至装配巢上方对中", "携壳体运行至装配工装巢正上方完成同轴视觉/几何对中。", 1.1),
                "compliant_insert": ("阻抗力控柔顺压装", "启用关节阻抗柔顺控制，在接触力安全阈值 (<18 N) 内下压插装到位。", 1.3),
                "release_and_retract": ("松爪释放并安全撤离", "张开平行夹爪释放已压装总成，机械臂平滑抬升撤回安全位。", 1.0),
                "finish": ("完工确认", "确认精密柔顺压装批次已全部达标完成。", 0.4),
            }
        if eid == "voron_printer":
            return {
                "preheat_hotend_bed": ("热床与喷头闭环预热", "PEI 磁吸热床升温至 105°C、喷嘴升温至 245°C 工程材料熔融区间。", 1.2),
                "home_and_qgl": ("CoreXY 回零与四轴调平", "执行三轴归零与四角探测龙门调平 (Quad Gantry Leveling)，校准热膨胀平面。", 1.3),
                "extrude_part_layers": ("高速轨迹挤出打印", "启动飞行龙门高速 CoreXY 路径挤出成型，同步开启尾部活性炭排风过滤。", 1.6),
                "retract_and_release": ("抬升龙门退驻取件位", "抽回耗材防拉丝，Z 轴飞行龙门抬升至 145mm 驻留位完成单件成型。", 1.1),
                "finish": ("完工确认", "确认工业增材制造整机当前批次零件全部成型。", 0.4),
            }
        raise AssertionError("Unhandled CAD equipment")

    def _check_interlock(self, action: str) -> str | None:
        if self.estop:
            return "急停联锁激活中 (E-Stop Engaged)：必须先解除急停才能执行机构动作"
        if action not in self.action_catalog():
            return f"未知控制动作 '{action}'"
        if action == "finish":
            if self.completed < self.target_count:
                return f"未达目标节拍 ({self.completed}/{self.target_count} {self.spec.metric_unit})，不可提前完工"
            return None

        s = self.state
        eid = self.equipment_id
        if eid == "sorting_line":
            if action == "feed_and_scan" and s["scanned"]:
                return "当前包裹已完成视觉扫描，请先执行分流或直通决策，避免后件追尾叠件"
            if action in {"divert_to_chute", "pass_mainline"} and not s["scanned"]:
                return "包裹尚未经过光幕视觉识别，禁止盲拨分拣杆"
            if action == "divert_to_chute":
                if s["chute_buffer"] >= s["chute_capacity"]:
                    return "安全联锁：分流滑道缓存已满，强行拨件会导致滑道拥堵卡件，请先清空滑道"
                if s["active_sku"] != "divert":
                    return "质量联锁：当前包裹为直通标准件，禁止误拨入分流滑道"
            if action == "pass_mainline" and s["active_sku"] == "divert":
                return "质量联锁：当前包裹为待分流异常/专线件，禁止直通放行"
            if action == "discharge_chute" and s["chute_buffer"] == 0:
                return "分流滑道当前为空，无需执行排空动作"

        elif eid == "forklift":
            if action in {"drive_to_dock", "transport_to_rack"} and s["fork_lift_m"] >= 0.18:
                return "高位禁行安全联锁：货叉高度 >= 0.18m 时重心过高，严禁底盘移动防倾翻！"
            if action == "drive_to_dock" and s["pallet_loaded"]:
                return "叉车已载货，应转运至货架而非返回取货月台"
            if action == "engage_and_tilt":
                if s["pallet_loaded"]:
                    return "货叉已承载托盘"
                if s["chassis_z_m"] > -0.4:
                    return "叉车尚未到达装卸月台取货位"
            if action == "transport_to_rack" and not s["pallet_loaded"]:
                return "货叉空载，请先在月台叉取托盘"
            if action == "elevate_to_beam":
                if not s["pallet_loaded"]:
                    return "空载无需举升至高层货架"
                if s["chassis_z_m"] < 0.4:
                    return "叉车尚未停靠货架立柱位，禁止提前高位举升"
            if action == "place_and_lower":
                if not s["pallet_loaded"] or s["fork_lift_m"] < 0.95:
                    return "托盘尚未举升至目标货架横梁高度 (1.10m)，无法落托上架"

        elif eid == "kr210":
            if action == "approach_feeder" and s["holding"]:
                return "夹爪已持件，请装入焊接工装"
            if action == "grip_billet" and (s["holding"] or s["pose_stage"] != "feeder"):
                return "机械臂未在来料台位或已持件"
            if action == "load_weld_fixture" and not s["holding"]:
                return "夹爪空载，无法装入工装"
            if action == "spot_weld_cycle":
                if not s["fixture_clamped"]:
                    return "工装联锁：气动夹具未锁紧工件，严禁启动点焊防飞溅移位！"
                if s["part_welded"]:
                    return "当前工件已完成点焊，请松开夹具下料"
            if action == "unclamp_and_offload" and not s["part_welded"]:
                return "工件尚未完成点焊工序，禁止提前松夹下料"

        elif eid == "robot_cell":
            if action == "pick_housing" and s["holding"]:
                return "夹爪已持壳体"
            if action == "align_above_nest" and not s["holding"]:
                return "夹爪未持壳体，请先取料"
            if action == "compliant_insert" and (not s["holding"] or not s["aligned"]):
                return "壳体尚未在装配巢正上方同轴对中，禁止盲压防过载卡死"
            if action == "release_and_retract" and s["pose_stage"] != "inserted":
                return "壳体尚未压装到位，禁止提前松开夹爪"

        elif eid == "voron_printer":
            if action == "preheat_hotend_bed" and s["nozzle_temp_c"] >= 230.0:
                return "喷头与热床已处于目标恒温区间"
            if action == "home_and_qgl":
                if s["nozzle_temp_c"] < 150.0:
                    return "热膨胀补偿联锁：请先预热热床与喷头再执行四轴龙门调平 (QGL)"
                if s["qgl_leveled"]:
                    return "当前批次已完成四轴龙门调平"
            if action == "extrude_part_layers":
                if s["nozzle_temp_c"] < 230.0:
                    return "防冷挤出安全联锁：喷嘴温度未达 230°C 熔融阈值，严禁启动挤出电机！"
                if not s["homed"] or not s["qgl_leveled"]:
                    return "运动安全联锁：CoreXY 飞行龙门尚未完成回零与四轴调平，严禁打印防撞热床！"
                if s["part_printed"]:
                    return "当前零件已完成打印，请抬升龙门退驻取件"
            if action == "retract_and_release" and not s["part_printed"]:
                return "零件尚未完成打印成型，禁止提前退驻中断"

        return None

    def baseline_action(self) -> str:
        if self.completed >= self.target_count:
            return "finish"
        s = self.state
        eid = self.equipment_id
        if eid == "sorting_line":
            if s["chute_buffer"] >= s["chute_capacity"]:
                return "discharge_chute"
            if not s["scanned"]:
                return "feed_and_scan"
            return "divert_to_chute" if s["active_sku"] == "divert" else "pass_mainline"
        if eid == "forklift":
            if not s["pallet_loaded"]:
                return "drive_to_dock" if s["chassis_z_m"] > -0.4 else "engage_and_tilt"
            if s["chassis_z_m"] < 0.4:
                return "transport_to_rack"
            return "elevate_to_beam" if s["fork_lift_m"] < 0.95 else "place_and_lower"
        if eid == "kr210":
            if not s["holding"]:
                return "approach_feeder" if s["pose_stage"] != "feeder" else "grip_billet"
            if not s["fixture_clamped"]:
                return "load_weld_fixture"
            return "spot_weld_cycle" if not s["part_welded"] else "unclamp_and_offload"
        if eid == "robot_cell":
            if not s["holding"]:
                return "pick_housing"
            if not s["aligned"]:
                return "align_above_nest"
            return "compliant_insert" if s["pose_stage"] != "inserted" else "release_and_retract"
        if eid == "voron_printer":
            if s["nozzle_temp_c"] < 230.0:
                return "preheat_hotend_bed"
            if not s["qgl_leveled"]:
                return "home_and_qgl"
            return "extrude_part_layers" if not s["part_printed"] else "retract_and_release"
        raise AssertionError("Unhandled CAD equipment")

    def candidates(self, preview: bool = True) -> list[EquipmentActionCandidate]:
        catalog = self.action_catalog()
        result: list[EquipmentActionCandidate] = []
        for aid, (label, desc, dur) in catalog.items():
            rejection = self._check_interlock(aid)
            cand = EquipmentActionCandidate(
                id=aid,
                label=label,
                description=desc,
                seconds=dur,
                admitted=rejection is None,
                rejection=rejection,
            )
            if preview and cand.admitted:
                shadow = self.clone()
                shadow.apply_action(aid)
                obs = shadow.observe()
                cand.preview = {
                    "completed": obs["completed"],
                    "progress_pct": obs["progress_pct"],
                    "sim_seconds": obs["sim_seconds"],
                    "safe": True,
                }
            elif preview:
                cand.preview = {"safe": False, "rejection": rejection}
            result.append(cand)
        return result

    def apply_action(self, action: str) -> dict:
        rejection = self._check_interlock(action)
        if rejection is not None:
            self.interlock_trips += 1
            raise ValueError(rejection)

        _, _, dur = self.action_catalog()[action]
        self.sim_seconds = round(self.sim_seconds + dur, 3)
        self.last_action = action
        if action == "finish":
            self.finished = True
            return self.observe()

        s = self.state
        eid = self.equipment_id
        if eid == "sorting_line":
            if action == "feed_and_scan":
                s["scanned"] = True
                s["parcel_x_m"] = 0.6
                s["parcel_z_m"] = 0.0
            elif action == "divert_to_chute":
                s["diverter_deg"] = 0.0
                s["parcel_x_m"] = 2.2
                s["parcel_z_m"] = -0.98
                s["chute_buffer"] += 1
                self.completed += 1
                self._advance_parcel()
            elif action == "pass_mainline":
                s["diverter_deg"] = 85.0
                s["parcel_x_m"] = 3.4
                s["parcel_z_m"] = 0.0
                self.completed += 1
                self._advance_parcel()
            elif action == "discharge_chute":
                s["chute_buffer"] = 0

        elif eid == "forklift":
            if action == "drive_to_dock":
                s["chassis_z_m"] = -0.52
                s["mast_tilt_deg"] = 0.0
            elif action == "engage_and_tilt":
                s["fork_lift_m"] = 0.14
                s["mast_tilt_deg"] = -2.6
                s["pallet_loaded"] = True
            elif action == "transport_to_rack":
                s["chassis_z_m"] = 0.52
            elif action == "elevate_to_beam":
                s["fork_lift_m"] = 1.10
                s["mast_tilt_deg"] = -2.8
            elif action == "place_and_lower":
                s["pallet_loaded"] = False
                s["mast_tilt_deg"] = 0.0
                s["fork_lift_m"] = 0.06
                self.completed += 1

        elif eid == "kr210":
            if action == "approach_feeder":
                s["pose_stage"] = "feeder"
                s["joints_rad"] = [-0.46, 0.22, 0.28, 0.0, 0.24, 0.0]
            elif action == "grip_billet":
                s["holding"] = True
            elif action == "load_weld_fixture":
                s["pose_stage"] = "fixture"
                s["joints_rad"] = [0.36, -0.18, -0.22, 0.28, -0.20, 0.35]
                s["fixture_clamped"] = True
                s["part_welded"] = False
            elif action == "spot_weld_cycle":
                s["pose_stage"] = "welded"
                s["joints_rad"] = [0.42, -0.22, -0.30, -0.32, 0.26, -0.45]
                s["part_welded"] = True
            elif action == "unclamp_and_offload":
                s["pose_stage"] = "offload"
                s["joints_rad"] = [0.05, 0.12, 0.16, 0.0, 0.12, 0.0]
                s["fixture_clamped"] = False
                s["holding"] = False
                s["part_welded"] = False
                self.completed += 1

        elif eid == "robot_cell":
            if action == "pick_housing":
                s["pose_stage"] = "picked"
                s["joints_rad"] = [-0.38, 0.20, 0.0, -1.18, 0.0, 0.85, 0.25]
                s["jaw_open_m"] = 0.002
                s["holding"] = True
                s["aligned"] = False
            elif action == "align_above_nest":
                s["pose_stage"] = "aligned"
                s["joints_rad"] = [0.28, -0.12, 0.0, -1.32, 0.15, 0.92, -0.20]
                s["aligned"] = True
                s["contact_force_n"] = 1.2
            elif action == "compliant_insert":
                s["pose_stage"] = "inserted"
                s["joints_rad"] = [0.28, 0.04, 0.0, -1.46, 0.15, 1.05, -0.20]
                s["contact_force_n"] = 11.4
            elif action == "release_and_retract":
                s["pose_stage"] = "home"
                s["joints_rad"] = [0.0, -0.25, 0.0, -1.35, 0.0, 0.95, 0.0]
                s["jaw_open_m"] = 0.014
                s["holding"] = False
                s["aligned"] = False
                s["contact_force_n"] = 0.0
                self.completed += 1

        elif eid == "voron_printer":
            if action == "preheat_hotend_bed":
                s["nozzle_temp_c"] = 245.0
                s["bed_temp_c"] = 105.0
            elif action == "home_and_qgl":
                s["homed"] = True
                s["qgl_leveled"] = True
                s["gantry_z_mm"] = 8.0
                s["tool_x_mm"] = -65.0
                s["tool_y_mm"] = -65.0
            elif action == "extrude_part_layers":
                s["part_printed"] = True
                s["gantry_z_mm"] = 72.0
                s["tool_x_mm"] = 55.0
                s["tool_y_mm"] = 48.0
            elif action == "retract_and_release":
                s["part_printed"] = False
                s["qgl_leveled"] = False
                s["gantry_z_mm"] = 145.0
                s["tool_x_mm"] = 0.0
                s["tool_y_mm"] = 90.0
                self.completed += 1

        return self.observe()

    def _advance_parcel(self) -> None:
        s = self.state
        s["scanned"] = False
        if s["queue"]:
            s["active_sku"] = s["queue"].pop(0)
        else:
            s["active_sku"] = "standard"

    def actuator_pose(self) -> dict:
        s = self.state
        eid = self.equipment_id
        if eid == "sorting_line":
            return {
                "diverter_rad": round(math.radians(s["diverter_deg"]), 4),
                "parcel_x": s["parcel_x_m"],
                "parcel_z": s["parcel_z_m"],
                "scanning": s["scanned"],
                "diverting": s["diverter_deg"] < 30.0,
                "chute_full": s["chute_buffer"] >= s["chute_capacity"],
            }
        if eid == "forklift":
            return {
                "chassis_z": s["chassis_z_m"],
                "fork_lift": s["fork_lift_m"],
                "mast_tilt_rad": round(math.radians(s["mast_tilt_deg"]), 4),
                "pallet_loaded": s["pallet_loaded"],
            }
        if eid in {"kr210", "robot_cell"}:
            return {
                "joints_rad": list(s["joints_rad"]),
                "jaw_open_m": s.get("jaw_open_m", 0.0 if s["holding"] else 0.016),
                "holding": s["holding"],
            }
        if eid == "voron_printer":
            return {
                "gantry_z_mm": s["gantry_z_mm"],
                "tool_x_mm": s["tool_x_mm"],
                "tool_y_mm": s["tool_y_mm"],
                "printing": s["part_printed"],
            }
        return {}

    def observe(self) -> dict:
        pct = min(100, round((self.completed / max(1, self.target_count)) * 100))
        return {
            "domain": "equipment",
            "equipment_id": self.equipment_id,
            "equipment_name": self.spec.name,
            "category": self.spec.category,
            "goal": self.spec.goal,
            "sim_seconds": self.sim_seconds,
            "completed": self.completed,
            "target": self.target_count,
            "unit": self.spec.metric_unit,
            "progress_pct": pct,
            "success": self.success(),
            "estop": self.estop,
            "interlock_trips": self.interlock_trips,
            "last_action": self.last_action,
            "telemetry": copy.deepcopy(self.state),
            "actuators": self.actuator_pose(),
        }


class EquipmentSession:
    """Thread-safe closed-loop decision-model controller session for CAD industrial equipment."""

    def __init__(
        self,
        equipment_id: str = "sorting_line",
        seed: int = 0,
        provider: str = "baseline",
        preview: bool = True,
        threshold: float = 0.55,
        max_cycles: int | None = None,
        speed: float = 1.5,
        connection: dict | None = None,
        target: int | None = None,
    ):
        self.id = uuid.uuid4().hex[:10]
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.world = EquipmentWorld(equipment_id, seed=seed, target_override=target)
        self.policy = DecisionPolicy(provider, connection)
        self.profile_id = (connection or {}).get("profile_id")
        self.preview = bool(preview)
        self.threshold = float(threshold)
        self.speed = float(speed)
        self.max_cycles = int(max_cycles or self.world.spec.max_cycles)
        self.status = "idle"
        self.error: str | None = None
        self.cycles = 0
        self.history: list[dict] = []
        self.last_decision: dict | None = None
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.wake = threading.Event()
        self.worker: threading.Thread | None = None

    def start(self, single_step: bool = False, threshold: float | None = None) -> None:
        with self.lock:
            if self.world.estop:
                raise ValueError("急停已按下 (E-Stop Engaged)，请先解除急停再启动决策控制")
            if self.status in {"completed", "stopped", "error", "exhausted"}:
                raise ValueError("当前会话已结束，请先重置后再启动")
            if threshold is not None:
                self.threshold = float(threshold)
            if self.status == "running":
                return
            self.status = "running"
            self.cancel.clear()
            self.wake.set()
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._loop, args=(single_step,), daemon=True)
                self.worker.start()

    def pause(self) -> None:
        with self.lock:
            if self.status == "running":
                self.status = "paused"
                self.cancel.set()

    def stop(self) -> None:
        with self.lock:
            self.cancel.set()
            if self.status not in {"completed", "error", "exhausted"}:
                self.status = "stopped"
        if self.worker is not None and self.worker.is_alive() and threading.current_thread() is not self.worker:
            self.worker.join(timeout=2.0)
        self.policy.close()

    def set_estop(self, engaged: bool) -> dict:
        with self.lock:
            self.world.estop = bool(engaged)
            if engaged and self.status == "running":
                self.status = "paused"
                self.cancel.set()
            elif not engaged and self.error and "急停" in self.error:
                self.error = None
            return self.snapshot()

    def step_once(self, *, pause_after: bool = False) -> dict:
        with self.lock:
            if self.world.estop:
                raise ValueError("急停联锁激活中 (E-Stop Engaged)")
            if self.world.success():
                self.status = "completed"
                return self.snapshot()
            if self.cycles >= self.max_cycles:
                self.status = "exhausted"
                return self.snapshot()

            self.error = None
            before = self.world.observe()
            cands = self.world.candidates(preview=self.preview)
            admitted = {c.id: f"{c.label}: {c.description}" for c in cands if c.admitted}
            if not admitted:
                self.status = "error"
                self.error = "所有动作均被安全联锁拦截，请检查设备状态或重置"
                return self.snapshot()

            baseline = self.world.baseline_action()
            if baseline not in admitted:
                baseline = next(iter(admitted))

            question = (
                f"Control industrial equipment '{self.world.spec.name}'. Goal: {self.world.spec.goal}. "
                f"Choose the safest and most productive admitted control action."
            )
            decision = self.policy.choose(before, question, admitted, baseline, self.history[-6:])
            chosen = decision["choice"]
            sel_prob = decision.get("selected_probability")
            if sel_prob is not None and sel_prob < self.threshold:
                self.status = "paused"
                self.error = f"模型置信度 {sel_prob:.2f} 低于安全阈值 {self.threshold:.2f}，已自动暂停等待人工确认"
                self.last_decision = {**decision, "candidates": [c.serialise() for c in cands], "executed": False}
                return self.snapshot()

            after = self.world.apply_action(chosen)
            self.cycles += 1
            record = {
                "cycle": self.cycles,
                "action": chosen,
                "action_label": self.world.action_catalog()[chosen][0],
                "provider": self.policy.provider,
                "model": self.policy.model,
                "decision": decision,
                "decision_input": self.policy.last_input,
                "candidates": [c.serialise() for c in cands],
                "before": before,
                "after": after,
            }
            self.history.append(record)
            self.last_decision = record
            if self.world.success():
                self.status = "completed"
            elif self.cycles >= self.max_cycles:
                self.status = "exhausted"
            elif pause_after and self.status == "idle":
                self.status = "paused"
            return self.snapshot()

    def actuate_manual(self, action: str) -> dict:
        with self.lock:
            if self.world.finished or self.status == "completed":
                raise ValueError("当前批次已达标完工，请先重置设备再执行新批次动作")
            before = self.world.observe()
            cands = self.world.candidates(preview=self.preview)
            after = self.world.apply_action(action)
            self.error = None
            self.cycles += 1
            record = {
                "cycle": self.cycles,
                "action": action,
                "action_label": self.world.action_catalog()[action][0],
                "provider": "external_override",
                "model": "manual_or_sdk",
                "decision": {"choice": action, "probabilities": {action: 1.0}, "latency_ms": 0, "model_call": False},
                "decision_input": None,
                "candidates": [c.serialise() for c in cands],
                "before": before,
                "after": after,
            }
            self.history.append(record)
            self.last_decision = record
            if self.world.success():
                self.status = "completed"
            elif self.cycles >= self.max_cycles:
                self.status = "exhausted"
            elif self.status == "idle":
                self.status = "paused"
            return self.snapshot()

    def _loop(self, single_step: bool = False) -> None:
        try:
            while not self.cancel.is_set():
                snap = self.step_once()
                if single_step or snap["status"] in {"completed", "exhausted", "error", "paused", "stopped"}:
                    with self.lock:
                        if single_step and self.status == "running":
                            self.status = "paused"
                    break
                delay = max(0.08, 0.42 / max(0.25, self.speed))
                if self.cancel.wait(delay):
                    break
        except Exception as exc:
            with self.lock:
                self.status = "error"
                self.error = str(exc)

    def snapshot(self) -> dict:
        with self.lock:
            obs = self.world.observe()
            cands = [c.serialise() for c in self.world.candidates(preview=self.preview)]
            return {
                "id": self.id,
                "domain": "equipment",
                "equipment_id": self.world.equipment_id,
                "equipment_name": self.world.spec.name,
                "category": self.world.spec.category,
                "subtitle": self.world.spec.subtitle,
                "status": self.status,
                "error": self.error,
                "seed": self.world.seed,
                "provider": self.policy.provider,
                "profile_id": self.profile_id,
                "model": self.policy.model,
                "preview": self.preview,
                "threshold": self.threshold,
                "speed": self.speed,
                "cycles": self.cycles,
                "max_cycles": self.max_cycles,
                "observation": obs,
                "candidates": cands,
                "baseline_action": self.world.baseline_action() if not obs["estop"] else None,
                "last_decision": self.last_decision,
                "history": self.history[-25:],
                "metrics": {
                    "model_calls": self.policy.calls,
                    "input_tokens": self.policy.tokens,
                    "output_tokens": self.policy.output_tokens,
                    "avg_latency_ms": round(sum(self.policy.latencies) / len(self.policy.latencies), 1)
                    if self.policy.latencies else 0,
                },
            }

    def export(self) -> dict:
        with self.lock:
            return {
                "schema": "kense.industrial.equipment_episode.v1",
                "created_at": self.created_at,
                "snapshot": self.snapshot(),
                "full_history": self.history,
            }


def run_equipment_headless(
    equipment_id: str,
    seed: int = 0,
    provider: str = "baseline",
    connection: dict | None = None,
    max_cycles: int | None = None,
) -> EquipmentSession:
    session = EquipmentSession(
        equipment_id=equipment_id,
        seed=seed,
        provider=provider,
        connection=connection,
        max_cycles=max_cycles,
    )
    try:
        while session.status not in {"completed", "exhausted", "error"}:
            session.step_once()
            if session.status == "paused":
                break
        return session
    finally:
        session.policy.close()
