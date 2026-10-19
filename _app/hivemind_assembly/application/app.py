from __future__ import annotations
import asyncio, json, os, secrets, shutil, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from hivemind_assembly import __version__
from hivemind_assembly.paths import APP_ROOT
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.core.common import (
    canonical,
    atomic_write,
    uid,
    ContractError,
    Blocked,
    scoped,
    file_hash,
    InstanceLock,
)
from hivemind_assembly.core.store import Store
from hivemind_assembly.core.controller import Controller
from hivemind_assembly.core.broker import Broker
from hivemind_assembly.core.acceptance import Acceptance
from hivemind_assembly.learning.engine import Learning
from hivemind_assembly.automation.native import NativeBrowser
from hivemind_assembly.automation.team import NativeTeam
from hivemind_assembly.automation.policy import validate_config
from hivemind_assembly.learning.knowledge import Knowledge
from hivemind_assembly.domains.reverse_engineering.semantics import (
    smoke_cases,
    differential,
)
from hivemind_assembly.domains.reverse_engineering.proof import prove

STATIC = Path(__file__).parent / "static"
DEFAULT = APP_ROOT / "config" / "default.json"


def data_home():
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "UnifiedWorkbench"
        )
    return Path.home() / ".local" / "share" / "unified-workbench"


class Application:
    def __init__(self, root):
        self.instance_lock = InstanceLock(root)
        self.store = Store(root)
        self.config_path = Path(root) / "settings.json"
        if not self.config_path.exists():
            default_config = json.loads(DEFAULT.read_text())
            if os.name == "nt":
                edge = (
                    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
                    / "Microsoft/Edge/Application/msedge.exe"
                )
                chrome = (
                    Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                    / "Google/Chrome/Application/chrome.exe"
                )
                if edge.exists():
                    default_config["browser"]["channel"] = "msedge"
                elif chrome.exists():
                    default_config["browser"]["channel"] = "chrome"
            atomic_write(self.config_path, canonical(default_config))
        self.config = validate_config(json.loads(self.config_path.read_text()))
        self.controller = Controller(self.store)
        self.controller.recover()
        self.broker = Broker(
            self.controller, self.config, domain=ReverseEngineeringDomain()
        )
        recovery = self.broker.recover_pending()
        if recovery:
            self.store.put("startup_recovery", uid("startup"), {"operations": recovery})
        self.token = secrets.token_urlsafe(32)
        self.loop = asyncio.new_event_loop()
        self.browser = NativeBrowser(self.config, root, self.controller)
        self.team = NativeTeam(self.controller, self.broker, self.browser, self.config)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.background = {}
        self.shutdown = False
        self.learning_lock = threading.Lock()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.runner = self.loop.create_task(self.team.run())
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def status(self):
        return {
            "version": __version__,
            "application": "Hivemind Assembly",
            "domain": self.broker.domain.id,
            "projects": self.store.rows("SELECT * FROM projects ORDER BY created DESC"),
            "tasks": self.store.rows("SELECT * FROM tasks ORDER BY updated DESC"),
            "events": self.store.rows(
                "SELECT * FROM events ORDER BY seq DESC LIMIT 60"
            ),
            "operations": self.store.rows(
                "SELECT id,task_id,tool,state,updated,result FROM operations ORDER BY updated DESC LIMIT 50"
            ),
            "sources": self.store.rows(
                "SELECT id,name,revision,external_allowed,extraction FROM sources"
            ),
            "polls": self.store.rows("SELECT * FROM polls"),
            "retries": self.store.rows("SELECT * FROM retry_schedule"),
            "lessons": self.store.rows(
                "SELECT id,asset_key,version,kind,status FROM lessons"
            ),
            "acceptance": [
                json.loads(r["payload"])
                for r in self.store.rows(
                    "SELECT payload FROM records WHERE kind='acceptance_result' ORDER BY created DESC LIMIT 30"
                )
            ],
            "jobs": self.background,
            "routes": [
                {
                    **{
                        "id": k,
                        **{a: v[a] for a in ("provider", "mode", "model", "effort")},
                    },
                    "bound": bool(v["conversation_url"]),
                    "status": (
                        dict(self.team.observations[k].__dict__)
                        if k in self.team.observations
                        else {"ready": False, "blocked": "Not yet observed"}
                    ),
                }
                for k, v in self.config["routes"].items()
            ],
        }

    def background_job(self, name, fn):
        key = uid("job")
        self.background[key] = {
            "name": name,
            "status": "running",
            "started": time.time(),
        }

        def work():
            try:
                self.background[key].update(status="completed", result=fn())
            except Exception as e:
                self.background[key].update(status="failed", error=str(e))

        threading.Thread(target=work, daemon=True).start()
        return {"job": key}

    def action(self, path, data):
        if path == "/api/project":
            if not data.get("name") or not data.get("objective"):
                raise ContractError("Name and objective are required")
            t = self.store.create_project(
                data["name"][:200],
                data["objective"][:20000],
                paused=bool(data.get("start_paused", False)),
            )
            return t
        if path == "/api/acceptance":
            return Acceptance(self.controller, self.broker).configure(
                data["task"], data["contract"]
            )
        if path == "/api/learning/optimize":
            from hivemind_assembly.domains.reverse_engineering.workflows import (
                optimize_repeated_proofs,
            )

            if not self.learning_lock.acquire(blocking=False):
                raise Blocked("A workflow evaluation is already running")

            def optimize():
                try:
                    return optimize_repeated_proofs(self.store)
                finally:
                    self.learning_lock.release()

            return self.background_job("Evaluate reusable proof workflow", optimize)
        if path == "/api/learning/rollback":
            Learning(self.store).rollback(data["lesson"])
            return {"rolled_back": data["lesson"]}
        if path == "/api/control":
            task = data["task"]
            action = data["action"]
            t = self.store.task(task)
            if action not in ("pause", "resume", "cancel"):
                raise ContractError("Unknown control")
            if t["status"] in ("accepted", "cancelled"):
                raise Blocked("Task is terminal")
            if action in ("pause", "cancel"):
                event = self.broker.cancel.setdefault(task, threading.Event())
                event.set()
                self.controller.checkpoint(task, action)
                if action == "cancel":
                    self.team.usage.release(task)
                self.store.state(task, "paused" if action == "pause" else "cancelled")

                def cancel_turn():
                    if task in self.team.active:
                        self.team.active[task].cancel()

                self.loop.call_soon_threadsafe(cancel_turn)
            else:
                self.broker.cancel.setdefault(task, threading.Event()).clear()
                self.store.state(task, "queued")
            return self.store.task(task)
        if path == "/api/import-target":
            task = data["task"]
            root = self.broker.workspace(task)
            source = Path(data["path"]).expanduser().resolve()
            if not source.is_file():
                raise ContractError("Target file does not exist")
            target = scoped(root, source.name)
            if target.exists() and file_hash(target) != file_hash(source):
                raise Blocked("A different file already has this name")
            # Treat imports as project mutations and retain an immutable original.
            with self.store.tx() as c:
                current = dict(
                    c.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
                )
                if (
                    current["status"] not in ("paused", "queued", "waiting_quota")
                    or current["owner"]
                ):
                    raise Blocked("Import targets before starting the task")
                if not target.exists():
                    shutil.copy2(source, target)
                    c.execute(
                        "UPDATE projects SET revision=revision+1 WHERE id=?",
                        (current["project_id"],),
                    )
            original = self.broker.artifacts.add(
                target.read_bytes(),
                source.name,
                self.store.task(task)["project_id"],
                "protected",
            )
            return {
                "name": source.name,
                "sha256": file_hash(target),
                "original_artifact": original["id"],
            }
        if path == "/api/source":
            return Knowledge(self.store).ingest(
                data["path"], bool(data.get("external_allowed", False))
            )
        if path == "/api/settings":
            if any(not p.done() for p in self.team.active.values()):
                raise Blocked("Pause active tasks before changing route bindings")
            cfg = validate_config(data["config"])
            atomic_write(self.config_path, canonical(cfg))
            self.config.clear()
            self.config.update(cfg)
            self.submit(self.browser.close()).result(timeout=15)
            self.team.observations.clear()
            return {"saved": True}
        if path == "/api/probe":
            route = data["route"]
            return self.background_job(
                "Observe native route",
                lambda: self.submit(self.browser.observe(route)).result(timeout=120),
            )
        if path == "/api/verify":

            def verify():
                results = [differential(c) for c in smoke_cases()]
                result = {
                    "cases": results,
                    "proof": prove("89f801f0", "8d0437"),
                    "negative_proof": prove("89f801f0", "89f829f0"),
                    "passed": all(r["comparison"]["passed"] for r in results),
                }
                result["passed"] = (
                    result["passed"]
                    and result["proof"]["result"] == "UNSAT"
                    and result["negative_proof"]["result"] == "SAT"
                )
                self.store.put("local_verification", uid("verify"), result)
                return result

            return self.background_job("Semantic self-check", verify)
        if path == "/api/backup":
            name = "controller-" + time.strftime("%Y%m%d-%H%M%S") + ".sqlite3"
            path = self.store.root / "backups" / name
            path.parent.mkdir(exist_ok=True)
            self.store.backup(path)
            return {
                "name": name,
                "scope": "Controller metadata only; project/native/artifact data remains in the data directory",
            }
        if path == "/api/reconcile":
            op = self.store.one(
                "SELECT tool FROM operations WHERE id=?", (data["operation"],)
            )
            if op["tool"] == "propose_annotation":
                return self.broker.reconcile_native(data["operation"])
            return self.broker.reconcile_file(data["operation"])
        if path == "/api/setup":
            from hivemind_assembly.application.setup import install_foundations

            return self.background_job(
                "Install pinned foundations",
                lambda: install_foundations(self.store.root, self.config_path),
            )
        raise ContractError("Unknown action")

    def close(self):
        if self.shutdown:
            return
        self.shutdown = True
        for event in self.broker.cancel.values():
            event.set()

        async def close_runtime():
            await self.team.stop()
            self.runner.cancel()
            await asyncio.gather(self.runner, return_exceptions=True)

        self.submit(close_runtime()).result(timeout=20)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.store.close()
        self.instance_lock.close()


def make_server(app, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, content_type="application/json"):
            if not isinstance(data, bytes):
                data = canonical(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def trusted(self):
            host = self.headers.get("Host", "")
            valid = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if host not in valid:
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in valid}:
                return False
            return True

        def authenticated(self):
            return self.headers.get("X-Workbench-Token") == app.token

        def do_GET(self):
            if not self.trusted():
                self.send(403, {"error": "Origin rejected"})
                return
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                if not self.authenticated():
                    self.send(403, {"error": "Local session token required"})
                    return
                if path == "/api/status":
                    status = app.status()
                    for route in status["routes"]:
                        if "windows" in route["status"]:
                            route["status"]["windows"] = [
                                w.__dict__ for w in route["status"]["windows"]
                            ]
                    self.send(200, status)
                elif path == "/api/settings":
                    self.send(200, app.config)
                elif path == "/api/skills":
                    self.send(200, app.team.skill_manifest(True))
                else:
                    self.send(404, {"error": "Not found"})
                return
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            if path not in files:
                self.send(404, {"error": "Not found"})
                return
            filename, kind = files[path]
            data = (STATIC / filename).read_bytes()
            self.send(200, data, kind)

        def do_POST(self):
            if not self.trusted() or not self.authenticated():
                self.send(403, {"error": "Unauthorized local request"})
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 < n <= 2_000_000:
                    raise ContractError("Invalid request size")
                if (
                    self.headers.get("Content-Type", "").split(";")[0]
                    != "application/json"
                ):
                    raise ContractError("JSON required")
                value = json.loads(self.rfile.read(n))
                result = app.action(urlsplit(self.path).path, value)
                self.send(200, result)
            except (ContractError, KeyError, ValueError, FileNotFoundError) as e:
                self.send(400, {"error": str(e)})
            except Exception as e:
                self.send(500, {"error": str(e)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(root=None, port=0, open_browser=True):
    app = Application(root or data_home())
    server = make_server(app, port)
    url = f"http://127.0.0.1:{server.server_port}/#" + app.token
    print(
        "Hivemind Assembly is running on this computer. Close this window to stop.\n"
        + url,
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
