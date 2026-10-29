"""Independent checks of what the assistants wrote.

The checker is never the writer's conversation: it's a fresh, separate conversation,
with an assistant from another provider when one is signed in with usage left
(otherwise another of your assistants, or the same kind in a new conversation). It
gets only the files and their sources: the project's objective, its completion checks
and HA's own results for those files, never the writer's reasoning. Its report stays
in the project under checks/, and the "checks pending" markers of what passed are
removed in the same commit. A failed or interrupted check keeps the markers.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from hivemind_assembly.core.checks import REPORTS, Checks, blob_sha
from hivemind_assembly.core.common import AllowanceUnavailable, ContractError, digest, scoped

MESSAGE_CHARS = 120_000  # File text per checker message.
FILE_CHARS = 100_000  # A longer file can't be checked in one message.
CHECK_TOOLS = (
    "validate_c_function", "compare_program", "compare_windows_program", "compare_linked_function",
    "compare_project", "test_programs", "test_game", "hosted_test_status",
)
INSTRUCTION = (
    "You are an independent checker. Another assistant wrote these files; you did not. Check each file against "
    "the project's objective, its completion checks and the sources given: is it correct, complete for what it "
    "claims, and free of invented results? HA's own check results are facts; a file's own comments and claims "
    "are not. Pass a file only if you found no problem that matters; otherwise fail it and say exactly what is "
    "wrong and where. Don't rewrite the files. Return type check_report, results [{path, verdict: pass or fail, "
    "findings}] with one entry for every file, summary, and request_id."
)


def report_name(key):
    return f"{REPORTS}/{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{key[:8]}.md"


class IndependentChecks:
    def __init__(self, team):
        self.team = team
        self.store = team.store
        self.running = set()  # Projects being checked now.

    @property
    def drafts(self):
        return self.team.broker.drafts

    @property
    def checks(self) -> Checks:
        return self.drafts.checks

    def provider(self, route):
        return (self.team.config["routes"].get(route) or {}).get("provider")

    def choose(self, writer):
        """A checker that isn't the writer: another provider first, then another
        assistant of the same provider, then the writer's kind in a new conversation
        (the check always runs in its own conversation). None if nobody has usage left."""
        writer_provider = self.provider(writer) if writer and writer != "outside" else None
        ready = [
            route for route in self.team.config["routes"]
            if (observation := self.team.observations.get(route)) is not None and observation.eligible()
        ]
        order = {"reviewer": 0, "worker": 1, "adviser": 2}

        def rank(route):
            other_provider = writer_provider is None or self.provider(route) != writer_provider
            return (0 if other_provider else 1 if route != writer else 2, order.get(route.split(".")[0], 3), route)

        ready.sort(key=rank)
        return ready[0] if ready else None

    def sources(self, project, paths):
        """What the checker may use besides the files: the objective, the completion
        checks and HA's recorded check results that name these files."""
        from hivemind_assembly.core.acceptance import Acceptance

        info = self.store.project(project)
        tasks = self.store.rows("SELECT id,objective,status FROM tasks WHERE project_id=? ORDER BY rowid", (project,))
        acceptance = []
        for task in tasks:
            try:
                acceptance.append(Acceptance(self.team.controller, self.team.broker).describe(task["id"]))
            except Exception:
                continue
        results = []
        marks = tuple(paths)
        for row in self.store.rows(
            "SELECT o.tool,o.args,o.result,o.state FROM operations o JOIN tasks t ON t.id=o.task_id "
            "WHERE t.project_id=? AND o.state IN ('completed','saved') ORDER BY o.created DESC LIMIT 400",
            (project,),
        ):
            if row["tool"] not in CHECK_TOOLS or not any(p in (row["args"] or "") for p in marks):
                continue
            result = json.loads(row["result"] or "{}")
            brief = {k: result[k] for k in ("passed", "status", "summary", "failures", "differences") if k in result}
            results.append({"tool": row["tool"], "args": json.loads(row["args"]), "result": brief})
            if len(results) >= 20:
                break
        return {
            "project_objective": info.get("objective") if isinstance(info, dict) else None,
            "tasks": [{"objective": t["objective"], "status": t["status"]} for t in tasks],
            "completion_checks": acceptance,
            "ha_check_results": json.loads(json.dumps(results, default=str)[:60_000]) if results else [],
        }

    def batches(self, project, items):
        """Messages of files for the checker: [(files, unreadable {path: reason})]. A file
        written outside HA is read from GitHub when the project's folder doesn't have it."""
        import hashlib

        root = self.drafts.workspace(project)
        publications = self.team.broker.publications
        out, batch, size, skipped = [], [], 0, {}
        hand = "; check it yourself and mark it checked on the Projects page"
        for item in items:
            p = scoped(root, item["path"])
            text, raw = None, None
            try:
                if item.get("outside") and publications and publications.enabled(project):
                    # Written elsewhere: the version on GitHub is the one to check.
                    text = publications.read_text(project, item["path"])
                elif p.is_file():
                    raw = p.read_bytes()  # Hashed below from these same bytes.
                    text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                skipped[item["path"]] = "it isn't a text file HA can show a checker" + hand
                continue
            except Exception as error:  # A folder named in a row, a lost connection: this item only.
                skipped[item["path"]] = f"HA couldn't read it from GitHub ({str(error)[:120]})" + hand
                continue
            if text is None:
                skipped[item["path"]] = "HA can't find it in the project's folder or on GitHub" + hand
                continue
            if len(text) > FILE_CHARS:
                skipped[item["path"]] = f"it's longer than {FILE_CHARS:,} characters; split it" + hand
                continue
            sha = hashlib.sha256(raw if raw is not None else text.encode("utf-8")).hexdigest()
            if batch and size + len(text) > MESSAGE_CHARS:
                out.append((batch, {}))
                batch, size = [], 0
            batch.append({"path": item["path"], "sha256": sha, "text": text})
            size += len(text)
        if batch or skipped:
            out.append((batch, skipped))
        return out

    @staticmethod
    def store_hash(path):
        from hivemind_assembly.core.common import file_hash

        return file_hash(path)

    def who(self, project):
        """Which assistant would check this project's oldest pending file now."""
        items = sorted(self.checks.pending(project), key=lambda i: i.get("since") or 0)
        route = self.choose(items[0].get("writer")) if items else None
        return self.checks.name(route) if route else None

    async def requested(self, project):
        """Run from the Projects page: any error is shown there, not lost."""
        try:
            await self.run(project, requested=True)
        except Exception as error:
            def note(state):
                state["last_run"] = {"at": time.time(), "requested": True, "error": str(error)[:300]}
            self.checks.update(project, note)

    async def run(self, project, requested=False):
        """Check what's pending in this project. Returns {passed, failed, left, waiting, reports}."""
        if project in self.running:
            return {"status": "running"}
        self.running.add(project)
        outcome = {"passed": [], "failed": [], "left": [], "reports": [], "waiting": None}
        try:
            reconciliation = await self.team.blocking(self.drafts.reconcile, project)
            if reconciliation.get("deferred"):
                outcome["waiting"] = "Reconcile the pending workspace operation before checking its files."
                outcome["left"] = [i["path"] for i in self.checks.pending(project)]
                return outcome
            if self.checks.stale(project):
                await self.team.blocking(self.drafts.sync, project, (), None, "Checks stopped when HA stopped")
            groups = {}
            for item in self.checks.pending(project):
                groups.setdefault(item.get("writer"), []).append(item)
            for writer, group in groups.items():
                route = self.choose(writer)
                if route is None:
                    outcome["waiting"] = "No assistant has usage left to check; HA checks when one has."
                    outcome["left"] += [i["path"] for i in group]
                    continue
                for batch, skipped in await self.team.blocking(self.batches, project, group):
                    if skipped:
                        self._unreadable(project, skipped)
                        outcome["left"] += list(skipped)
                    if batch:
                        result = await self.check(project, route, writer, batch)
                        for key in ("passed", "failed", "left"):
                            outcome[key] += result[key]
                        outcome["reports"].append(result["report"])
            self._record(project, outcome, requested)
            return outcome
        finally:
            self.running.discard(project)

    def _unreadable(self, project, skipped):
        def note(state):
            for path, reason in skipped.items():
                if path in state["items"]:
                    state["items"][path].update(state="pending", note=f"can't be checked automatically: {reason}")
        self.checks.update(project, note)

    def _record(self, project, outcome, requested):
        def note(state):
            state["last_run"] = {"at": time.time(), "requested": requested,
                                 **{k: (len(v) if isinstance(v, list) else v) for k, v in outcome.items() if k != "reports"},
                                 "reports": outcome["reports"]}
        self.checks.update(project, note)

    async def check(self, project, route, writer, batch):
        paths = [f["path"] for f in batch]
        key = "check_" + digest({"project": project, "files": [(f["path"], f["sha256"]) for f in batch], "route": route})[:32]
        observation = self.team.observations.get(route)
        if observation is None or not observation.eligible() or self.team.sessions is None:
            raise AllowanceUnavailable("The checking assistant has no usage left: " + route)
        self.checks.begin(project, paths, route)
        await self.team.blocking(self.drafts.sync, project, (), None, "Checking: " + ", ".join(paths[:5]))
        try:
            with self.team.learning_budget(route, key, observation):
                # Its own conversation: the checker never sees the writer's.
                browser = await self.team.sessions.isolated_browser(key, route, key + "_session")
                rows = self.store.rows("SELECT * FROM messages WHERE id=?", (key,))
                sources = self.sources(project, paths)
                message = rows[0] if rows else self.team.controller.prepare_message(
                    key, route, browser.config["routes"][route]["conversation_url"],
                    {"instruction": INSTRUCTION, "files": batch, "sources": sources}, key,
                )
                response = (
                    json.loads(message["response"]) if message["state"] == "validated"
                    else await browser.exchange(route, message)
                )
                await self.team.sessions.release_isolated(key + "_session")
        except BaseException as error:
            try:
                await self.team.sessions.release_isolated(key + "_session")
            except Exception:
                pass
            self.checks.interrupt(project, paths, str(error)[:120] or type(error).__name__)
            await self.team.blocking(self.drafts.sync, project, (), None, "Check stopped early: " + ", ".join(paths[:5]))
            raise
        results = self.results(response, paths)
        name = report_name(key)
        text = self.report(project, route, writer, batch, results, response.get("summary", ""), sources)
        # An editor outside HA can change files without updating our pending-item hashes.
        # Compare bytes again before accepting the checker response for its older snapshot.
        reconciliation = await self.team.blocking(self.drafts.reconcile, project)
        if reconciliation.get("deferred"):
            self.checks.interrupt(project, paths, "workspace operation still unresolved")
            raise ContractError("Reconcile the pending workspace operation before accepting this check")
        outcome = self.checks.finish(project, {f["path"]: f["sha256"] for f in batch}, results, name, route,
                                     report_text=text,
                                     versions={f["path"]: blob_sha(f["text"]) for f in batch})
        # The report and the removal of what passed go up in the same commit.
        await self.team.blocking(
            self.drafts.sync, project, (), {name: text},
            f"Independent check by {self.checks.name(route)}: {len(outcome['passed'])} passed, {len(outcome['failed'])} failed")
        self.store.event(project, "independent_check", {"report": name, "checker": route, **outcome})
        return {**outcome, "report": name}

    @staticmethod
    def results(response, paths):
        if response.get("type") != "check_report" or not isinstance(response.get("results"), list):
            raise ContractError("Expected a check report")
        found = {}
        for entry in response["results"]:
            if (
                isinstance(entry, dict)
                and entry.get("path") in paths
                and entry.get("verdict") in ("pass", "fail")
            ):
                found[entry["path"]] = {"verdict": entry["verdict"],
                                        "findings": str(entry.get("findings") or "")[:4000]}
        return found

    def report(self, project, route, writer, batch, results, summary, sources):
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        name = self.store.project(project).get("name", project)
        writer_name = self.checks.name(writer)
        checker = self.checks.name(route)
        lines = [
            f"# Independent check, {when}",
            "",
            f"- Project: {name}",
            f"- Checker: {checker}, in a new conversation of its own",
            f"- Written by: {writer_name}" + (" (another provider checked it)"
                                              if self.provider(route) != self.provider(writer) else
                                              " (no other provider had usage left; a separate conversation checked it)"),
            "- Given: the files below and their sources (objective, completion checks, "
            f"{len(sources['ha_check_results'])} of HA's own check results). Not given: the writer's conversation.",
            "",
            "| File | SHA-256 | Result |",
            "| --- | --- | --- |",
        ]
        for f in batch:
            verdict = results.get(f["path"], {}).get("verdict")
            label = {"pass": "passed", "fail": "failed"}.get(verdict, "not reported")
            lines.append(f"| {f['path']} | {f['sha256'][:16]}… | {label} |")
        lines += ["", "## Findings", ""]
        for f in batch:
            result = results.get(f["path"])
            lines.append(f"### {f['path']}")
            lines.append("")
            lines.append((result or {}).get("findings") or "No findings reported.")
            lines.append("")
        lines += ["## Summary", "", str(summary or "No summary given.")[:4000], ""]
        return "\n".join(lines)

