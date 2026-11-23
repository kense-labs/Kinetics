"""Command-line interface for Kense Industrial Sim (`kense-sim`)."""
from __future__ import annotations

import argparse
import json
import sys

from .env import list_environments, run_episode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kense-sim",
        description="Kense Industrial Sim: decision-model interfacing & control for industrial simulation",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Launch Web workbench + REST/WebSocket control server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8090)
    p_serve.add_argument("--memory-only", action="store_true", help="Do not touch OS keychain")

    p_list = sub.add_parser("list", help="List all registered MuJoCo robot & industrial equipment environments")
    p_list.add_argument("--domain", choices=["mujoco", "equipment"], default=None)
    p_list.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="Run a closed-loop decision episode on any environment")
    p_run.add_argument("env_id", help="Environment ID (e.g. equipment/forklift-v0 or mujoco/ur5e-weld-v0)")
    p_run.add_argument("--seed", type=int, default=0)
    p_run.add_argument("--provider", default="baseline", choices=["baseline", "jev", "chat", "claude", "minicpm", "local"])
    p_run.add_argument("--output", default=None, help="Optional JSON file path for episode trace")

    p_bench = sub.add_parser("benchmark", help="Run batch verification across industrial environments")
    p_bench.add_argument("--domain", choices=["all", "equipment", "mujoco"], default="equipment")
    p_bench.add_argument("--seeds", type=int, nargs="+", default=[0])
    p_bench.add_argument("--provider", default="baseline")
    p_bench.add_argument("--output", default=None)

    args = parser.parse_args(argv)

    if args.command == "serve" or args.command is None:
        import os
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8090)
        memory_only = getattr(args, "memory_only", False)
        import uvicorn
        from embodied_jev.server import create_app

        store = None
        if not memory_only and os.getenv("EMBODIED_JEV_PERSISTENCE") != "memory":
            from embodied_jev.connection_store import SystemConnectionStore
            store = SystemConnectionStore()

        print(f"Kense Industrial Sim Workbench & Control API -> http://{host}:{port}")
        print(f"  REST SDK API:      http://{host}:{port}/api/v1/environments")
        print(f"  WebSocket Control: ws://{host}:{port}/ws/v1/control")
        uvicorn.run(create_app(store=store), host=host, port=port, access_log=False)
        return 0

    if args.command == "list":
        envs = list_environments(domain=args.domain)
        if args.json:
            print(json.dumps(envs, ensure_ascii=False, indent=2))
        else:
            print(f"{'ENV ID':<32} {'DOMAIN':<11} {'MAX':>4}  {'NAME'}")
            print("-" * 80)
            for e in envs:
                print(f"{e['env_id']:<32} {e['domain']:<11} {e['max_steps']:>4}  {e['name']}")
        return 0

    if args.command == "run":
        res = run_episode(args.env_id, policy=args.provider, seed=args.seed)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        status = "SUCCESS" if res["success"] else "FAILED"
        print(f"[{status}] {res['env_id']} steps={res['steps']} reward={res['total_reward']} sim_s={res['sim_seconds']}")
        return 0 if res["success"] else 1

    if args.command == "benchmark":
        domains = ["equipment", "mujoco"] if args.domain == "all" else [args.domain]
        targets = []
        if "equipment" in domains:
            targets.extend([e["env_id"] for e in list_environments("equipment")])
        if "mujoco" in domains:
            targets.extend([
                "mujoco/panda-insert-v0",
                "mujoco/openarm-sort-v0",
                "mujoco/ur5e-tending-v0",
                "mujoco/ur5e-weld-v0",
                "mujoco/xarm7-depalletize-v0",
                "mujoco/xarm7-palletize-v0",
                "mujoco/gen3-kitting-v0",
                "mujoco/gen3-glue-v0",
            ])
        results = []
        passed = 0
        total = 0
        for eid in targets:
            for sd in args.seeds:
                total += 1
                res = run_episode(eid, policy=args.provider, seed=sd)
                ok = bool(res["success"])
                passed += int(ok)
                results.append({k: res[k] for k in ("env_id", "seed", "success", "steps", "total_reward", "sim_seconds")})
                print(f"  [{'PASS' if ok else 'FAIL'}] {eid:<32} seed={sd} steps={res['steps']:>2} sim_s={res['sim_seconds']}")
        summary = {"passed": passed, "total": total, "results": results}
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\nBenchmark Summary: {passed}/{total} passed")
        return 0 if passed == total else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
