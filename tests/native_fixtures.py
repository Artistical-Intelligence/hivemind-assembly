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
    paths = [item["path"] for item in items]
    report = "checks/test.md"
    text = "# Fixture check report\n\nMocked approval for automated tests; not live provider evidence.\n\n"
    text += "\n".join(f"- {item['path']}: pass ({item['sha256']})" for item in items) + "\n"
    checks.begin(project, paths, checker)
    outcome = checks.finish(
        project, {item["path"]: item["sha256"] for item in items},
        {path: {"verdict": "pass", "findings": "fixture approval"} for path in paths},
        report, checker, report_text=text,
        versions={path: checks.state(project).get("blobs", {}).get(path) for path in paths},
    )
    # Match the production check lifecycle: persist its report and remove the
    # approved markers together, so reconciliation can verify the evidence.
    broker.drafts.sync(project, extra={report: text}, message="Fixture independent check")
    return outcome
