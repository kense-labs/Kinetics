#!/usr/bin/env python3
"""Full-fleet verification: 8 MuJoCo robotic arm processes + 11 industrial equipment twins."""
from __future__ import annotations

import sys

from embodied_jev.equipment_sim import EQUIPMENT_SPECS, run_equipment_headless
from embodied_jev.runtime import run_headless

MUJOCO_SIGNATURE = [
    ("panda", "insert"),
    ("openarm", "sort"),
    ("ur5e", "tending"),
    ("xarm7", "depalletize"),
    ("gen3", "kitting"),
    ("ur5e", "weld"),
    ("gen3", "glue"),
    ("xarm7", "palletize"),
]


def main() -> int:
    ok = 0
    total = len(MUJOCO_SIGNATURE) + len(EQUIPMENT_SPECS)

    print("=== Part 1: MuJoCo 3D Physics Industrial Arms ===")
    for robot, task in MUJOCO_SIGNATURE:
        s = run_headless(task, 0, robot=robot)
        w = s.world
        good = s.status == "completed" and w.success() and w.unsafe_contacts == 0 and all(w.placed)
        ok += int(good)
        print(f"  [{'OK  ' if good else 'FAIL'}] mujoco/{robot}-{task:<12} cycles={s.cycles}")

    print("\n=== Part 2: Industrial Equipment PLC & Safety-Interlock Twins ===")
    for eid in EQUIPMENT_SPECS:
        es = run_equipment_headless(eid, seed=0)
        obs = es.world.observe()
        good = es.status == "completed" and obs["success"] and obs["interlock_trips"] == 0
        ok += int(good)
        print(f"  [{'OK  ' if good else 'FAIL'}] equipment/{eid:<18} cycles={es.cycles:2d} sim_s={obs['sim_seconds']:5.1f}s")

    print(f"\n{'PASS' if ok == total else 'FAIL'} {ok}/{total}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
