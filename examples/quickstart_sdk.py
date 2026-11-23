#!/usr/bin/env python3
"""Quickstart: Control both industrial equipment and MuJoCo robotic arms via `kense_sim`."""
from __future__ import annotations

import kense_sim


def main() -> None:
    print("1. Registered Environments:", len(kense_sim.list_environments()))

    # A) Closed-loop control of an autonomous counterbalance forklift with safety interlocks
    env = kense_sim.make("equipment/forklift-v0", seed=0)
    obs, info = env.reset(seed=0)
    print(f"\n[Forklift] Goal: {obs['goal']}")

    # Demonstrate real-time safety interlock protection:
    # Drive to dock -> engage pallet -> drive to rack -> elevate mast -> try unsafe high-mast driving
    for cmd in ("drive_to_dock", "engage_and_tilt", "transport_to_rack", "elevate_to_beam"):
        obs, reward, _, _, info = env.step(cmd)
    obs, reward, _, _, blocked_info = env.step("drive_to_dock")
    print(f"  Interlock test while mast elevated ({obs['telemetry']['fork_lift_m']}m):")
    print(f"    Rejected={blocked_info['interlock_rejected']} | Reason: {blocked_info['rejection_reason']}")

    # Run a full closed-loop episode to completion
    result = kense_sim.run_episode("equipment/forklift-v0", policy="baseline", seed=0)
    print(f"  Episode completed: success={result['success']} steps={result['steps']} sim_s={result['sim_seconds']}s")

    # B) Closed-loop control of a 6-DOF UR5e robotic arm executing spot-welding in MuJoCo physics
    weld_res = kense_sim.run_episode("mujoco/ur5e-weld-v0", policy="baseline", seed=0)
    print(
        f"\n[MuJoCo UR5e Spot-Welding] success={weld_res['success']} "
        f"steps={weld_res['steps']} unsafe_contacts={weld_res['final_observation']['unsafe_contacts']}"
    )


if __name__ == "__main__":
    main()
