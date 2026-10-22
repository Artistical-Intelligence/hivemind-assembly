import argparse, json
from hivemind_assembly.application.app import serve, data_home


def main():
    p = argparse.ArgumentParser(
        description="Hivemind Assembly — reverse engineering and collaborative learning"
    )
    p.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=[
            "serve",
            "mcp",
            "verify",
            "check-function",
            "test-programs",
            "learn",
            "setup",
            "doctor",
            "verify-foundations",
            "restore",
            "game-test",
        ],
    )
    p.add_argument("--data-dir", default=str(data_home()))
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--candidate", help="Freestanding C source for check-function")
    p.add_argument("--original", help="Original function bytes as hexadecimal text")
    p.add_argument("--function", default="recovered")
    p.add_argument("--argument-bits", default="32,32")
    p.add_argument("--output-bits", type=int, choices=[32, 64], default=32)
    p.add_argument("--compiler", default="")
    p.add_argument(
        "--workflow",
        choices=["proofs", "calls"],
        default="proofs",
        help="Executable workflow for learn",
    )
    p.add_argument(
        "--backup",
        help="Workspace ZIP for offline restore into an empty data directory",
    )
    p.add_argument("--suite", help="Owner-defined native test suite JSON")
    p.add_argument(
        "--workspace", help="Directory containing the suite's explicit program inputs"
    )
    p.add_argument(
        "--allow-native",
        action="store_true",
        help="Authorize the recipes to execute with this host's access (not a sandbox)",
    )
    p.add_argument("--game", default="game.json", help="Game contract for game-test")
    p.add_argument(
        "--mode",
        choices=["describe", "compare", "run", "explore", "shrink", "package", "regressions"],
        default="describe",
        help="game-test operation",
    )
    p.add_argument("--side", choices=["original", "candidate", "both"], help="game-test side")
    p.add_argument("--trajectory", help="game-test trajectory token or named start")
    p.add_argument("--signature", help="Finding signature for shrink/package, comma separated")
    p.add_argument("--steps", type=int, default=200, help="game-test exploration steps")
    p.add_argument("--seed", type=int, default=0, help="game-test exploration seed")
    p.add_argument("--seconds", type=int, default=120, help="game-test time budget")
    p.add_argument("--end", action="store_true", help="game-test: end input (findings detected after end of input)")
    p.add_argument("--godot", default="", help="game-test: Godot 4 executable for native Godot games")
    args = p.parse_args()
    if args.command == "game-test":
        import threading
        from pathlib import Path
        from hivemind_assembly.core.domain import ToolContext
        from hivemind_assembly.core.jobs import Jobs
        from hivemind_assembly.domains.reverse_engineering.game_play import GamePlay, strip_images

        if not args.workspace:
            p.error("game-test requires --workspace (the folder holding the game contract)")
        # Native games (Godot projects, SDL2 programs) run only with --allow-native.
        context = ToolContext(
            Path(args.workspace).resolve(),
            {"foundations": {"c_compiler": args.compiler, "godot": args.godot}},
            Jobs(),
            threading.Event(),
            native=args.allow_native,
        )
        games = GamePlay()
        if args.mode == "describe":
            result = games.describe(context, {"game_path": args.game})
            print(json.dumps(result, indent=2))
            raise SystemExit(0)
        request = {"game_path": args.game, "mode": args.mode, "seconds": args.seconds}
        if args.mode == "explore":
            request.update(steps=args.steps, seed=args.seed)
        if args.side:
            request["side"] = args.side
        if args.end:
            request["end"] = True
        if args.trajectory:
            key = "trajectory" if args.trajectory.startswith("g1.") else "start"
            request[key] = args.trajectory
        if args.signature:
            request["signature"] = [
                int(x) if x.lstrip("-").isdigit() else x for x in args.signature.split(",")
            ]
        result = strip_images(games.test(context, request))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result.get("passed", result.get("reproduced")) else 1)
    if args.command == "mcp":
        from hivemind_assembly.integrations.mcp import serve_bridge
        serve_bridge(args.data_dir)
    elif args.command == "serve":
        serve(args.data_dir, args.port, not args.no_browser)
    elif args.command == "test-programs":
        from pathlib import Path
        from hivemind_assembly.core.tool_testing import execute

        if not args.suite or not args.workspace or not args.allow_native:
            p.error("test-programs requires --suite, --workspace and --allow-native")
        source = Path(args.suite)
        if source.stat().st_size > 16 * 1024 * 1024:
            p.error("Test suite exceeds 16 MiB")
        result = execute(
            args.workspace,
            json.loads(source.read_text("utf-8")),
            allow_native=True,
            compiler=args.compiler or None,
        )
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["passed"] else 1)
    elif args.command == "restore":
        from hivemind_assembly.core.backups import restore
        from hivemind_assembly.core.common import InstanceLock

        if not args.backup:
            p.error("restore requires --backup and an empty --data-dir")
        print(json.dumps(restore(args.backup, args.data_dir), indent=2))
    elif args.command == "verify-foundations":
        from pathlib import Path
        from hivemind_assembly.application.verification import verify_foundations

        root = Path(args.data_dir)
        config = json.loads((root / "settings.json").read_text())
        result = verify_foundations(
            root / "private" / "verification", config["foundations"]
        )
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["passed"] else 1)
    elif args.command == "verify":
        from hivemind_assembly.domains.reverse_engineering.semantics import (
            smoke_cases,
            differential,
        )
        from hivemind_assembly.domains.reverse_engineering.proof import prove

        r = [differential(c) for c in smoke_cases()]
        proof = prove("89f801f0", "8d0437")
        negative = prove("89f801f0", "89f829f0")
        print(
            json.dumps(
                {
                    "cases": [
                        {"name": x["case"]["name"], **x["comparison"]} for x in r
                    ],
                    "proof": proof,
                    "negative_proof": negative,
                },
                indent=2,
            )
        )
        raise SystemExit(
            0
            if all(x["comparison"]["passed"] for x in r)
            and proof["result"] == "UNSAT"
            and negative["result"] == "SAT"
            else 1
        )
    elif args.command == "check-function":
        from pathlib import Path
        from hivemind_assembly.core.jobs import Jobs
        from hivemind_assembly.domains.reverse_engineering.reconstruction import (
            compile_function,
            compare_functions,
            vectors,
        )

        if not args.candidate or not args.original:
            p.error("check-function requires --candidate and --original")
        try:
            path = Path(args.candidate)
            if path.stat().st_size > 128000:
                raise ValueError("Candidate source exceeds 128 KB")
            cases = vectors(
                [int(x.strip()) for x in args.argument_bits.split(",") if x.strip()], 0
            )
            built = compile_function(
                path.read_text("utf-8"), args.function, Jobs(), args.compiler
            )
            if built["passed"]:
                built["comparison"] = compare_functions(
                    bytes.fromhex(args.original),
                    bytes.fromhex(built["machine_hex"]),
                    cases,
                    args.output_bits,
                )
                built["passed"] = built["comparison"]["passed"]
            built["claim"] = (
                "Development samples only; use a pinned project acceptance contract for independent completion checks"
            )
        except (OSError, ValueError) as error:
            built = {"passed": False, "reason": str(error)}
        print(json.dumps(built, indent=2))
        raise SystemExit(0 if built["passed"] else 1)
    elif args.command == "learn":
        from hivemind_assembly.core.common import InstanceLock
        from hivemind_assembly.core.store import Store
        from hivemind_assembly.domains.reverse_engineering.workflows import (
            optimize_repeated_proofs,
            optimize_repeated_calls,
        )

        lock = InstanceLock(args.data_dir)
        store = Store(args.data_dir)
        try:
            optimize = (
                optimize_repeated_calls
                if args.workflow == "calls"
                else optimize_repeated_proofs
            )
            print(json.dumps(optimize(store), indent=2))
        finally:
            store.close()
            lock.close()
    elif args.command == "setup":
        from hivemind_assembly.application.setup import install_foundations
        from hivemind_assembly.application.app import Application

        app = Application(args.data_dir)
        try:
            print(
                json.dumps(
                    install_foundations(args.data_dir, app.config_path), indent=2
                )
            )
        finally:
            app.close()
    else:
        import importlib.util, shutil

        print(
            json.dumps(
                {
                    "python_dependencies": {
                        name: bool(importlib.util.find_spec(name))
                        for name in ["playwright", "pypcode", "unicorn", "z3"]
                    },
                    "tools": {
                        n: bool(shutil.which(n))
                        for n in ["git", "node", "java", "clang", "gcc"]
                    },
                    "native_routes": "Require live calibration; never inferred from installed tools",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
