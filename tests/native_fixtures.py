"""Select the compiler for the guest format, separately from the host oracle."""

import os
import platform
import shutil
import pytest


def elf_compiler():
    # MinGW GCC produces PE, even with the freestanding Linux recipe's flags.
    compiler = (
        (os.environ.get("HA_TEST_CLANG") or shutil.which("clang"))
        if os.name == "nt"
        else (shutil.which("gcc") or shutil.which("clang"))
    )
    if not compiler:
        pytest.skip("A Linux ELF cross compiler is required")
    return compiler


LINUX_ORACLE = pytest.mark.skipif(
    platform.system() != "Linux"
    or platform.machine().lower() not in ("x86_64", "amd64"),
    reason="Native Linux ELF oracle requires a Linux x86-64 host",
)


class PassingChecks:
    """Stand-in sessions for push early, check later: the independent checker (in its
    own conversation) passes every file it's given."""

    def __init__(self, config):
        self.checked = []
        outer = self

        class Checker:
            def __init__(self):
                self.config = config

            async def exchange(self, route, message):
                import json as _json

                files = _json.loads(message["payload"])["files"]
                outer.checked.append((route, [f["path"] for f in files]))
                return {"request_id": message["id"], "type": "check_report", "summary": "Fine.",
                        "results": [{"path": f["path"], "verdict": "pass", "findings": "Fine."} for f in files]}

        self.checker = Checker()

    async def ensure(self, *args, **kwargs):
        pass

    async def isolated_browser(self, key, route, identity):
        return self.checker

    async def release_isolated(self, identity):
        pass


def pass_checks(broker, project, checker="reviewer.high"):
    """Record a passing independent check of everything pending (for tests that drive
    acceptance directly)."""
    checks = broker.drafts.checks
    items = checks.pending(project)
    return checks.finish(project, {i["path"]: i["sha256"] for i in items},
                         {i["path"]: {"verdict": "pass", "findings": "fine"} for i in items}, "checks/test.md", checker)
