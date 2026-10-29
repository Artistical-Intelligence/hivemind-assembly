"""Push early, check later.

Every file an assistant creates or changes is pushed to the project's repository at
once, before any review, and marked as not yet checked:

- STATUS.md in the file's folder gets a line "CHECKS PENDING: <file> — <what it's
  waiting for>";
- CHECKS_STATUS.md at the top of the repository gets a row (item, folder, waiting for).

Missing markers alone do not prove a check. A check is done by a different assistant session than the
writer (another provider when one is signed in, always a fresh conversation), which
sees only the files and their sources. Its report stays under checks/ as evidence;
the markers of what passed are removed in the same commit. A failed or interrupted
check keeps the marker and says what failed or is left. Nothing with a marker is
accepted as a finished deliverable.

The same rules go into the repository's AGENTS.md (with a pointer from CLAUDE.md), so
assistants working outside HA follow them too, and QUEUE.md lists pending checks
before new work for whoever picks the repository up next.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
import time
from pathlib import PurePosixPath

from .common import Blocked, ContractError, atomic_write, file_hash, scoped

MARK = "CHECKS PENDING:"
STATUS = "STATUS.md"
LEDGER = "CHECKS_STATUS.md"
QUEUE = "QUEUE.md"
REPORTS = "checks"
AGENTS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
HISTORY = 500  # Checked items remembered per project, newest first.
START = "<!-- checks-workflow:start (kept up to date by Hivemind Assembly) -->"
END = "<!-- checks-workflow:end -->"
QUEUE_START = "<!-- queue:start (kept up to date by Hivemind Assembly) -->"
QUEUE_END = "<!-- queue:end -->"

RULES = """## Push early, check later

Every assistant working in this repository (Claude, ChatGPT or any other) follows these rules:

1. Commit and push every file you create or change right away, before any review.
2. Mark what isn't checked yet: add a line `CHECKS PENDING: <file> — <what still needs checking>`
   to STATUS.md in the file's folder, and a row to CHECKS_STATUS.md at the top of the repository
   (item, folder, waiting for). Missing markers alone do not prove a file was checked.
3. A check is done by a different assistant session than the one that wrote the file (another
   provider when possible, otherwise a fresh conversation). The checker gets only the files and
   their sources, and writes a report under checks/ that stays in the repository.
4. When a check passes, remove its STATUS.md line (and STATUS.md once it's empty) and its
   CHECKS_STATUS.md row in the same commit as the report. When a check fails or stops early,
   keep the marker and say in STATUS.md what failed or what is left.
5. Never put anything with a pending marker into a release, the main deliverable or any other
   published output.
6. When you pick up this repository, reconcile CHECKS_STATUS.md and QUEUE.md with current files,
   their hashes and check reports: finish pending checks before starting more work. Preserve
   completed work; a changed file must be checked again. Failed checks permit focused repairs.
7. Give each worker explicit output ownership. HA's project writer lease and broker own edits
   and saves; assistants outside HA must likewise use one integration/saving owner. Save drafts
   immediately with pending markers; never wait for an entire batch or acceptance check.
8. Brief each worker with the current task, source/revision references, necessary dependencies,
   edit scope and completion criteria. Retrieve additional evidence as needed; do not replace
   required reading with a summary or repeat unrelated conversation history.
9. Validate the combined deliverable against its existing whole-project checks before completion;
   passing child tasks alone is insufficient. Reuse required checks without duplicate reviews.
10. Do not add operational performance records for these practices. Existing correctness evidence,
    recovery journals and learning evaluations remain required."""

POINTER = "Read AGENTS.md first: it has this repository's rules, including push early, check later."

LEDGER_HEAD = """# Checks status

Files pushed before an independent check. Missing rows or STATUS.md lines alone
do not prove a check; verify current file evidence against the reports in checks/.

| Item | Folder | Waiting for |
| --- | --- | --- |"""

PROVIDERS = {"openai": "ChatGPT", "claude": "Claude"}
LOCK = threading.RLock()  # Writes and checks change the same state from different threads.


def locked(method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        with LOCK:
            return method(*args, **kwargs)
    return wrapper


def managed(path):
    """Files HA keeps up to date itself; writing them isn't work to check."""
    p = PurePosixPath(path)
    return p.name in (STATUS, LEDGER, QUEUE) or (p.parts and p.parts[0] == REPORTS)


def safe_path(path):
    """A plain relative path inside the repository (rows written by others can be anything)."""
    p = PurePosixPath(path)
    return bool(path) and path not in (".", "./") and not p.is_absolute() and "\\" not in path and ":" not in path and ".." not in p.parts \
        and not any(part.startswith(".") for part in p.parts) and len(path) <= 500


def folder_of(path):
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def cell(text):
    return " ".join(str(text).replace("|", "\\|").split())


def section(text, start, end, body):
    """Put body between the start and end markers of text, keeping everything else."""
    block = f"{start}\n{body}\n{end}"
    if text and start in text and end in text.split(start, 1)[1]:
        before, rest = text.split(start, 1)
        after = rest.split(end, 1)[1]
        return before + block + after
    if not text or not text.strip():
        return block + "\n"
    return text.rstrip("\n") + "\n\n" + block + "\n"


def parse_ledger(text):
    """Rows of CHECKS_STATUS.md: [{item, folder, waiting}]."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- :"):
            continue
        parts = [p.strip().replace("\\|", "|") for p in re.split(r"(?<!\\)\|", line.strip("|"))]
        if len(parts) < 3 or parts[0].lower() == "item":
            continue
        rows.append({"item": parts[0], "folder": parts[1], "waiting": parts[2]})
    return rows


def waiting_in(root, rels):
    """Files of a folder or repository that its own markers (STATUS.md lines and
    CHECKS_STATUS.md rows) say still wait for a check; a row may name a whole folder."""
    from pathlib import Path

    rels = set(rels)
    found = set()

    def read(rel):
        try:
            return (Path(root) / rel).read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    for row in parse_ledger(read(LEDGER)):
        item = row["item"].strip("`").strip().strip("/")
        if item in rels:
            found.add(item)
        elif item:
            found |= {r for r in rels if r.startswith(item + "/")}
    for rel in rels:
        if PurePosixPath(rel).name != STATUS:
            continue
        folder = folder_of(rel)
        for line in read(rel).splitlines():
            if line.startswith(MARK):
                name = line[len(MARK):].strip().split(" — ", 1)[0].strip().strip("`")
                candidate = f"{folder}/{name}" if folder else name
                if candidate in rels:
                    found.add(candidate)
    return found


class Checks:
    """Which files of a project are waiting for an independent check, and the marker
    files that say so."""

    def __init__(self, store, providers=None):
        self.store = store
        # route -> provider name ("openai", "claude"), for the writer and the checker.
        self.providers = providers or (lambda route: None)

    # ------------------------------------------------------------ state
    def state(self, project):
        rows = self.store.rows("SELECT state FROM project_checks WHERE project_id=?", (project,))
        state = json.loads(rows[0]["state"]) if rows else {}
        state.setdefault("items", {})
        state.setdefault("checked", [])
        state.setdefault("folders", [])  # Folders whose STATUS.md HA last wrote lines in.
        state.setdefault("remote_folders", [])
        state.setdefault("push", {"state": "idle"})
        state.setdefault("blobs", {})  # What HA last pushed of each file (Git blob IDs).
        return state

    def save(self, project, state, db=None):
        if db is None:
            with self.store.tx() as transaction:
                return self.save(project, state, transaction)
        db.execute(
            "INSERT INTO project_checks VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET state=excluded.state,updated=excluded.updated",
            (project, json.dumps(state, ensure_ascii=False, separators=(",", ":")), time.time()),
        )

    def pending(self, project):
        return sorted(self.state(project)["items"].values(), key=lambda i: i["path"])

    def summary(self, project):
        state = self.state(project)
        items = sorted(state["items"].values(), key=lambda i: i["path"])
        return {
            "pending": len(items),
            "checked": len(state["checked"]),
            "items": items[:200],
            "recent": state["checked"][:20],
            "push": state["push"],
            "last_run": state.get("last_run"),
            "kept_local": state.get("kept_local", {}),
        }

    def name(self, route):
        if not route:
            return "an assistant"
        if route == "outside":
            return "an assistant outside HA"
        provider = PROVIDERS.get(self.providers(route), self.providers(route) or "")
        return f"{provider} ({route})" if provider else route

    # ------------------------------------------------------------ changes
    @locked
    def update(self, project, change):
        """Change the state under the lock: change(state) edits it in place."""
        state = self.state(project)
        result = change(state)
        self.save(project, state)
        return result

    @locked
    def mark(self, project, path, writer, sha256, before=None):
        """An assistant created or changed this file: it waits for an independent check.
        before: the file's SHA-256 before this change, so a push can tell whether
        GitHub still has the version the assistant started from."""
        if managed(path):
            return None
        state = self.state(project)
        state.setdefault("before", {})
        if path not in state.get("unpushed", []) and path not in state["before"]:
            state["before"][path] = before
        old = state["items"].get(path)
        note = "independent check by a different assistant"
        if old and old.get("state") == "failed":
            note = "check again after the fix (the last check failed)"
        elif old and old.get("state") == "checking":
            note = "check again: the file changed while it was being checked"
        state["items"][path] = {
            "path": path,
            "folder": folder_of(path),
            "writer": writer,
            "writer_provider": self.providers(writer),
            "sha256": sha256,
            "since": old["since"] if old else time.time(),
            "state": "pending",
            "note": note,
        }
        self.save(project, state)
        return state["items"][path]

    @locked
    def begin(self, project, paths, checker):
        state = self.state(project)
        for path in paths:
            if path in state["items"]:
                state["items"][path].update(state="checking", note=f"being checked by {self.name(checker)}",
                                            checker=checker, started=time.time())
                state["items"][path].pop("needs_recheck", None)
        self.save(project, state)

    @locked
    def interrupt(self, project, paths, reason):
        state = self.state(project)
        for path in paths:
            item = state["items"].get(path)
            if item and item["state"] == "checking":
                item.update(state="interrupted", note=f"check stopped early ({reason}); run it again")
        self.save(project, state)

    @locked
    def stale(self, project, active=()):
        """Checks that were running when HA stopped are interrupted, not passed."""
        state = self.state(project)
        changed = False
        for item in state["items"].values():
            if item["state"] == "checking" and item["path"] not in active:
                item.update(state="interrupted", note="check stopped early (HA stopped); run it again")
                changed = True
        if changed:
            self.save(project, state)
        return changed

    @locked
    def reconcile_local(self, project, root):
        """Compare retained evidence with current local files; never infer a pass from markers.

        Inspect known pending paths, the newest retained check per path (history is bounded),
        and explicit local marker entries. This is not a full scan of every source file or
        an audit of unmarked remote edits. Keep remote-only pending items remote-only.
        """
        state = self.state(project)
        # A broker operation may have replaced bytes but not yet journaled its final hash.
        if self.store.rows(
            "SELECT o.id FROM operations o JOIN tasks t ON t.id=o.task_id "
            "WHERE t.project_id=? AND o.state IN ('running','uncertain','applied') LIMIT 1",
            (project,),
        ):
            return {"changed": [], "pending": len(state["items"]), "deferred": True}
        latest = {}
        for item in state["checked"]:
            latest.setdefault(item["path"], item)
        candidates = dict(latest)
        candidates.update(state["items"])
        markers = {}
        ledger = scoped(root, LEDGER)
        if ledger.is_file():
            for row in parse_ledger(ledger.read_text("utf-8")):
                path = row["item"].strip().strip("`").strip()
                if safe_path(path) and not managed(path):
                    markers[path] = row["waiting"] or "independent check"
        # Only marker files are enumerated; source contents are never scanned wholesale.
        for marker in root.rglob(STATUS):
            if marker.is_symlink():
                continue
            rel = marker.relative_to(root).as_posix()
            if not safe_path(rel):
                continue
            for line in marker.read_text("utf-8").splitlines():
                if not line.startswith(MARK):
                    continue
                name, _, note = line[len(MARK):].strip().partition(" — ")
                name = name.strip().strip("`")
                folder = folder_of(rel)
                path = f"{folder}/{name}" if folder else name
                if safe_path(path) and not managed(path):
                    markers[path] = note or "independent check"
        for path in markers:
            candidates.setdefault(path, {})
        changed, discovered = [], []
        for path, previous in candidates.items():
            # Before origin was recorded in checked history, only remote imports
            # used writer="outside". New local discoveries explicitly record
            # outside=False on completion, so they remain locally verifiable.
            remote_origin = previous.get(
                "outside", path not in state["items"] and previous.get("writer") == "outside")
            if not safe_path(path) or managed(path) or remote_origin:
                continue
            try:
                current = file_hash(scoped(root, path))
                unavailable = False
            except (OSError, ContractError):
                current, unavailable = None, True
            pending = state["items"].get(path)
            drift = previous.get("sha256") != current or bool(previous.get("evidence_unavailable")) != unavailable
            missing_report = False
            if path in latest and not pending:
                report = latest[path].get("report")
                try:
                    missing_report = not report or not scoped(root, report).is_file()
                except ContractError:
                    missing_report = True
            if not drift and not missing_report and (pending or path not in markers):
                continue
            item = dict(pending or {})
            item.update(path=path, folder=folder_of(path), writer=item.get("writer", "outside"),
                        writer_provider=item.get("writer_provider"), sha256=current,
                        since=item.get("since", time.time()), state="pending",
                        evidence_unavailable=unavailable, needs_recheck=True, outside=False)
            item["note"] = (
                "cannot verify: the local file is missing or unreadable" if unavailable else
                "check again: local bytes changed since the retained evidence" if drift and previous else
                "check again: the retained check report is missing" if missing_report else
                markers.get(path, "independent check")
            )
            state["items"][path] = item
            # Never let an old pass remove freshly discovered pending markers.
            for key in ("clear_local", "clear_remote"):
                state[key] = [p for p in state.get(key, []) if p != path]
            state.get("clear_versions", {}).pop(path, None)
            discovered.append(path)
            if drift:
                changed.append(path)
                state.setdefault("before", {}).setdefault(path, previous.get("sha256"))
        if discovered:
            with self.store.tx() as db:
                if db.execute(
                    "SELECT o.id FROM operations o JOIN tasks t ON t.id=o.task_id "
                    "WHERE t.project_id=? AND o.state IN ('running','uncertain','applied') LIMIT 1",
                    (project,),
                ).fetchone():
                    return {"changed": [], "pending": len(self.state(project)["items"]), "deferred": True}
                self.save(project, state, db)
                if changed:
                    db.execute("UPDATE projects SET revision=revision+1 WHERE id=?", (project,))
                    db.execute("UPDATE tasks SET brief_id=NULL WHERE project_id=?", (project,))
        return {"changed": changed, "discovered": discovered,
                "pending": len(state["items"]), "deferred": False}

    @locked
    def finish(self, project, checked, results, report, checker, report_text=None, versions=None):
        """Record a finished check. checked: {path: sha256 it was given}; results:
        {path: {"verdict": "pass"|"fail", "findings": text}}. Returns what passed and failed.
        report_text is queued for GitHub in the same step, so no push can carry the
        markers' removal without it."""
        state = self.state(project)
        if report_text is not None:
            state.setdefault("unpushed_extra", {})[report] = report_text
        passed, failed, left = [], [], []
        for path, sha in checked.items():
            item = state["items"].get(path)
            result = results.get(path)
            if item is None:
                continue
            if item.get("needs_recheck"):
                item.update(state="pending", note="check again: evidence changed during the previous check")
                left.append(path)
            elif item.get("evidence_unavailable"):
                item.update(state="pending", note="check again: the local file is missing or unreadable")
                left.append(path)
            elif item.get("sha256") not in (None, sha):
                item.update(state="pending", note="check again: the file changed after it was given to the checker")
                left.append(path)
            elif result and result["verdict"] == "pass" and path in state.get("conflicts", []):
                # GitHub has another version of it (changed there); that one isn't checked.
                item.update(state="pending", note=f"this copy passed (see {report}), but GitHub has a different "
                            "version someone changed there; reconcile the two, then check again")
                left.append(path)
            elif not result:
                item.update(state="interrupted", note=f"the checker didn't report on it (see {report}); run it again")
                left.append(path)
            elif result["verdict"] == "pass":
                del state["items"][path]
                # Its markers are removed with the next writes (here and on GitHub), and only
                # those: a marker someone adds for this file later is a new one and stays.
                for key in ("clear_local", "clear_remote"):
                    state[key] = list(dict.fromkeys(state.get(key, []) + [path]))[-2000:]
                if (versions or {}).get(path):
                    # Its markers go from GitHub only while GitHub has this version (or gets it in
                    # the same push): a version someone changed there meanwhile isn't checked.
                    state.setdefault("clear_versions", {})[path] = {"blob": versions[path], "item": item}
                state["checked"].insert(0, {"path": path, "sha256": sha, "report": report, "checker": checker,
                                            "writer": item.get("writer"), "outside": bool(item.get("outside")),
                                            "at": time.time()})
                passed.append(path)
            else:
                findings = " ".join(str(result.get("findings") or "no reason given").split())[:300]
                item.update(state="failed", note=f"check failed (see {report}); fix it, then check again",
                            findings=findings)
                failed.append(path)
        del state["checked"][HISTORY:]
        self.save(project, state)
        return {"passed": passed, "failed": failed, "left": left}

    @locked
    def adopt(self, project, rows, known=()):
        """Rows of the repository's CHECKS_STATUS.md written outside HA become pending
        items too, so HA checks them and never treats them as finished."""
        state = self.state(project)
        ours = set(state["items"]) | set(known)
        added = 0
        for row in rows:
            item = row["item"].strip().strip("`").strip()
            if not safe_path(item) or item in ours or managed(item):
                continue
            state["items"][item] = {
                "path": item, "folder": folder_of(item),
                "writer": "outside", "writer_provider": None, "sha256": None, "since": time.time(),
                "state": "pending", "note": row["waiting"] or "independent check", "outside": True,
            }
            added += 1
        if added:
            self.save(project, state)
        return added

    def gate(self, project, what="this"):
        """Refuse to treat work as published while anything waits for a check."""
        items = self.pending(project)
        if items:
            names = ", ".join(i["path"] for i in items[:5]) + (f" and {len(items) - 5} more" if len(items) > 5 else "")
            raise Blocked(f"{len(items)} file{'s' if len(items) != 1 else ''} still wait{'s' if len(items) == 1 else ''} "
                          f"for an independent check ({names}); {what} waits until they pass.")

    # ------------------------------------------------------------ marker files
    def line(self, item):
        return f"{MARK} {PurePosixPath(item['path']).name} — {item['note']}"

    def status_text(self, existing, folder, items, known):
        """STATUS.md for one folder: HA's lines for its own items; lines anyone else
        wrote stay. None when nothing is left (the file is removed)."""
        names = {PurePosixPath(p).name for p in known if folder_of(p) == folder}
        kept = []
        for line in (existing or "").splitlines():
            if line.startswith(MARK):
                name = line[len(MARK):].strip().split(" — ", 1)[0].strip()
                if name in names:
                    continue  # HA's own line: rewritten below, or gone because it passed.
            kept.append(line)
        while kept and not kept[-1].strip():
            kept.pop()
        ours = [self.line(i) for i in sorted(items, key=lambda i: i["path"]) if not i.get("outside")]
        lines = kept + ours
        if not any(line.strip() for line in lines):
            return None
        return "\n".join(lines) + "\n"

    def ledger_text(self, items, existing_rows=()):
        rows = []
        ours = {i["path"] for i in items}
        for item in sorted(items, key=lambda i: i["path"]):
            waiting = item["note"]
            if item.get("writer") and item["writer"] != "outside":
                waiting += f" (written by {self.name(item['writer'])})"
            rows.append(f"| {cell(item['path'])} | {cell(item['folder'] or '(top)')} | {cell(waiting)} |")
        for row in existing_rows:
            if row["item"].strip("`") not in ours and not row.get("ours"):
                rows.append(f"| {cell(row['item'])} | {cell(row['folder'])} | {cell(row['waiting'])} |")
        if not rows:
            return LEDGER_HEAD.split("\n\n| Item")[0] + "\n\nNothing is waiting for a check.\n"
        return LEDGER_HEAD + "\n" + "\n".join(rows) + "\n"

    def queue_text(self, existing, project):
        items = self.pending(project)
        tasks = self.store.rows(
            "SELECT objective,status FROM tasks WHERE project_id=? AND status NOT IN ('accepted','cancelled') ORDER BY rowid",
            (project,),
        )
        lines = ["## Next up", "", "1. Pending checks (see CHECKS_STATUS.md):"]
        lines += [f"   - {i['path']}: {i['note']}" for i in items[:50]] or ["   - none"]
        if len(items) > 50:
            lines.append(f"   - and {len(items) - 50} more")
        lines += ["2. Then new work:"]
        lines += [f"   - {' '.join(t['objective'].split())[:200]} ({t['status'].replace('_', ' ')})" for t in tasks[:30]] or ["   - none queued"]
        body = "\n".join(lines)
        text = existing if existing else "# Queue\n\n"
        return section(text, QUEUE_START, QUEUE_END, body)

    def files(self, project, read, remote=False, clear=None, used=None, keep=()):
        """The marker and instruction files as they should now be: {path: text or None
        (remove it)}. read(path) gives the current text (from the folder or from GitHub).
        clear: files whose markers a passed check removes now (default: all waiting)."""
        state = self.state(project)
        items = list(state["items"].values())
        if clear is None:
            # Taken with the items, from one reading of the state; keep: removals to hold back.
            clear = set(state.get("clear_remote" if remote else "clear_local", [])) - set(keep)
        if used is not None:
            used.update(clear)
        ledger = read(LEDGER)
        if remote and ledger:
            if self.adopt(project, parse_ledger(ledger), set(clear) | set(keep)):  # Held back: still HA's.
                state = self.state(project)
                items = list(state["items"].values())
        out = {}
        # Lines HA manages: its own pending items, and those whose check just passed.
        # Anyone else's lines and rows stay as written, even for a file HA checked before.
        known = {i["path"] for i in items if not i.get("outside")} | set(clear)
        folders = {i["folder"] for i in items} | set(state["remote_folders" if remote else "folders"])
        for folder in sorted(folders):
            path = f"{folder}/{STATUS}" if folder else STATUS
            existing = read(path)
            text = self.status_text(existing, folder, [i for i in items if i["folder"] == folder], known)
            if text != existing:
                out[path] = text
        rows = [r for r in parse_ledger(ledger) if r["item"].strip("`") not in known]
        text = self.ledger_text(items, rows)
        if text != ledger:
            out[LEDGER] = text
        existing = read(QUEUE)
        text = self.queue_text(existing, project)
        if text != existing:
            out[QUEUE] = text
        for name, body in ((AGENTS, RULES), (CLAUDE, POINTER)):
            existing = read(name)
            text = section(existing, START, END, body)
            if text != existing:
                out[name] = text
        return out

    @locked
    def synced(self, project, cleared=()):
        """The marker files were written here: remember where HA's STATUS.md lines are."""
        state = self.state(project)
        state["folders"] = sorted({i["folder"] for i in state["items"].values()})
        state["clear_local"] = [p for p in state.get("clear_local", []) if p not in set(cleared)]
        self.save(project, state)

    @locked
    def write_local(self, project, root, extra=None):
        """Write the marker files (and a check report) into the project's folder."""
        def read(path):
            p = scoped(root, path)
            return p.read_text("utf-8") if p.is_file() else None

        clear = set(self.state(project).get("clear_local", []))
        changes = self.files(project, read, clear=clear)
        changes.update(extra or {})
        for path, text in changes.items():
            p = scoped(root, path)
            if text is None:
                if p.is_file():
                    p.unlink()  # A STATUS.md HA emptied: nothing in that folder waits any more.
            else:
                atomic_write(p, text.encode("utf-8"))
        self.synced(project, clear)
        return changes


class Drafts:
    """Pushes each file an assistant writes at once, with its markers; keeps the
    markers in the project's folder in step; retries what couldn't be pushed."""

    def __init__(self, store, publications, workspace, providers=None):
        self.store = store
        self.publications = publications
        self.workspace = workspace  # project id -> the project's folder
        self.checks = Checks(store, providers)

    def after_write(self, task, path, writer, sha256, before=None):
        project = self.store.task(task)["project_id"]
        if self.checks.mark(project, path, writer, sha256, before) is None:
            return None
        return self.sync(project, changed=[path],
                         message=f"{path}: written by {self.checks.name(writer)}, checks pending")

    def reconcile(self, project):
        result = self.checks.reconcile_local(project, self.workspace(project))
        if result.get("discovered"):
            # Publish reopened markers immediately; do not automatically publish external file edits.
            self.sync(project, message="Reconcile saved checks with current workspace evidence")
        return result

    def report_text(self, path, text):
        """A check report as it may go to GitHub: if it quotes private reference text or
        something like a key, GitHub gets a short version; the full one stays here."""
        try:
            self.publications._safe_text(path, text.encode("utf-8"))
            return text
        except Exception:
            # Nothing of the original: its title, file names or note may be what was refused.
            return ("# Check report\n\nThis report is kept only in the project's folder on the owner's computer, "
                    "under the same name: it quotes something HA doesn't send to GitHub (private reference "
                    "material, or text that looks like a password or key).\n")

    def sync(self, project, changed=(), extra=None, message=None):
        """Write the markers locally, then push the changed files, anything that
        couldn't be pushed before, check reports not yet on GitHub and the markers in
        one commit. The state lock is held only for local work, never while GitHub is
        called."""
        root = self.workspace(project)
        self.checks.write_local(project, root, extra)
        if extra:
            # Queued first: a report always goes up with (or before) its markers' removal.
            def queue(state):
                state.setdefault("unpushed_extra", {}).update(extra)
            self.checks.update(project, queue)
        state = self.checks.state(project)
        waiting = list(dict.fromkeys(list(state.get("unpushed", [])) + list(changed)))
        if not self.publications:
            self.checks.update(project, lambda state: state.update(clear_remote=[], unpushed_extra={}))
            return {"status": "local"}
        skipped = {}
        texts = {}
        for path in waiting:
            p = scoped(root, path)
            try:
                if p.is_file():
                    texts[path] = p.read_bytes().decode("utf-8")  # Line endings as they are.
            except UnicodeDecodeError:
                # Never sent as a removal: GitHub's copy, if any, stays as it is.
                skipped[path] = "not a text file"
        reports = {path: self.report_text(path, text) for path, text in state.get("unpushed_extra", {}).items()}
        clear = set()  # The removals this push carries, taken with the items they belong to.

        def build(read):
            # A passed file keeps its markers on GitHub unless GitHub has the version that
            # passed, or gets it in this push over a copy nobody else changed. A version
            # someone changed there meanwhile waits for its own check.
            current = self.checks.state(project)
            versions = current.get("clear_versions", {})
            before = current.get("before", {})
            moved, unsure = {}, set()
            for path, version in versions.items():
                try:
                    remote = read(path)
                except Exception as error:
                    sha = getattr(error, "sha", None)
                    if sha == version["blob"]:
                        continue  # A large file, but exactly the version that passed.
                    if sha and path in texts and blob_sha(texts[path]) == version["blob"] and (
                            sha == current["blobs"].get(path)):
                        continue  # HA's own older copy, replaced by the passed version in this push.
                    if sha:
                        moved[path] = version  # A different large file there now: it needs its own check.
                    else:
                        unsure.add(path)  # A folder, or no answer: decide on a later push.
                    continue
                if remote is None:
                    if path in texts and blob_sha(texts[path]) != version["blob"]:
                        unsure.add(path)
                    continue  # Not on GitHub: nothing unchecked there.
                rb = blob_sha(remote)
                if rb == version["blob"]:
                    continue
                ours = path in texts and blob_sha(texts[path]) == version["blob"] and (
                    rb == current["blobs"].get(path)
                    or hashlib.sha256(remote.encode("utf-8")).hexdigest() == before.get(path))
                if not ours:
                    moved[path] = version
            if moved:
                def again(state):
                    for path, version in moved.items():
                        state.get("clear_versions", {}).pop(path, None)
                        state["clear_remote"] = [p for p in state.get("clear_remote", []) if p != path]
                        if path not in state["items"]:
                            state["items"][path] = {
                                **version["item"], "state": "pending", "sha256": None, "outside": True,
                                "writer": "outside", "note": "someone changed it on GitHub before its check "
                                "finished; the version there needs its own check"}
                self.checks.update(project, again)
            files = dict(texts)
            files.update(self.checks.files(project, read, remote=True, used=clear, keep=unsure))
            files.update(reports)
            return files

        def keep(state, status, **push):
            state["unpushed"] = list(dict.fromkeys(state.get("unpushed", []) + waiting))[-2000:]
            state["push"] = {"state": status, "at": time.time(), **push}

        try:
            result = self.publications.push_files(
                project, build, message or "Update checks status",
                check_remote={p: state.get("before", {}).get(p) for p in texts},
                blobs=state["blobs"], required=set(reports))
        except Exception as error:  # Saved locally either way; pushed with the next change.
            self.checks.update(project, lambda state: keep(state, "failed", error=str(error)[:300]))
            self.store.event(project, "draft_push_failed", {"project": project, "error": str(error)[:300]})
            return {"status": "failed", "error": str(error), "skipped": skipped}
        if result["status"] == "disabled":
            # Nothing on GitHub to remove markers from; a repository linked later starts clean.
            self.checks.update(project, lambda state: state.update(clear_remote=[]))
        if result["status"] in ("disabled", "refused"):
            self.checks.update(project, lambda state: keep(
                state, "local" if result["status"] == "disabled" else "failed", error=result.get("reason", "")))
            return {**result, "skipped": {**skipped, **result.get("skipped", {})}}
        skipped.update(result.get("skipped", {}))
        conflicts = result.get("conflicts", [])
        pushed = set(result.get("files", []))
        removed = {folder_of(p) for p in result.get("removed", []) if PurePosixPath(p).name == STATUS}

        def saved(state):
            # Writes that came in meanwhile stay waiting; what went up doesn't. Files the
            # filter keeps off GitHub stay on this computer and say so.
            state["unpushed"] = [p for p in dict.fromkeys(state.get("unpushed", []) + waiting)
                                 if p not in pushed and p not in skipped or p in conflicts]
            state["conflicts"] = sorted((set(state.get("conflicts", [])) - pushed) | set(conflicts))
            local = {**state.get("kept_local", {}), **{p: r for p, r in skipped.items() if p in waiting}}
            state["kept_local"] = {p: r for p, r in local.items() if p not in pushed}
            for path in pushed:
                state.get("before", {}).pop(path, None)
                state.get("unpushed_extra", {}).pop(path, None)
            # A removal is done once the marker files it touches went up (not refused).
            done = {p for p in clear if LEDGER not in skipped
                    and (f"{folder_of(p)}/{STATUS}" if folder_of(p) else STATUS) not in skipped}
            state["clear_remote"] = [p for p in state.get("clear_remote", []) if p not in done]
            for path in done:
                state.get("clear_versions", {}).pop(path, None)
            state["blobs"] = {**state["blobs"], **result.get("blobs", {})}
            # A folder is forgotten only once its STATUS.md is gone from GitHub.
            state["remote_folders"] = sorted(
                (set(state.get("remote_folders", [])) - removed) | {i["folder"] for i in state["items"].values()})
            state["push"] = {"state": "saved" if not conflicts else "conflict", "sha": result.get("sha"),
                             "url": result.get("url"), "at": time.time(), "skipped": skipped, "conflicts": conflicts}
        self.checks.update(project, saved)
        return {**result, "skipped": skipped}

    def _versions(self, project, paths):
        """The Git blob IDs of these files as they are in the project's folder now."""
        out = {}
        for path in paths:
            try:
                if (self.checks.state(project)["items"].get(path) or {}).get("outside") and self.publications:
                    # Written elsewhere: the owner looked at the version on GitHub.
                    text = self.publications.read_text(project, path)
                    if text is not None:
                        out[path] = blob_sha(text)
                    continue
                out[path] = blob_sha(scoped(self.workspace(project), path).read_bytes().decode("utf-8"))
            except Exception:
                continue
        return out

    def owner_checked(self, project, paths, note=""):
        """The owner checked these files by hand (for what an assistant can't check)."""
        from datetime import datetime, timezone

        items = {i["path"]: i for i in self.checks.pending(project) if i["path"] in paths}
        if not items:
            return {"passed": [], "failed": [], "left": []}
        when = datetime.now(timezone.utc)
        key = hashlib.sha256(json.dumps([sorted(items), time.time_ns()]).encode()).hexdigest()[:8]
        name = f"{REPORTS}/{when.strftime('%Y-%m-%d-%H%M%S')}-owner-{key}.md"
        lines = [f"# Checked by the owner, {when.strftime('%Y-%m-%d %H:%M UTC')}", "",
                 "The owner checked these files by hand in HA.", "", "| File | SHA-256 |", "| --- | --- |"]
        lines += [f"| {cell(p)} | {(i.get('sha256') or 'as on GitHub')[:16]} |" for p, i in sorted(items.items())]
        lines += ["", "## Note", "", " ".join(str(note or "No note.").split())[:2000], ""]
        outcome = self.checks.finish(project, {p: i.get("sha256") for p, i in items.items()},
                                     {p: {"verdict": "pass", "findings": "checked by the owner"} for p in items},
                                     name, "owner", report_text="\n".join(lines),
                                     versions=self._versions(project, items))
        self.sync(project, extra={name: "\n".join(lines)},
                  message=f"Checked by the owner: {len(outcome['passed'])} file(s)")
        return {**outcome, "report": name}


def blob_sha(text):
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
