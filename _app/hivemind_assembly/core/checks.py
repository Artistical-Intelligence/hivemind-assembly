"""Push early, check later.

Every file an assistant creates or changes is pushed to the project's repository at
once, before any review, and marked as not yet checked:

- STATUS.md in the file's folder gets a line "CHECKS PENDING: <file> — <what it's
  waiting for>";
- CHECKS_STATUS.md at the top of the repository gets a row (item, folder, waiting for).

No marker means checked. A check is done by a different assistant session than the
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

from .common import Blocked, atomic_write, scoped

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
   (item, folder, waiting for). No marker means checked.
3. A check is done by a different assistant session than the one that wrote the file (another
   provider when possible, otherwise a fresh conversation). The checker gets only the files and
   their sources, and writes a report under checks/ that stays in the repository.
4. When a check passes, remove its STATUS.md line (and STATUS.md once it's empty) and its
   CHECKS_STATUS.md row in the same commit as the report. When a check fails or stops early,
   keep the marker and say in STATUS.md what failed or what is left.
5. Never put anything with a pending marker into a release, the main deliverable or any other
   published output.
6. When you pick up this repository, read CHECKS_STATUS.md and QUEUE.md first: finish pending
   checks, then start new work."""

POINTER = "Read AGENTS.md first: it has this repository's rules, including push early, check later."

LEDGER_HEAD = """# Checks status

Files pushed before an independent check. No row here (and no STATUS.md line in the
file's folder) means checked. Reports of finished checks are in checks/.

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

    def save(self, project, state):
        with self.store.tx() as db:
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
    def mark(self, project, path, writer, sha256):
        """An assistant created or changed this file: it waits for an independent check."""
        if managed(path):
            return None
        state = self.state(project)
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
    def finish(self, project, checked, results, report, checker):
        """Record a finished check. checked: {path: sha256 it was given}; results:
        {path: {"verdict": "pass"|"fail", "findings": text}}. Returns what passed and failed."""
        state = self.state(project)
        passed, failed, left = [], [], []
        for path, sha in checked.items():
            item = state["items"].get(path)
            result = results.get(path)
            if item is None:
                continue
            if item.get("sha256") != sha:
                item.update(state="pending", note="check again: the file changed after it was given to the checker")
                left.append(path)
            elif not result:
                item.update(state="interrupted", note=f"the checker didn't report on it (see {report}); run it again")
                left.append(path)
            elif result["verdict"] == "pass":
                del state["items"][path]
                state["checked"].insert(0, {"path": path, "sha256": sha, "report": report, "checker": checker,
                                            "writer": item.get("writer"), "at": time.time()})
                passed.append(path)
            else:
                findings = " ".join(str(result.get("findings") or "no reason given").split())[:300]
                item.update(state="failed", note=f"check failed: {findings} (see {report}); fix it, then check again")
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
            item = row["item"].strip("`")
            if not item or item in ours or managed(item):
                continue
            state["items"][item] = {
                "path": item, "folder": row["folder"] if row["folder"] not in ("(top)", "") else folder_of(item),
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

    def files(self, project, read, remote=False):
        """The marker and instruction files as they should now be: {path: text or None
        (remove it)}. read(path) gives the current text (from the folder or from GitHub)."""
        state = self.state(project)
        items = list(state["items"].values())
        ledger = read(LEDGER)
        if remote and ledger:
            known = {i["path"] for i in items} | {c["path"] for c in state["checked"]}
            if self.adopt(project, parse_ledger(ledger), known):
                state = self.state(project)
                items = list(state["items"].values())
        out = {}
        known = {i["path"] for i in items} | {c["path"] for c in state["checked"]}
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
    def synced(self, project, remote=False):
        """The marker files were written: remember where HA's STATUS.md lines are."""
        state = self.state(project)
        state["remote_folders" if remote else "folders"] = sorted({i["folder"] for i in state["items"].values()})
        self.save(project, state)

    @locked
    def write_local(self, project, root, extra=None):
        """Write the marker files (and a check report) into the project's folder."""
        def read(path):
            p = scoped(root, path)
            return p.read_text("utf-8") if p.is_file() else None

        changes = self.files(project, read)
        changes.update(extra or {})
        for path, text in changes.items():
            p = scoped(root, path)
            if text is None:
                if p.is_file():
                    p.unlink()  # A STATUS.md HA emptied: nothing in that folder waits any more.
            else:
                atomic_write(p, text.encode("utf-8"))
        self.synced(project)
        return changes


class Drafts:
    """Pushes each file an assistant writes at once, with its markers; keeps the
    markers in the project's folder in step; retries what couldn't be pushed."""

    def __init__(self, store, publications, workspace, providers=None):
        self.store = store
        self.publications = publications
        self.workspace = workspace  # project id -> the project's folder
        self.checks = Checks(store, providers)

    @locked
    def after_write(self, task, path, writer, sha256):
        project = self.store.task(task)["project_id"]
        if self.checks.mark(project, path, writer, sha256) is None:
            return None
        return self.sync(project, changed=[path],
                         message=f"{path}: written by {self.checks.name(writer)}, checks pending")

    @locked
    def sync(self, project, changed=(), extra=None, message=None):
        """Write the markers locally, then push the changed files, anything that
        couldn't be pushed before, and the markers in one commit."""
        root = self.workspace(project)
        self.checks.write_local(project, root, extra)
        state = self.checks.state(project)
        waiting = list(dict.fromkeys(list(state.get("unpushed", [])) + list(changed)))
        if not self.publications:
            return {"status": "local"}

        def build(read):
            files = {}
            for path in waiting:
                p = scoped(root, path)
                try:
                    files[path] = p.read_text("utf-8") if p.is_file() else None
                except UnicodeDecodeError:
                    files[path] = None
                    skipped[path] = "not a text file; it stays on this computer"
            files.update(self.checks.files(project, read, remote=True))
            files.update(extra or {})
            return files

        skipped = {}
        try:
            result = self.publications.push_files(
                project, build, message or "Update checks status", check_remote=set(waiting),
                blobs=self.checks.state(project)["blobs"])
        except Exception as error:  # Saved locally either way; pushed on the next change.
            state = self.checks.state(project)
            state["unpushed"] = waiting[-2000:]
            state["push"] = {"state": "failed", "error": str(error)[:300], "at": time.time()}
            self.checks.save(project, state)
            self.store.event(project, "draft_push_failed", {"project": project, "error": str(error)[:300]})
            return {"status": "failed", "error": str(error)}
        state = self.checks.state(project)
        if result["status"] == "disabled":
            state["unpushed"] = waiting[-2000:]
            state["push"] = {"state": "local", "at": time.time()}
            self.checks.save(project, state)
            return result
        skipped.update(result.get("skipped", {}))
        conflicts = result.get("conflicts", [])
        state["unpushed"] = [p for p in waiting if p in conflicts]
        state["blobs"] = result.get("blobs", state["blobs"])
        state["remote_folders"] = sorted({i["folder"] for i in state["items"].values()})
        state["push"] = {"state": "saved" if not conflicts else "conflict", "sha": result.get("sha"),
                         "url": result.get("url"), "at": time.time(), "skipped": skipped, "conflicts": conflicts}
        self.checks.save(project, state)
        return result


def blob_sha(text):
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
