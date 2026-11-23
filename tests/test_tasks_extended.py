"""Extended tasks: 精密插装 (insert) and 双物分拣 (sort).

Both run on the stock arm pipeline for Panda and OpenArm alike; sort exercises
the multi-object generalisation (one cube per tray, one at a time)."""

import numpy as np
import pytest

from embodied_jev.physics import RobotWorld, build_scene
from embodied_jev.runtime import Session, run_headless


@pytest.mark.parametrize("robot", ["panda", "openarm"])
def test_insert_episode(robot):
    session = run_headless("insert", seed=7, robot=robot)
    assert session.status == "completed", session.message
    assert session.world.success()
    assert session.world.unsafe_contacts == 0
    # Peg is upright in the pocket: on the floor (support), centred, released.
    assert session.world.placed == [True]
    peg = session.world.cube
    assert np.linalg.norm(peg[:2] - np.array([.43, .18])) < .01
    assert abs(peg[2] - .045) < .004


@pytest.mark.parametrize("robot", ["panda", "openarm"])
def test_sort_episode(robot):
    session = run_headless("sort", seed=7, robot=robot)
    assert session.status == "completed", session.message
    assert session.world.success()
    assert session.world.unsafe_contacts == 0
    assert session.world.placed == [True, True]
    red, green = session.world._all_cubes()
    assert np.linalg.norm(red[:2] - np.array([.43, .20])) < .03   # red -> blue tray
    assert np.linalg.norm(green[:2] - np.array([.28, .08])) < .03  # green -> yellow tray


def test_sort_placed_latch_survives_gripper_close():
    # Regression: placing object 1 must keep its placed flag while the gripper
    # closes on object 2 (previously the flag flickered and the active object
    # flip-flopped, looping grasp/recover forever).
    world = RobotWorld("sort", 0, robot="openarm")
    cube1 = np.array([.43, .20, .021])
    adr = world.model.jnt_qposadr[world.model.joint("cube_joint").id]
    world.data.qpos[adr:adr + 3] = cube1
    for _ in range(400):  # settle onto the tray floor
        world.tick()
    assert world.placed[0]
    world.closed = True  # closing the gripper elsewhere must not unplace it
    world.tick()
    assert world.placed[0]
    assert world.object_names[world.active_index] == "cube2"


def test_sort_rejects_custom_layout():
    with pytest.raises(ValueError, match="布局固定"):
        RobotWorld("sort", 0, scene_config={"source_xy": [.4, -.2]}, robot="openarm")


def test_insert_support_contact_via_peg_disc():
    # The peg rests on its disc (cube_base), not the grasped shaft: support
    # detection must cover every geom of the object body.
    world = RobotWorld("insert", 0, robot="openarm")
    adr = world.model.jnt_qposadr[world.model.joint("cube_joint").id]
    world.data.qpos[adr:adr + 3] = np.array([.43, .18, .045])
    for _ in range(400):
        world.tick()
    assert world.placed[0]


def test_extended_tasks_privileged_only():
    with pytest.raises(ValueError, match="privileged"):
        Session(task="insert", robot="openarm", observation_mode="rgbd")
    with pytest.raises(ValueError, match="privileged"):
        Session(task="sort", robot="panda", observation_mode="rgbd")


def test_insert_task_xml_deterministic():
    first, _, _ = build_scene("insert", 3, robot="openarm")
    second, _, _ = build_scene("insert", 3, robot="openarm")
    assert first == second
