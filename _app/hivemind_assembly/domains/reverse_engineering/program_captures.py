"""Owner-scoped raw frame/audio observations for bounded program replays.

Selectors name entire standard streams or final guest files, never host paths.
Unselected outputs and all other acceptance criteria remain exact.
"""

import copy

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.observations import compare_capture, validate_comparators

LIMIT = 1_000_000


def validate(case, windows=False):
    if not isinstance(case, dict):
        raise ContractError("Program cases must be objects")
    rules = copy.deepcopy(case.get("captures", {}))
    if not isinstance(rules, dict) or len(rules) > 66:
        raise ContractError("Program captures must map at most 66 output selectors")
    for selector in rules:
        if selector in ("stdout", "stderr"):
            continue
        if not isinstance(selector, str) or not selector.startswith("file:"):
            raise ContractError(
                "Capture selectors are stdout, stderr or file:<guest path>"
            )
        path = selector[5:]
        if windows:
            from .windows_files import filename

            if filename(path) != path:
                raise ContractError(
                    "Windows capture file names must be canonical lowercase names"
                )
        else:
            from .platform_runtime import files_spec

            if case.get("runtime", "unicorn_linux") != "qiling_linux":
                raise ContractError("File captures require the Qiling lane")
            files_spec({path: ""})
    return validate_comparators(rules, rules, LIMIT)


def content(observation, selector):
    value = (
        observation.get(selector + "_hex")
        if selector in ("stdout", "stderr")
        else observation.get("files", {}).get(selector[5:])
    )
    return None if value is None else bytes.fromhex(value)


def compare(before, after, rules):
    return {
        selector: compare_capture(
            content(after, selector), content(before, selector), rule
        )
        for selector, rule in rules.items()
    }


def exact_files(observation, rules):
    return {
        path: value
        for path, value in observation.get("files", {}).items()
        if "file:" + path not in rules
    }


def preflight(observation, rules):
    # Identical malformed/missing captures are not valid reference evidence.
    metrics = compare(observation, observation, rules)
    if any(not item["passed"] for item in metrics.values()):
        raise Blocked(
            "Original program capture is missing or has the wrong declared shape"
        )
