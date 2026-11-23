# External Decision-Model SDK & Control Protocol (`kense_sim` / v1 API)

`kense-industrial-sim` exposes **26 industrial simulation environments** (`15` MuJoCo robotic arm process tasks + `11` industrial equipment digital twins) through three equivalent interfaces:

1. **In-Process Python Gym SDK (`import kense_sim`)**
2. **HTTP REST Control API (`/api/v1/env/*` & `KenseSimClient`)**
3. **Full-Duplex Real-Time WebSocket Bus (`ws://127.0.0.1:8090/ws/v1/control` & `KenseWebSocketClient`)**

---

## 1. Python Gym-Style SDK

```python
import kense_sim

# Inspect all 26 environments ("mujoco/*" and "equipment/*")
envs = kense_sim.list_environments()

# Create an environment with shadow safety-interlock preview enabled
env = kense_sim.make("equipment/sts_crane-v0", seed=0, safety_preview=True)
obs, info = env.reset(seed=0)

# info["valid_actions"]: dict[action_id, description] of safety-admitted actions
# info["rejected_actions"]: dict[action_id, rejection_reason] blocked by safety interlocks
# info["baseline_action"]: deterministic reference action

while True:
    action = my_llm_or_plc_agent(obs, info["valid_actions"])
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        break
```

### MuJoCo Robot Control Modes
For `mujoco/<robot>-<task>-v0` environments, `kense_sim.make(..., control_mode=...)` supports:
- `"skills"` (default): High-level industrial process phases (`approach`, `descend`, `grasp`, `touch`, `lift`, `carry`, `lower`, `release`, `withdraw`, `finish`) with MuJoCo shadow-clone collision preview.
- `"incremental"`: Closed-loop Cartesian step deltas (`+x`, `-x`, `+y`, `-y`, `+z`, `-z`, `open`, `close`).
- `"continuous_tcp"`: Direct 3D Cartesian TCP setpoint `{"target_tcp": [x, y, z], "gripper": "close", "seconds": 0.8}` with IK & collision verification.

### OpenAI Tool-Calling Schema Export
Any `IndustrialEnv` exports ready-to-use OpenAI Function Calling schemas reflecting the live safety-admitted actions at the current state:

```python
tools = env.to_openai_tools()
prompt = env.build_decision_prompt()
```

---

## 2. HTTP REST Control Protocol (`/api/v1/*`)

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/environments` | List all MuJoCo & Equipment environments (`?domain=mujoco\|equipment`) |
| `POST` | `/api/v1/env/reset` | Reset environment `{"env_id": "equipment/forklift-v0", "seed": 0}` |
| `POST` | `/api/v1/env/step` | Step via direct action `{"action": "drive_to_dock"}` or server policy `{"mode": "policy", "provider": "chat"}` |
| `POST` | `/api/v1/env/estop` | Engage or release hardware E-Stop `{"engaged": true}` |
| `GET` | `/api/v1/env/state` | Inspect current observation, admitted actions, interlock rejections & OpenAI tool schema |

Remote Python client:

```python
from kense_sim import KenseSimClient

with KenseSimClient("http://127.0.0.1:8090") as client:
    obs, info = client.reset("equipment/factory_floor-v0", seed=0)
    obs, reward, terminated, truncated, info = client.step(info["baseline_action"])
```

---

## 3. Full-Duplex WebSocket Protocol (`/ws/v1/control`)

Connect to `ws://127.0.0.1:8090/ws/v1/control` and exchange JSON frames:

- **Reset**: `{"op": "reset", "env_id": "equipment/sorting_line-v0", "seed": 0}`
- **Direct Actuation**: `{"op": "step", "action": "feed_and_scan"}`
- **Server Model Step**: `{"op": "policy_step", "provider": "baseline"}`
- **Emergency Stop**: `{"op": "estop", "engaged": true}`
- **Read State**: `{"op": "state"}`
