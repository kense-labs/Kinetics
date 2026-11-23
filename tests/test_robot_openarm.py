"""OpenArm (Enactic) robot integration: asset integrity, workbench semantics and
full decision-loop episodes. Panda parity is guarded by the scene-hash test."""

import numpy as np
import pytest

from embodied_jev.physics import ROBOTS, RobotWorld, build_scene, resolve_robot
from embodied_jev.runtime import run_headless

PANDA_BASELINE_HASH = "4f2b9b0627efe1816a0f3ca927b7f44079588750edd89c4c46e669dca28cfc30"

# Every key pose the three tabletop tasks can request, including jitter corners
# and barrier clearance (see scenarios.SCENE_LIMITS and planning.candidates).
KEY_TARGETS = [
    [.38, -.08, .22],   # initial hover
    [.455, -.145, .161], [.405, -.195, .161],  # cube approach corners
    [.405, -.195, .022], [.455, -.145, .022],  # grasp corners
    [.43, .18, .22],    # travel above tray
    [.43, .18, .029], [.43, .18, .063],        # tray / stack placement
    [.43, 0, .33],      # barrier overflight
    [.30, -.28, .05],   # custom-scene near corner
    [.38, -.08, .029],
]


def test_panda_scene_hash_unchanged():
    # The OpenArm integration must not alter the stock Panda scene at all.
    assert RobotWorld("transfer", 0, robot="panda").scene_hash == PANDA_BASELINE_HASH


def test_resolve_robot_default_and_unknown(monkeypatch):
    monkeypatch.delenv("EMBODIED_JEV_ROBOT", raising=False)
    assert resolve_robot(None).key == "panda"
    monkeypatch.setenv("EMBODIED_JEV_ROBOT", "openarm")
    assert resolve_robot(None).key == "openarm"
    with pytest.raises(ValueError):
        resolve_robot("atlas")


def test_openarm_scene_hash_stable_and_distinct():
    first = RobotWorld("transfer", 0, robot="openarm").scene_hash
    second = RobotWorld("transfer", 0, robot="openarm").scene_hash
    assert first == second
    assert first != RobotWorld("transfer", 0, robot="panda").scene_hash


def test_openarm_initial_state_is_clean():
    world = RobotWorld("transfer", 0, robot="openarm")
    assert np.linalg.norm(world.position - world.spec.initial_target) < .004
    assert world.unsafe_contacts == 0
    assert world.observe()["robot"] == "Enactic OpenArm"
    # Stock parallel jaw is open at start: fingertip inner faces 86 mm apart.
    assert abs(world.data.qpos[world.model.jnt_qposadr[
        world.model.joint("openarm_finger_joint1").id]] - .044) < 1e-6


@pytest.mark.parametrize("target", KEY_TARGETS)
def test_openarm_ik_covers_task_workspace(target):
    world = RobotWorld("transfer", 0, robot="openarm")
    _, error = world.solve_ik(np.asarray(target, dtype=float))
    assert error <= .004


def test_openarm_gripper_semantics():
    world = RobotWorld("transfer", 0, robot="openarm")
    open_ctrl = world.data.ctrl[world.gripper_ctrl]
    assert open_ctrl == world.spec.gripper_open == pytest.approx(.044)
    for _ in world.motion(world.position, gripper="close", seconds=.2, emit=False):
        pass
    assert world.closed
    assert world.data.ctrl[world.gripper_ctrl] == pytest.approx(-.005)


def test_openarm_workspace_guard():
    world = RobotWorld("transfer", 0, robot="openarm")
    with pytest.raises(ValueError):
        list(world.motion([.65, 0, .2], emit=False))  # fine for Panda, outside for OpenArm


def test_openarm_far_corner_fails_gracefully():
    # (.58, .28) is inside the custom-scene envelope but beyond the OpenArm's
    # 633 mm reach with a locked grasp orientation: the workbench must reject it
    # with a clear error, not a bad motion. Panda reaches it — that size gap is
    # exactly why the OpenArm sits on a pedestal closer to the workspace.
    world = RobotWorld("transfer", 0, robot="openarm")
    _, error = world.solve_ik(np.array([.55, .30, .05]))
    assert error > .004
    with pytest.raises(ValueError, match="Unreachable target"):
        list(world.motion([.55, .30, .05], emit=False))


def test_openarm_pedestal_is_collision_free_during_episode():
    session = run_headless("transfer", 0, robot="openarm")
    assert session.status == "completed"
    model = session.world.model
    pedestal = {i for i in range(model.ngeom) if model.geom(i).name == "openarm_pedestal"}
    assert pedestal
    world = session.world
    assert world.unsafe_contacts == 0
    assert session.world.success()


@pytest.mark.parametrize("task", ["transfer", "stack", "barrier"])
def test_openarm_full_episode(task):
    session = run_headless(task, seed=7, robot="openarm")
    assert session.status == "completed", session.message
    assert session.world.success()
    assert session.world.unsafe_contacts == 0
    assert session.last_frame["observation"]["gripper"] == "open"
    assert session.last_frame["observation"]["stable_seconds"] >= .4
    assert session.world.model.neq == 1  # stock finger equality, no object attachment
