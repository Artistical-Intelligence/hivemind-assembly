"""Project-level reconstruction: dependency-ordered regions, composition and rollback.

A project manifest names the candidate's C units and, for every recovered
function, the units that define it and the calling convention it was written
for. A check proceeds in three layers:

1. Function checks. Each recovered function is rebuilt on its own and compared
   with the same function in the original, in Ghidra callgraph dependency order
   when a plan is supplied. The verified prefix tells the worker which groups can
   be relied on and where repair starts.
2. Region composition (same architecture). Function-checked and program-only
   regions are linked into the original image, replacing their original code;
   everything else stays original machine code (fallback). The composed program is
   replayed against the original. When it diverges, regions are re-added
   cumulatively in plan order and every region whose addition breaks the program
   is rejected and left on its original code. A region that previously belonged to
   a verified composition and now fails is reported as a regression and rolled
   back to the original code.
3. Complete program (optional `build`). The cumulative source-only program is
   rebuilt from every unit and replayed. This is the only layer available when the
   candidate targets another architecture than the original (for example an
   AArch64 original reconstructed as x86-64 C).

Checks are finite declared cases. They do not prove all inputs; unexercised and
unchecked regions are reported as such rather than assumed correct.
"""

import hashlib
import json

from hivemind_assembly.core.common import Blocked, ContractError, digest, scoped
from . import call_images, pe_dependencies, program, project_hybrid

ABI_ARCHITECTURE = {"sysv": "x86_64", "aapcs64": "aarch64", "win64": "x86_64"}
MACHINE_ARCHITECTURE = {62: "x86_64", 183: "aarch64"}
MAX_FUNCTIONS = 128
MAX_GREEDY = 48


def _text(root, path, limit=128000):
    p = scoped(root, path)
    if p.stat().st_size > limit:
        raise Blocked("Manifest exceeds bounds: " + path)
    return p.read_text("utf-8")


def read_manifest(root, path):
    """Return (project, build or None, build_text or None, units)."""
    project = json.loads(_text(root, path))
    if not isinstance(project, dict) or set(project) - {
        "build",
        "sources",
        "declarations",
        "optimization",
        "functions",
        "addresses",
        "inventory_path",
    }:
        raise ContractError(
            "Project manifest allows build, sources, declarations, optimization, functions, addresses and inventory_path"
        )
    build = build_text = None
    if "build" in project:
        if not isinstance(project["build"], str):
            raise ContractError("Project build must be a build manifest path")
        build_text = _text(root, project["build"])
        build = json.loads(build_text)
        units = program.sources(root, build)
    elif "sources" in project:
        units = program.sources(
            root,
            {
                k: project[k]
                for k in ("sources", "declarations", "optimization")
                if k in project
            },
        )
    else:
        raise ContractError("Project manifest requires a build manifest or region sources")
    if "build" in project and (
        "sources" in project or "declarations" in project or "optimization" in project
    ):
        raise ContractError("Region units come from the build manifest when one is named")
    functions = project.get("functions", {})
    if not isinstance(functions, dict) or len(functions) > MAX_FUNCTIONS:
        raise ContractError("Project functions must map at most 128 names")
    for name, spec in functions.items():
        call_images.function_name(name)
        if not isinstance(spec, dict) or set(spec) - {"sources", "abi"}:
            raise ContractError("Function entries allow sources and abi")
        paths = spec.get("sources")
        if (
            not isinstance(paths, list)
            or not paths
            or len(paths) != len(set(paths))
            or not set(paths) <= set(units)
        ):
            raise ContractError(
                "Function sources must be distinct files from the project units: " + name
            )
        if spec.get("abi", "sysv") not in ABI_ARCHITECTURE:
            raise ContractError("Project functions use sysv, aapcs64 or win64")
    addresses = project.get("addresses", {})
    if not isinstance(addresses, dict) or len(addresses) > 4096:
        raise ContractError("Supplied addresses must map at most 4096 names")
    if "inventory_path" in project:
        # Saved Ghidra inventory pages (inspect_program results) for stripped
        # originals; explicit addresses take precedence over inventory entries.
        pages = json.loads(_text(root, project["inventory_path"], 8_000_000))
        project = dict(project, addresses={**addresses_from_inventory(pages), **addresses})
    return project, build, build_text, units


def addresses_from_inventory(pages):
    """Function addresses and contiguous sizes from Ghidra inventory pages.

    Ghidra's body size counts every address of a function, including detached
    chunks, so a region never extends past the next function's entry. External,
    thunk, duplicate and non-C names are skipped.
    """
    from .project_hybrid import NAME

    if isinstance(pages, dict):
        pages = [pages]
    if not isinstance(pages, list) or not 1 <= len(pages) <= 10000:
        raise ContractError("Supply Ghidra inventory pages")
    rows, seen, duplicate = [], set(), set()
    for page in pages:
        for item in page.get("functions", []) if isinstance(page, dict) else []:
            name, entry = item.get("name"), item.get("entry")
            if (
                not isinstance(name, str)
                or not NAME.fullmatch(name)
                or not isinstance(entry, str)
                or item.get("external")
                or item.get("thunk")
            ):
                continue
            try:
                address = int(entry.split(":")[-1], 16)
            except ValueError:
                continue
            if name in seen:
                duplicate.add(name)
            seen.add(name)
            rows.append((address, name, item.get("size", 0)))
    rows.sort()
    result = {}
    for index, (address, name, size) in enumerate(rows):
        if name in duplicate:
            continue
        bound = rows[index + 1][0] - address if index + 1 < len(rows) else size
        result[name] = {"address": address, "size": max(0, min(int(size or 0), bound))}
    return result


def normalized_hash(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode()).hexdigest()


def validate_checks(function_checks, project):
    if not isinstance(function_checks, dict) or len(function_checks) > MAX_FUNCTIONS:
        raise ContractError("Supply at most 128 function checks")
    for name, check in function_checks.items():
        if name not in project.get("functions", {}):
            raise ContractError("Function check has no project manifest entry: " + name)
        if not isinstance(check, dict) or set(check) - {
            "original_symbol",
            "original_address",
            "cases",
        }:
            raise ContractError("Function checks allow original_symbol/address and cases")
        if "original_symbol" in check and "original_address" in check:
            raise ContractError("Select an original symbol or address, not both")
        cases = check.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 256:
            raise ContractError("Each function check needs 1–256 cases")
        for case in cases:
            call_images.validate_case(case)
    return function_checks


def original_function(original, name, check, dependencies=None):
    address = check.get("original_address")
    if isinstance(address, str):
        address = int(address, 16)
    symbol = None if address is not None else check.get("original_symbol", name)
    return pe_dependencies.load(original, symbol, address, dependencies or {})


def order(names, plan):
    """Plan groups are dependency-first; unplanned names keep manifest order."""
    names = list(names)
    if not plan:
        return [(name, None) for name in names], None
    groups = plan.get("groups") if isinstance(plan, dict) else None
    if not isinstance(groups, list):
        raise ContractError("Plan must be a plan_reconstruction result")
    position = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("names"), dict):
            raise ContractError("Plan groups require function names")
        for label in group["names"].values():
            position.setdefault(label, group["id"])
    rank = {g["id"]: i for i, g in enumerate(groups)}
    ordered = sorted(
        names,
        key=lambda n: (rank.get(position.get(n), len(groups)), names.index(n)),
    )
    planned = {label for g in groups for label in g["names"].values()}
    return [(n, position.get(n)) for n in ordered], sorted(planned)


class Lane:
    """Format-specific builders: static Linux ELF or x64 Windows console PE."""

    def __init__(self, original):
        self.pe = original[:2] == b"MZ"
        if self.pe:
            from . import project_hybrid_pe, windows_program

            windows_program.image_info(original)
            self.architecture = "x86_64"
            self.hybrid = project_hybrid_pe
            self.build = windows_program.build
            self.compare = windows_program.compare
            self.image_key = "pe_hex"
        else:
            self.architecture = MACHINE_ARCHITECTURE[program.image_machine(original)]
            self.hybrid = project_hybrid
            self.build = program.build
            self.compare = program.compare
            self.image_key = "elf_hex"

    def static_reason(self, original):
        if self.pe:
            return None
        try:
            program.load_image(original, machine=program.image_machine(original))
        except Blocked as error:
            return "Region replacement needs a static ET_EXEC original: " + str(error)
        return None


def executable_ranges(original):
    """(address, bytes, arm) for every executable, file-backed range of the original."""
    if original[:2] == b"MZ":
        import pefile

        pe = pefile.PE(data=original)
        try:
            base = pe.OPTIONAL_HEADER.ImageBase
            return [
                (base + s.VirtualAddress, s.get_data()[: s.SizeOfRawData], False)
                for s in pe.sections
                if s.Characteristics & 0x20000000
            ]
        finally:
            pe.close()
    machine = program.image_machine(original)
    _, segments = program.load_image(original, machine=machine)
    return [(s["address"], s["data"], machine == 183) for s in segments if s["flags"] & 1]


def direct_references(original, targets):
    """Count direct call/jump encodings that land on each target entry.

    A byte scan, so counts are an upper bound (data bytes can look like a call),
    but zero means no direct call or jump reaches the entry: the region is only
    reached indirectly, or the original compiler inlined every use.
    """
    import struct

    wanted = {address: name for name, address in targets.items()}
    counts = {name: 0 for name in targets}
    for start, data, arm in executable_ranges(original):
        if arm:
            for offset in range(0, len(data) - 3, 4):
                word = struct.unpack_from("<I", data, offset)[0]
                if word & 0x7C000000 == 0x14000000:  # B / BL imm26
                    imm = word & 0x3FFFFFF
                    if imm & 0x2000000:
                        imm -= 0x4000000
                    target = start + offset + imm * 4
                    if target in wanted:
                        counts[wanted[target]] += 1
        else:
            for offset in range(len(data) - 4):
                if data[offset] in (0xE8, 0xE9):
                    delta = struct.unpack_from("<i", data, offset + 1)[0]
                    target = start + offset + 5 + delta
                    if target in wanted:
                        counts[wanted[target]] += 1
    return counts


def original_callable(original, name, check, project, dependencies=None):
    if original[:2] != b"MZ":
        return original_function(original, name, check, dependencies)
    # PE executables rarely export functions: use the check's address or the
    # project's address table. Imports are not resolved; a function that calls
    # one faults instead of passing.
    address = check.get("original_address")
    if address is None:
        address = (project.get("addresses") or {}).get(name, {}).get("address")
    if isinstance(address, str):
        address = int(address, 16)
    if type(address) is not int:
        raise ContractError(
            "Windows function checks need original_address or a project address: " + name
        )
    from .windows_program import image_info

    base = image_info(original)["image_base"]
    if address < base:
        address += base
    return call_images.load(original, address=address, _imports_resolved=True)


def _function_results(project, original, function_checks, sequence, jobs, compiler, cancel, dependencies, optimization, declarations):
    functions = []
    for name, group in sequence:
        if cancel is not None and cancel.is_set():
            raise Blocked("Project check cancelled")
        spec = project["functions"][name]
        abi = spec.get("abi", "sysv")
        item = {"function": name, "group": group, "sources": spec["sources"], "abi": abi}
        if name not in function_checks:
            item |= {"passed": None, "stage": "program_only"}
            functions.append(item)
            continue
        manifest = {
            "sources": spec["sources"],
            "declarations": declarations,
            "optimization": optimization,
            "architecture": ABI_ARCHITECTURE[abi],
        }
        built = call_images.build(project["_root"], manifest, name, abi, jobs, compiler, cancel)
        if not built["passed"]:
            item |= {"passed": False, "stage": "build", "build": built["build"]}
            functions.append(item)
            continue
        compared = call_images.compare(
            original_callable(original, name, function_checks[name], project, dependencies),
            call_images.load(bytes.fromhex(built["image_hex"]), symbol=name),
            function_checks[name]["cases"],
            cancel,
        )
        item |= {
            "passed": compared["passed"],
            "stage": "compared",
            "tested": compared["tested"],
            "total": compared["total"],
            "failures": compared["failures"][:2],
        }
        functions.append(item)
    return functions


def _summary(compared):
    return [
        {
            "id": r["id"],
            "passed": r["passed"],
            "differences": r["differences"],
            "candidate_status": r["candidate"]["status"],
            **(
                {"stop_context": r["candidate"].get("stop_context")}
                if not r["passed"] and r["candidate"].get("stop_context")
                else {}
            ),
        }
        for r in compared["cases"]
    ]


def compose_and_compare(root, units, declarations, optimization, original, selection, cases, jobs, compiler, cancel, addresses, cache=None):
    """One composition attempt; never raises for candidate-caused failures."""
    lane = Lane(original)
    try:
        built = lane.hybrid.compose(
            root, units, declarations, optimization, original, selection, jobs, compiler, cancel, addresses, cache
        )
    except ContractError as error:
        return {"passed": False, "stage": "compose", "reason": str(error)}
    if not built["passed"]:
        return {"passed": False, "stage": built["stage"], "build": built["build"]}
    coverage = {r["recovered_address"]: r["function"] for r in built["regions"]}
    compared = lane.compare(original, built["image"], cases, cancel, coverage=coverage)
    hits = {name: 0 for name in coverage.values()}
    for r in compared["cases"]:
        for name, count in r["candidate"].get("coverage", {}).items():
            hits[name] += count
    return {
        "passed": compared["passed"],
        "stage": "compared",
        "built": built,
        "compared": compared,
        "hits": hits,
    }


def check(
    root,
    manifest_path,
    original,
    function_checks,
    program_cases,
    jobs,
    compiler="",
    cancel=None,
    plan=None,
    dependencies=None,
    verified=None,
):
    project, build, build_text, units = read_manifest(root, manifest_path)
    project = dict(project, _root=root)
    function_checks = function_checks or {}
    validate_checks(function_checks, project)
    lane = Lane(original)
    declarations = (build or project).get("declarations", "")
    optimization = (build or project).get("optimization", "O2")
    sequence, planned = order(project["functions"], plan)
    functions = _function_results(
        project, original, function_checks, sequence, jobs, compiler, cancel, dependencies, optimization, declarations
    )
    failing = [f for f in functions if f["passed"] is False]
    verified_prefix = []
    for item in functions:
        if item["passed"] is False:
            break
        verified_prefix.append(item["function"])
    previous = set((verified or {}).get("recovered", ()))
    result = {
        "functions": functions,
        "verified_prefix": verified_prefix,
        "first_failure": failing
        and {"function": failing[0]["function"], "group": failing[0]["group"]}
        or None,
        "source_hashes": {
            **{n: hashlib.sha256(t.encode()).hexdigest() for n, t in units.items()},
            **({project["build"]: normalized_hash(build_text)} if build else {}),
            **(
                {project["inventory_path"]: normalized_hash(_text(root, project["inventory_path"], 8_000_000))}
                if "inventory_path" in project
                else {}
            ),
        },
        "manifest_sha256": digest(json.loads(_text(root, manifest_path))),
    }
    image = None
    candidate_architectures = {
        ABI_ARCHITECTURE[s.get("abi", "sysv")] for s in project["functions"].values()
    } | ({build.get("architecture", "x86_64")} if build else set())
    same = candidate_architectures <= {lane.architecture}
    reason = "Candidate architecture differs from the original; regions cannot share one image"
    if same:
        # Dynamic/PIE originals keep the complete-build path only.
        blocked = lane.static_reason(original)
        if blocked:
            same, reason = False, blocked
    composition = {"applicable": same}
    if not same:
        composition["reason"] = reason
    elif project["functions"]:
        eligible = [f["function"] for f in functions if f["passed"] is not False]
        regressed = sorted(previous - set(eligible))
        attempts = []
        objects = {}

        def attempt(selection):
            units_for = {}
            for name in selection:
                for path in project["functions"][name]["sources"]:
                    units_for[path] = units[path]
            outcome = compose_and_compare(
                root,
                units_for,
                declarations,
                optimization,
                original,
                selection,
                program_cases,
                jobs,
                compiler,
                cancel,
                project.get("addresses"),
                objects,
            )
            attempts.append(
                {
                    "selection": list(selection),
                    "passed": outcome["passed"],
                    "stage": outcome["stage"],
                }
            )
            return outcome

        accepted, rejected = [], []
        outcome = attempt(eligible) if eligible else None
        if outcome is not None and outcome["passed"]:
            accepted = list(eligible)
        elif eligible:
            if len(eligible) > MAX_GREEDY:
                raise Blocked(
                    "Composition isolation is bounded to 48 regions; split the project check"
                )
            outcome = None
            for name in eligible:
                trial = attempt(accepted + [name])
                if trial["passed"]:
                    accepted.append(name)
                    outcome = trial
                else:
                    reason = {"function": name, "stage": trial["stage"]}
                    if trial["stage"] == "compared":
                        reason["cases"] = [c for c in _summary(trial["compared"]) if not c["passed"]][:3]
                    elif "reason" in trial:
                        reason["reason"] = trial["reason"]
                    else:
                        reason["build"] = trial.get("build")
                    rejected.append(reason)
            if outcome is None:
                outcome = attempt([])
        regressed = sorted(
            set(regressed) | (previous & {r["function"] for r in rejected})
        )
        inventory = lane.hybrid.inventory(original, project.get("addresses"))
        hits = outcome.get("hits", {}) if outcome else {}
        unexercised = sorted(n for n in accepted if not hits.get(n))
        references = direct_references(
            original,
            {
                n: inventory["functions"][n]["address"]
                for n in unexercised
                if n in inventory["functions"]
            },
        )
        unvalidated = sorted(
            n for n in accepted if n not in function_checks and not hits.get(n)
        )
        composition |= {
            "passed": bool(outcome and outcome["passed"]),
            "recovered": accepted,
            "fallback": sorted(set(inventory["functions"]) - set(accepted)),
            "fallback_planned": (
                sorted(set(planned) - set(accepted)) if planned is not None else None
            ),
            "rejected": rejected,
            "regressed": regressed,
            "rolled_back": sorted(set(regressed) - set(accepted)),
            "unexercised": unexercised,
            # Unexercised regions with no direct call or jump in the original:
            # reached only indirectly, or inlined into their callers.
            "no_direct_callers": sorted(n for n, c in references.items() if c == 0),
            "unvalidated": unvalidated,
            "executions": hits,
            "attempts": attempts,
        }
        if outcome and outcome.get("stage") == "compared":
            composition["cases"] = _summary(outcome["compared"])
            composition["regions"] = outcome["built"]["regions"]
            composition["image_sha256"] = outcome["built"]["sha256"]
            image = outcome["built"]["image"]
    else:
        composition |= {"passed": None, "reason": "No recovered regions declared"}
    result["composition"] = composition
    if build is not None:
        built = lane.build(root, build, jobs, compiler, cancel)
        if not built["passed"]:
            result["program"] = {"passed": False, "stage": "build", "build": built["build"]}
        else:
            complete = bytes.fromhex(built.pop(lane.image_key))
            compared = lane.compare(original, complete, program_cases, cancel, dependencies or None)
            result["program"] = compared
            result["program_sha256"] = built["sha256"]
            if compared["passed"]:
                image = complete
    coverage = {
        "checked": [f["function"] for f in functions if f["passed"] is not None],
        "program_only": [f["function"] for f in functions if f["passed"] is None],
        "planned_functions": len(planned) if planned is not None else None,
        "unchecked_planned": (
            sorted(set(planned) - set(project["functions"])) if planned is not None else None
        ),
    }
    result["coverage"] = coverage
    region_ok = (
        composition.get("passed") is True
        and not composition.get("rejected")
        and not composition.get("unvalidated")
        if same and project["functions"]
        else None
    )
    program_ok = result["program"]["passed"] if "program" in result else None
    if region_ok is None and program_ok is None:
        raise ContractError("A project check needs recovered regions or a complete build")
    result["passed"] = (
        not failing
        and region_ok is not False
        and program_ok is not False
    )
    if image is not None:
        result["image"] = image
        result["image_sha256"] = hashlib.sha256(image).hexdigest()
    result["claim"] = (
        "Declared function cases in dependency order, original-code fallback for every "
        "unrecovered function, and declared whole-program cases"
        + (" for the complete source build" if build is not None else "")
        + ". Unchecked functions, unexercised regions, inlined original copies and inputs "
        "outside the corpus are not established."
    )
    return result
