# Third-Party Notices

This repository (`Kinetics`) is released under the **MIT License** (for project source code). All 3D models in this project are strictly curated **1:1 real-world engineering CAD / manufacturer CAD meshes** — all procedural or simplified primitive substitutes have been removed. Please review the third-party model licenses below before commercial redistribution.

---

## 1. MuJoCo Industrial Robotic Arm CAD Assets (`src/embodied_jev/assets/` & `frontend/public/twin-assets/robots/`)

### Franka Emika Panda
- **Source**: [google-deepmind/mujoco_menagerie (`franka_emika_panda`)](https://github.com/google-deepmind/mujoco_menagerie/tree/822c2d8f877dd166c5b7d3c9f7e3c3b6589473b7/franka_emika_panda)
- **License**: Apache-2.0 (`LICENSE` preserved in `src/embodied_jev/assets/panda/`).

### Enactic OpenArm
- **Source**: [enactic/openarm_mujoco (`v1/openarm.xml`)](https://github.com/enactic/openarm_mujoco)
- **License**: Apache-2.0 (`LICENSE-APACHE-2.0` preserved in `src/embodied_jev/assets/openarm/`).

### Universal Robots UR5e
- **Source**: [google-deepmind/mujoco_menagerie (`universal_robots_ur5e`)](https://github.com/google-deepmind/mujoco_menagerie)
- **License**: BSD-3-Clause / ROS-Industrial (`LICENSE` preserved in `src/embodied_jev/assets/ur5e/`).

### UFACTORY xArm7
- **Source**: [google-deepmind/mujoco_menagerie (`ufactory_xarm7`)](https://github.com/google-deepmind/mujoco_menagerie)
- **License**: BSD-3-Clause (`LICENSE` preserved in `src/embodied_jev/assets/xarm7/`).

### Kinova Gen3
- **Source**: [google-deepmind/mujoco_menagerie (`kinova_gen3`)](https://github.com/google-deepmind/mujoco_menagerie)
- **License**: BSD-3-Clause (`LICENSE` preserved in `src/embodied_jev/assets/gen3/`).

---

## 2. Genuine Engineering-CAD Digital-Twin Equipment (`frontend/public/twin-assets/`)

### KUKA LBR iiwa 14 Workstation (`robot_cell.glb`)
- **Source**: [google-deepmind/mujoco_menagerie (`kuka_iiwa_14`)](https://github.com/google-deepmind/mujoco_menagerie) / Drake (`Robot Locomotion Group @ CSAIL`)
- **License**: BSD-3-Clause.

### Counterbalance Forklift (`forklift.glb`), KUKA KR210_L150 (`kr210.glb`), and Roller Sorting Line (`sorting_line.glb`)
- **Source**: Converted from NVIDIA Isaac Sim / Omniverse sample CAD assets (`Forklift/forklift.usd`, `Robots/Kuka/KR210_L150/kr210_l150.usd`, `Conveyors/ConveyorBelt_A08.usd`).
- **License**: Subject to the **NVIDIA Omniverse License Agreement** (permitted for simulation/research/development; review NVIDIA's asset redistribution terms prior to standalone commercial shipping).

### Voron 2.4r2 CoreXY Additive Manufacturing Machine (`voron_printer.glb`)
- **Source**: Converted directly from official [VoronDesign/Voron-2](https://github.com/VoronDesign/Voron-2) 7,433-part engineering STEP CAD assembly via `tools/step_to_glb.py`.
- **License**: GPL-3.0 (applies to the standalone Voron 3D CAD asset file `voron_printer.glb`; does not supersede the MIT license of the simulator codebase).

---

## 3. Runtime & Upstream Foundation

- **Upstream Foundation**: Built upon [FBddcz/embodied-jev](https://github.com/FBddcz/embodied-jev) (MIT License).
- **Runtime Dependencies**: MuJoCo (Apache-2.0), Three.js (MIT), Lucide (ISC), Vite (MIT), FastAPI (MIT), HTTPX (BSD-3-Clause).
