"""Worker and owner operations for playing and testing rebuilt games.

`describe_game`, `play_game` and `test_game` read a game spec (default `game.json`)
from the project workspace, run the original image and/or the candidate built from
the spec's manifest in deterministic engines, and return compact results with
trajectory tokens and optional frame images. They never write project files: each
result is a function of the workspace inputs and the supplied trajectory, so an
interrupted call is recomputed rather than reconciled. Caches only avoid repeated
builds and replays; they never change results.
"""

import hashlib
import json
import os
import shutil
import threading
import time
from collections import OrderedDict

from hivemind_assembly.core import game_spec as gs
from hivemind_assembly.core import game_testing as gt
from hivemind_assembly.core.common import Blocked, ContractError, digest, scoped

from .game_machine import open_engine

SIDES = ("original", "candidate", "both")
MODES = ("compare", "run", "explore", "shrink", "package", "regressions")


def _bounded_int(args, key, default, low, high):
    value = args.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ContractError(f"{key} must be an integer from {low} to {high}")
    return value


def strip_images(result):
    """Results for transports without binary attachments."""
    return {k: v for k, v in result.items() if k != "_images"}


class GamePlay:
    def __init__(self, builds=4, sessions=8):
        self.lock = threading.Lock()
        self.builds, self.build_limit = OrderedDict(), builds
        self.sessions, self.session_limit = OrderedDict(), sessions

    # Inputs.
    def load(self, root, path="game.json"):
        gs.relative(path, "game_path")
        file = scoped(root, path)
        if not file.is_file():
            raise ContractError("Game spec not found: " + path)
        if file.stat().st_size > 262144:
            raise Blocked("Game spec exceeds 256 KiB")
        try:
            value = json.loads(file.read_text("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ContractError("Game spec is not valid UTF-8 JSON: " + str(error)) from error
        return gs.validate(value)

    def _candidate(self, root, spec, context):
        from .program import sources

        path = scoped(root, spec["candidate_manifest"])
        if path.stat().st_size > 128000:
            raise Blocked("Build manifest exceeds bounds")
        manifest = json.loads(path.read_text("utf-8"))
        units = sources(root, manifest)
        compiler = context.config.get("foundations", {}).get("c_compiler", "") or ""
        located = (
            shutil.which(compiler)
            if compiler
            else shutil.which("clang") or (None if spec["platform"] == "windows" else shutil.which("gcc"))
        )
        stamp = None
        if located:
            # A changed compiler invalidates cached builds without rehashing it.
            info = os.stat(located)
            stamp = [located, info.st_size, info.st_mtime_ns]
        key = digest({"platform": spec["platform"], "manifest": manifest, "units": units, "compiler": compiler, "stamp": stamp})
        with self.lock:
            if key in self.builds:
                self.builds.move_to_end(key)
                return self.builds[key]
        if spec["platform"] == "windows":
            from .windows_program import build

            built = build(root, manifest, context.jobs, compiler, context.cancel)
            image_key = "pe_hex"
        else:
            from .program import build

            built = build(root, manifest, context.jobs, compiler, context.cancel)
            image_key = "elf_hex"
        if not built["passed"]:
            return None, {"passed": False, "stage": built.get("stage"), "build": built.get("build")}
        image = bytes.fromhex(built.pop(image_key))
        summary = {"passed": True, "sha256": built["sha256"], "sources": built.get("sources", {})}
        if sources(root, manifest) != units:
            # Sources changed during the build; return the result without caching it.
            return image, summary | {"cached": False}
        with self.lock:
            self.builds[key] = (image, summary)
            while len(self.builds) > self.build_limit:
                self.builds.popitem(last=False)
        return image, summary

    def images(self, context, spec, side):
        root = context.workspace
        result = {"original": None, "candidate": None, "build": None}
        if side in ("original", "both"):
            if "original_path" not in spec:
                raise Blocked("This game spec names no original_path")
            path = scoped(root, spec["original_path"])
            if not path.is_file():
                raise ContractError("Original image not found: " + spec["original_path"])
            if path.stat().st_size > 2_000_000:
                raise Blocked("Original image exceeds bounds")
            result["original"] = path.read_bytes()
        if side in ("candidate", "both"):
            if "candidate_manifest" in spec:
                result["candidate"], result["build"] = self._candidate(root, spec, context)
            elif "candidate_path" in spec:
                path = scoped(root, spec["candidate_path"])
                if not path.is_file() or path.stat().st_size > 2_000_000:
                    raise ContractError("Candidate image is missing or exceeds bounds")
                result["candidate"] = path.read_bytes()
            else:
                raise Blocked("This game spec names no candidate_manifest or candidate_path")
        return result

    # Runners.
    def _session(self, spec, image, side, cancel):
        return gt.Session(spec, open_engine(image, spec, cancel=cancel), side)

    def factory(self, spec, images, side, cancel):
        if side == "both":
            return lambda: gt.Pair(
                spec,
                self._session(spec, images["original"], "original", cancel),
                self._session(spec, images["candidate"], "candidate", cancel),
            )
        return lambda: self._session(spec, images[side], side, cancel)

    def _key(self, spec, images, side, inputs):
        return digest(
            {
                "spec": gs.spec_hash(spec),
                "side": side,
                "images": [
                    hashlib.sha256(images[s]).hexdigest() if images.get(s) else None
                    for s in ("original", "candidate")
                ],
                "inputs": inputs.hex(),
            }
        )

    def _take(self, key):
        with self.lock:
            return self.sessions.pop(key, None)

    def _keep(self, key, runner):
        with self.lock:
            self.sessions[key] = runner
            while len(self.sessions) > self.session_limit:
                self.sessions.popitem(last=False)

    @staticmethod
    def _start(spec, args):
        if "trajectory" in args and "start" in args:
            raise ContractError("Use trajectory or start, not both")
        return gt.start_inputs(spec, args.get("trajectory") or args.get("start") or "")

    # Operations.
    def execute(self, context, request):
        tool, args = request["tool"], request["args"]
        if not isinstance(args, dict):
            raise ContractError("Game operations take an object of arguments")
        if tool == "describe_game":
            return self.describe(context, args)
        if tool == "play_game":
            return self.play(context, args)
        return self.test(context, args)

    def describe(self, context, args):
        if set(args) - {"game_path"}:
            raise ContractError("describe_game takes game_path")
        spec = self.load(context.workspace, args.get("game_path", "game.json"))
        result = {"game": gs.describe(spec), "sides": {}}
        for side in ("original", "candidate"):
            try:
                images = self.images(context, spec, side)
                if images[side] is None:
                    result["sides"][side] = {"available": False, "build": images["build"]}
                    continue
                session = self._session(spec, images[side], side, context.cancel)
            except (Blocked, ContractError) as error:
                # One unusable side (for example a dynamic ELF) still leaves the other.
                result["sides"][side] = {"available": False, "reason": str(error)}
                continue
            result["sides"][side] = {
                "available": True,
                "capabilities": session.engine.capabilities,
                "build": images["build"],
                "functions": sorted(session.engine.coverage()),
                "unresolved_memory_fields": session.unresolved,
                "startup": session.observation(recent=1, view=False),
            }
        regressions = scoped(context.workspace, spec["regressions_path"])
        result["regressions"] = (
            len(gt.validate_regressions(spec, json.loads(regressions.read_text("utf-8"))))
            if regressions.is_file() and regressions.stat().st_size <= 4_000_000
            else 0
        )
        result["claim"] = "Deterministic emulated play under the declared contract; not GPU, window-system or hardware-timing evidence."
        return result

    def play(self, context, args):
        allowed = {"game_path", "side", "trajectory", "start", "actions", "end", "expect", "images", "view"}
        if set(args) - allowed:
            raise ContractError("play_game takes " + ", ".join(sorted(allowed)))
        spec = self.load(context.workspace, args.get("game_path", "game.json"))
        side = args.get("side", "candidate")
        if side not in SIDES:
            raise ContractError("side is original, candidate or both")
        count = _bounded_int(args, "images", 1, 0, 4)
        if type(args.get("view", True)) is not bool or type(args.get("end", False)) is not bool:
            raise ContractError("view and end are booleans")
        expect = gs.conditions(args.get("expect", []), set(gs.field_names(spec)), "Expectation")
        start, preconditions = self._start(spec, args)
        added = gs.expand(spec, args.get("actions", []))
        images = self.images(context, spec, side)
        if side != "original" and images["candidate"] is None:
            return {"passed": False, "outcome": "unsupported", "build": images["build"], "reason": "Candidate build failed"}
        key = self._key(spec, images, side, start)
        runner = self._take(key)
        if runner is None:
            runner = self.factory(spec, images, side, context.cancel)()
            runner.feed(start)
        sessions = (runner.original, runner.candidate) if side == "both" else (runner,)
        reached = gt.check_expectations(spec, (sessions[0].latest or {}).get("values", {}), preconditions)
        if any(item["met"] is not True for item in reached):
            return {
                "passed": False,
                "outcome": "unreached",
                "start": args.get("start"),
                "preconditions": reached,
                "trajectory": gs.encode_token(runner.inputs),
            }
        before = len(runner.inputs)
        runner.feed(added)
        if args.get("end"):
            runner.end()
        result = {
            "game": spec["name"],
            "side": side,
            "trajectory": gs.encode_token(runner.inputs),
            "ticks_added": (len(runner.inputs) - before) // spec["input"]["record_bytes"],
            "actions_available": sorted(spec["actions"]),
            "controls_available": sorted(spec["input"]["controls"]),
        }
        if side == "both":
            report = runner.report()
            result.update(
                comparison={k: report[k] for k in ("passed", "outcome", "compared_ticks", "divergence", "divergent_ticks", "findings", "original_behavior")},
                original=runner.original.observation(view=args.get("view", True)),
                candidate=runner.candidate.observation(view=args.get("view", True)),
                outcome=report["outcome"],
            )
            values = (runner.candidate.latest or {}).get("values", {})
        else:
            observation = runner.observation(view=args.get("view", True))
            found = gt.session_findings(runner)
            result.update(observation=observation, outcome=gt.outcome(found), findings=found)
            values = observation["state"]
        if expect:
            result["expectations"] = gt.check_expectations(spec, values, expect)
        result["_images"] = [image for session in sessions for image in session.images(count)]
        if not runner.stopped and not args.get("end"):
            self._keep(self._key(spec, images, side, bytes(runner.inputs)), runner)
        return result

    def test(self, context, args):
        allowed = {"game_path", "mode", "side", "trajectory", "start", "signature", "steps", "seed", "seconds", "end", "images"}
        if set(args) - allowed:
            raise ContractError("test_game takes " + ", ".join(sorted(allowed)))
        spec = self.load(context.workspace, args.get("game_path", "game.json"))
        mode = args.get("mode", "compare")
        if mode not in MODES:
            raise ContractError("mode is " + ", ".join(MODES))
        seconds = _bounded_int(args, "seconds", 60, 1, 600)
        deadline = time.monotonic() + seconds
        default_side = "both" if "original_path" in spec else "candidate"
        side = args.get("side", "candidate" if mode == "run" else default_side)
        if side not in SIDES:
            raise ContractError("side is original, candidate or both")
        if mode == "compare":
            side = "both"
        elif mode == "regressions":
            side = default_side
        images = self.images(context, spec, side)
        if side in ("candidate", "both") and images["candidate"] is None:
            return {"passed": False, "outcome": "unsupported", "build": images["build"], "reason": "Candidate build failed"}
        make = self.factory(spec, images, side, context.cancel)
        start, preconditions = self._start(spec, args)
        result = {"game": spec["name"], "mode": mode, "side": side, "build": images["build"]}
        if mode == "explore":
            reference = None
            if side == "candidate" and "original_path" in spec:
                # Single-build findings that the original reproduces are original behavior.
                images["original"] = self.images(context, spec, "original")["original"]
                reference = self.factory(spec, images, "original", context.cancel)
            report = gt.explore(
                spec,
                make,
                steps=_bounded_int(args, "steps", 200, 1, 5000),
                seed=_bounded_int(args, "seed", 0, 0, 2**31 - 1),
                start=start,
                deadline=deadline,
                cancel=context.cancel,
                reference=reference,
            )
            return result | report | {"passed": not report["findings"]}
        if mode in ("shrink", "package"):
            signature = args.get("signature")
            if not isinstance(signature, list) or not 1 <= len(signature) <= 4:
                raise ContractError("shrink and package need a finding signature from an earlier report")
            if not start:
                raise ContractError("shrink and package need the finding's trajectory")
            if mode == "shrink":
                return result | gt.shrink(spec, make, start, signature, deadline=deadline, cancel=context.cancel)
            report = gt.package(spec, make, start, signature, images=_bounded_int(args, "images", 2, 0, 4))
            return result | report
        if mode == "regressions":
            path = scoped(context.workspace, spec["regressions_path"])
            if not path.is_file():
                return result | {"passed": True, "total": 0, "failed": [], "results": [], "note": "No saved regressions yet"}
            if path.stat().st_size > 4_000_000:
                raise Blocked("Regressions file exceeds 4 MB")
            items = gt.validate_regressions(spec, json.loads(path.read_text("utf-8")))
            pair = self.factory(spec, images, "both", context.cancel) if images["original"] is not None else None
            if pair is None and any(item["expect"] == "match_original" for item in items):
                raise Blocked("match_original regressions need the original image")
            single = self.factory(spec, images, "candidate", context.cancel)
            return result | gt.run_regressions(spec, pair, single, items, deadline=deadline, cancel=context.cancel)
        runner = make()
        runner.feed(start)
        sessions = (runner.original, runner.candidate) if side == "both" else (runner,)
        reached = gt.check_expectations(spec, (sessions[0].latest or {}).get("values", {}), preconditions)
        if args.get("end", False) is True:
            runner.end()
        if side == "both":
            report = runner.report()
        else:
            found = gt.session_findings(runner)
            report = {"passed": not found, "outcome": gt.outcome(found), "findings": found, "summary": runner.summary(), "trajectory": gs.encode_token(runner.inputs)}
        if any(item["met"] is not True for item in reached):
            report = report | {"passed": False, "outcome": "unreached", "preconditions": reached}
        count = _bounded_int(args, "images", 1, 0, 4)
        return result | report | {"_images": [image for s in sessions for image in s.images(count)]}
