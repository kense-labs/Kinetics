"""First-tier fleet tests: UR5e / xArm7 / Gen3 robot integration and their
signature tasks (tending / depalletize / kitting), plus the shared machinery
they exercise (collision-aware IK, suction attach, task scoping)."""

import numpy as np
import pytest

from embodied_jev.physics import ROBOTS, RobotWorld
from embodied_jev.runtime import run_headless


def test_fleet_registered():
    assert {"panda", "openarm", "ur5e", "xarm7", "gen3"} <= set(ROBOTS)


@pytest.mark.parametrize("robot", ["ur5e", "xarm7", "gen3"])
def test_fleet_world_builds(robot):
    world = RobotWorld(ROBOTS[robot].tasks[0], 0, robot=robot)
    assert world.unsafe_contacts == 0
    assert np.isfinite(world.data.qpos).all()


def test_ur5e_ik_veto_rejects_table_grazing_pose():
    # Drive the forearm through the table, then ask the veto directly.
    world = RobotWorld("transfer", 0, robot="ur5e")
    spec = ROBOTS["ur5e"]
    import mujoco
    data = mujoco.MjData(world.model)
    data.qpos[:] = world.data.qpos
    # 实测穿模姿态(前臂贯入桌面): 来自分拣任务一次失败的 IK 解
    data.qpos[world.arm_q] = np.array([-0.107, -3.523, 1.534, 0.418, -1.571, 1.464])
    mujoco.mj_forward(world.model, data)
    assert not spec.ik_pose_ok(world.model, data)
    # the stock home pose is clean
    data.qpos[world.arm_q] = spec.home
    mujoco.mj_forward(world.model, data)
    assert spec.ik_pose_ok(world.model, data)


def test_xarm7_suction_attach_and_release():
    world = RobotWorld("depalletize", 0, robot="xarm7")
    cube = world.cube.copy()
    for _ in world.motion(cube + [0, 0, .14], "open", 1.4, emit=False):
        pass
    for _ in world.motion(cube + [0, 0, world.spec.grasp_above], None, 1.2, emit=False):
        pass
    for _ in world.motion(world.position, "close", 0.9, emit=False):
        pass
    assert world.attached and world.observe()["held"]
    for _ in world.motion([world.position[0], world.position[1], .30], None, 1.5, emit=False):
        pass
    assert world.cube[2] > .20  # carton rides with the pad
    for _ in world.motion(world.position, "open", 0.8, emit=False):
        pass
    assert not world.attached


def test_gen3_continuous_joints_not_clamped():
    # Gen3's twist joints (1/3/5/7) are unlimited in MJCF; IK must not clamp
    # them to [0, 0] (regression: palletize poses were unreachable).
    world = RobotWorld("kitting", 0, robot="gen3")
    _, err = world.solve_ik(np.array([.43, .18, .034]))
    assert err <= .004


@pytest.mark.parametrize("robot,task", [("ur5e", "tending"), ("xarm7", "depalletize"), ("gen3", "kitting")])
def test_signature_episode(robot, task):
    session = run_headless(task, 7, robot=robot)
    assert session.status == "completed", session.message
    assert session.world.success()
    assert session.world.unsafe_contacts == 0
    assert all(session.world.placed)


def test_task_scoping():
    # 差异化任务矩阵: 每台招牌工序独占 + 至多一个基础工况对照。
    # xArm7 吸盘专职物流线(拆垛/码垛); UR5e 机床上下料+焊接; Gen3 摆盘+涂胶;
    # OpenArm 分拣; Panda 精密插装。
    # 保留的排他边界: Gen3 drops tending (round blanks roll out);
    # Panda/OpenArm drop kitting (queue drag-off loosens the grasp on the feeder).
    assert ROBOTS["xarm7"].tasks == ("depalletize", "palletize")
    assert "weld" in ROBOTS["ur5e"].tasks and "weld" not in ROBOTS["panda"].tasks
    assert "glue" in ROBOTS["gen3"].tasks and "glue" not in ROBOTS["ur5e"].tasks
    assert "sort" not in ROBOTS["ur5e"].tasks
    assert "tending" not in ROBOTS["gen3"].tasks
    assert "kitting" not in ROBOTS["panda"].tasks
    assert "kitting" not in ROBOTS["openarm"].tasks
    assert "kitting" in ROBOTS["gen3"].tasks
