# Kinetics (`kense-labs/Kinetics`)

**全真机原厂 CAD · 基于决策模型的工业设备仿真对接与闭环操控平台**  
*1:1 Genuine CAD Industrial Equipment Simulation, Decision-Model Interfacing & Closed-Loop Control Platform by Kense*

[![License: MIT](https://img.shields.io/badge/Code%20License-MIT-0c6d54.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab.svg)](pyproject.toml)
[![Assets: 100% Genuine CAD](https://img.shields.io/badge/3D%20Models-100%25%20Genuine%20CAD-18846a.svg)](#全真机-cad-环境矩阵20-个可操控工业系统)

**Kinetics** 严选 **100% 真机原厂 CAD 与工程 STEP 装配体模型**（剔除一切低精度简模与程序化积木替代品），将 **5 台原厂 CAD 工业机械臂的高精度物理仿真（MuJoCo 500 Hz）** 与 **5 台百万面/千零件级工业装备真机 CAD 的 PLC 闭环控制及安全联锁** 统一到同一套 **“结构化观测 → 物理预演/工业联锁 → 决策模型推理 → 三维机构闭环执行”** 架构中。

---

## 全真机 CAD 环境矩阵（20 个可操控工业系统）

### A. 原厂 CAD 工业机械臂物理仿真（`mujoco/<robot>-<task>-v0`，共 15 个工艺环境）

| 机型（原厂 CAD） | 末端执行器 | 支持制造工序（Environment IDs） | 核心工艺与物理约束 |
| --- | --- | --- | --- |
| **Franka Emika Panda** | 平行伺服夹爪 | `panda-insert-v0`、`panda-tending-v0`、`panda-stack-v0`、`panda-transfer-v0` | 精密孔轴插装、机床滑门 I/O 协同上下料 |
| **Enactic OpenArm** | 原装平行夹爪 | `openarm-sort-v0`、`openarm-stack-v0`、`openarm-transfer-v0` | 双色工件分拣归盘 |
| **Universal Robots UR5e** | 平行夹爪（台座安装） | `ur5e-tending-v0`、`ur5e-weld-v0`、`ur5e-transfer-v0` | 2×2 铜柱 2mm 工艺间隙驻留点焊、机床上下料 |
| **UFACTORY xArm7** | 真空波纹管吸盘 | `xarm7-depalletize-v0`、`xarm7-palletize-v0` | 顶面吸附高速拆垛上料、辊筒排队码垛下线 |
| **Kinova Gen3** | 平行夹爪 + 视觉腕环 | `gen3-kitting-v0`、`gen3-glue-v0`、`gen3-barrier-v0` | 四件套精密摆盘、壳体密封槽 6 点驻留涂胶 |

### B. 工程级真机 CAD 产线装备闭环操控（`equipment/<id>-v0`，共 5 台真机 CAD 装备）

| Environment ID | 装备名称 | 真机 CAD 精度规格 | 核心安全联锁与闭环动作 |
| --- | --- | --- | --- |
| `equipment/sorting_line-v0` | **智能视觉分拣流水线** | **330,366 顶点 / 90 网格** 直辊筒线 ×3 节真机 CAD | 39 辊真转 + 光幕识别 + 摆臂分流；滑道满溢防堵联锁 |
| `equipment/forklift-v0` | **平衡重式智能叉车** | **37 万三角面 + 2K D/N/ORM PBR 贴图** 真机 CAD | 二级液压门架升降后倾；货叉 `>=0.18m` **高位禁行防倾翻联锁** |
| `equipment/kr210-v0` | **KUKA KR210 重载六轴工位** | **196,952 顶点** KUKA KR210_L150 真机 CAD | 六轴全关节运动链驱动；**气动工装未压紧严禁点焊联锁** |
| `equipment/robot_cell-v0` | **KUKA iiwa 14 精密装配台** | **46,730 顶点** Drake/Menagerie 原厂 CAD + 法兰螺栓 | 七轴阻抗力控柔顺压装（`<18N` 过载保护）+ TCP 荧光轨迹 |
| `equipment/voron_printer-v0` | **Voron 2.4 工业增材整机** | **7,433 真实零件 / 120 万顶点** 241MB 官方 STEP 直转 | 烟色透明亚克力封箱透视内部机构；CoreXY 飞行龙门调平 + **230°C 防冷挤出联锁** |

> 此外左侧栏还内置 **Franka Panda / UR5e / xArm7 / Kinova Gen3** 四台原厂 CAD 连杆树独立拆解展台，支持一键黄金角螺旋爆炸拆解与中文部件功能卡。

---

## 快速开始

### 1. 安装与启动 Web 操控台

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"

# 若修改了 frontend/ 源码，重新构建前端产物
npm ci && npm run build

# 启动三维操控台 + REST / WebSocket 控制总线
kinetics serve --port 8090
```

浏览器打开 `http://127.0.0.1:8090` 即可在线切换真机 CAD 装备、连接外部大模型（OpenAI / Qwen / DeepSeek / Claude / Jev）、触发单步/连续闭环推理、测试动作直控安全联锁与硬件急停（E-STOP），或一键展开零件级爆炸图。

### 2. 外部模型对接（Gym Python SDK / REST / WebSocket）

完整接口说明见 [docs/SDK_AND_PROTOCOL.md](docs/SDK_AND_PROTOCOL.md) 与 [examples/](examples/)：

```python
import kense_sim

env = kense_sim.make("equipment/forklift-v0", seed=0, safety_preview=True)
obs, info = env.reset(seed=0)
openai_tools = env.to_openai_tools()  # 一键导出当前安全合法动作的 OpenAI Tool Schema

while True:
    action = info["baseline_action"]  # 替换为你的 LLM / VLA 策略输出
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        break
```

---

## 工业 STEP → GLB 真机 CAD 量产管线

若需接入更多厂商原厂 STEP 装配体（SolidWorks / Creo / NX 导出的 `.step`），直接使用内置无损装配树转换管线（详见 [docs/MODELING_PIPELINE.md](docs/MODELING_PIPELINE.md)）：

```bash
python3 -m venv .venv-cad && .venv-cad/bin/pip install -r tools/requirements-cad.txt
.venv-cad/bin/python tools/step_to_glb.py <真机装配体.step> frontend/public/twin-assets/<id>.glb
```

---

## 开源协议与第三方资产说明

- 本项目源码采用 **MIT License**（见 [LICENSE](LICENSE)），基础工作台架构致谢 [FBddcz/embodied-jev](https://github.com/FBddcz/embodied-jev)。
- 随仓真机 CAD 资产各自的许可条款与商业分发注意事项详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
