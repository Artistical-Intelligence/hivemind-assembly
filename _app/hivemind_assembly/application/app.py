from __future__ import annotations
import asyncio, json, os, secrets, shutil, threading, time, webbrowser, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote
from hivemind_assembly import __version__
from hivemind_assembly.paths import APP_ROOT
from hivemind_assembly.learning.pipeline import stages as learning_stages
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)
from hivemind_assembly.core.common import (
    Conflict,
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
from hivemind_assembly.core.repositories import Repositories
from hivemind_assembly.core.hosted_tests import HostedTests
from hivemind_assembly.integrations.github import GitHubAuth, GitHubClient
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


def windows_chrome_installed():
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    return any(
        (Path(r) / "Google/Chrome/Application/chrome.exe").exists() for r in roots if r
    )


class Application:
    def __init__(self, root):
        self.instance_lock = InstanceLock(root)
        self.store = Store(root)
        self.config_path = Path(root) / "settings.json"
        if not self.config_path.exists():
            default_config = json.loads(DEFAULT.read_text())
            if os.name == "nt":
                # Chrome when it's installed (the owner's browser); Edge otherwise.
                default_config["browser"]["channel"] = (
                    "chrome" if windows_chrome_installed() else "msedge"
                )
            atomic_write(self.config_path, canonical(default_config))
        saved_config = json.loads(self.config_path.read_text())
        if (
            os.name == "nt"
            and saved_config.get("browser", {}).get("channel") == "msedge"
            and windows_chrome_installed()
        ):
            # Earlier versions picked Edge first; use Chrome once it's installed.
            saved_config["browser"]["channel"] = "chrome"
            atomic_write(self.config_path, canonical(saved_config))
        self.config = validate_config(saved_config)
        self.controller = Controller(self.store)
        self.controller.recover()
        with self.store.tx() as db:
            db.execute("DELETE FROM reservations WHERE task LIKE 'native-budget_%'")
        self.github_auth = GitHubAuth(self.store.root)
        self.github_client = GitHubClient(self.github_auth)
        self.repositories = Repositories(self.store, self.github_client, self.config)
        self.hosted_tests = HostedTests(self.store, self.repositories)
        self.broker = Broker(
            self.controller,
            self.config,
            domain=ReverseEngineeringDomain(),
            repositories=self.repositories,
            hosted_tests=self.hosted_tests,
        )
        from .workspace import Workspace

        self.workspace = Workspace(self.broker)
        from hivemind_assembly.integrations.mcp import Connections, Gateway
        from hivemind_assembly.integrations.codespaces import Codespaces

        self.connections = Connections(self.store)
        from hivemind_assembly.integrations.tunnel import Tunnel

        self.tunnel = Tunnel(self.connections)
        self.mcp_gateway = Gateway(self)
        from hivemind_assembly.integrations.quick_connect import QuickConnection

        def shared():
            cfg = self.connections.settings()
            return bool(cfg["enabled"] and cfg["projects"])

        self.quick = QuickConnection(
            self.store.root, self.mcp_gateway.call, __version__, enabled=shared
        )
        from hivemind_assembly.integrations.permanent import Permanent
        from hivemind_assembly.integrations.quick_connect import Rpc

        self.permanent = Permanent(
            self.store.root, lambda: Rpc(self.mcp_gateway.call, __version__)
        )
        self.mcp_shared = shared
        if self.permanent.enabled() and shared():
            try:
                self.permanent.start()  # a permanent address reconnects on its own
            except Exception:
                pass  # shown as stopped; Start retries
        self.broker.mcp_connections = self.connections
        self.codespaces = Codespaces(self)
        self.broker.codespaces = self.codespaces
        recovery = self.broker.recover_pending()
        if recovery:
            self.store.put("startup_recovery", uid("startup"), {"operations": recovery})
        self.token = secrets.token_urlsafe(32)
        self.loop = asyncio.new_event_loop()
        self.browser = NativeBrowser(self.config, root, self.controller)
        from hivemind_assembly.automation.chrome_relay import ChromeRelay

        self.browser.relay = ChromeRelay()
        self.connections.oauth.open_page = self.browser.service_page
        self.connections.oauth.submit = self.submit
        self.team = NativeTeam(self.controller, self.broker, self.browser, self.config)
        from hivemind_assembly.automation.sessions import Sessions

        self.sessions = Sessions(self.browser, self.config_path)
        self.sessions.restore_bindings()
        self.team.sessions = self.sessions
        self.configure_learning()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.background = {}
        # Owner play-testing has its own cancellation: pausing a task (required
        # before owner edits) stops its workers, not the owner's own game calls.
        self.game_cancel = threading.Event()
        from hivemind_assembly.integrations.github_setup import GitHubSetup

        self.github_setup = GitHubSetup(self.browser, self.github_auth, self.store.root)
        self.github_setup_future = None
        from hivemind_assembly.automation.onboarding import NativeSetup

        from hivemind_assembly.integrations import chrome_helper
        from hivemind_assembly.integrations.auto_reconnect import AutoReconnect

        self.auto_reconnect = AutoReconnect(
            self.quick.folder,
            self.browser,
            lambda provider: chrome_helper.details(self.quick, provider),
            lambda provider, url, flow: chrome_helper.pair(self.quick, provider, url, flow),
            lambda: self.config["routes"],
        )
        # A new address: reconnect the chosen providers from HA's own windows.
        self.quick.on_ready = lambda origin: (
            self.submit(self.auto_reconnect.run_all()) if self.auto_reconnect.providers() else None
        )
        # Like VSC: register the Chrome helper bridge automatically on every start.
        if os.environ.get("HA_SKIP_HELPER_REGISTRATION") != "1":  # tests keep the real profile untouched
            threading.Thread(target=self.register_helper, daemon=True).start()
        self.native_setup = NativeSetup(
            self.browser, self.store, self.config_path, self.sessions, self.team
        )
        self.native_setup_futures = {}
        self.shutdown = False
        self.closed = False
        self.learning_lock = threading.Lock()
        self.action_lock = threading.RLock()
        self.thread.start()
        self.hosted_tests.start_monitor()

    def configure_learning(self):
        self.team.learning_trials = None
        self.native_learning = None
        self.native_learning_error = ""
        try:
            from hivemind_assembly.domains.reverse_engineering.learning_evaluator import (
                FunctionEvaluator,
            )
            from hivemind_assembly.learning.native_rollouts import NativeRollouts

            evaluator = FunctionEvaluator(
                self.broker.jobs,
                self.config["foundations"].get("c_compiler", ""),
                allow_native=lambda: self.team.experimental.settings()[
                    "allow_native_benchmarks"
                ],
            )
            self.native_learning = NativeRollouts(
                self.store,
                self.controller,
                self.sessions,
                self.team.observations.get,
                evaluator,
                evaluator.fingerprint,
                budget=self.team.learning_budget,
                policy=self.team.experimental,
            )
            self.team.learning_trials = self.native_learning
            with self.store.tx() as db:
                db.execute(
                    "INSERT INTO meta VALUES('native_learning_engine',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (evaluator.fingerprint,),
                )
        except Blocked as error:
            self.native_learning_error = str(error)
            with self.store.tx() as db:
                db.execute(
                    "INSERT INTO meta VALUES('native_learning_engine','unavailable') ON CONFLICT(key) DO UPDATE SET value='unavailable'"
                )

    def _run(self):
        asyncio.set_event_loop(self.loop)
        for route in self.config["routes"]:
            if self.native_setup.status(route)["stage"] in (
                "authentication",
                "binding_required",
                "allowance_mapping",
                "waiting_quota",
                "waiting_delivery",
            ):
                self.native_setup_futures[route] = self.loop.create_task(
                    self.native_setup.run(route)
                )
        self.runner = self.loop.create_task(self.team.run())
        self.loop.run_forever()

    def register_helper(self):
        """Let Chrome start HA's helper bridge (current user only). Runs at every start."""
        from hivemind_assembly.integrations import chrome_helper

        try:
            self.helper_registration = chrome_helper.register_native_host(self.store.root)
        except Exception as exc:
            self.helper_registration = {"error": str(exc) or type(exc).__name__}
        return self.helper_registration

    def helper_status(self):
        from hivemind_assembly.integrations.chrome_helper import EXTENSION_DIR

        seen = getattr(self, "helper_seen", None)
        registration = getattr(self, "helper_registration", None) or {}
        return {
            "folder": str(EXTENSION_DIR),
            "registered": bool(registration.get("registered")),
            "error": registration.get("error"),
            "last_seen": seen,
            "connected": bool(seen and time.time() - seen < 15),
        }

    def connection(self):
        """The browser connection in use: the permanent address once set up, else the temporary one."""
        return self.permanent if self.permanent.enabled() else self.quick

    def browser_connection_status(self):
        from hivemind_assembly.integrations.quick_connect import PROVIDERS

        permanent = self.permanent.enabled()
        status = {"download": None, "address_changed": False, **self.connection().status()}
        return {
            **status,
            "providers": PROVIDERS,
            "mode": "permanent" if permanent else "temporary",
            "permanent": {"origin": self.permanent.settings().get("origin", "")},
            "auto": self.auto_reconnect.status(),
        }

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def status(self):
        return {
            "version": __version__,
            "application": "Hivemind Assembly",
            "domain": self.broker.domain.id,
            "github": {**self.github_auth.status(), **self.config.get("github", {})},
            "hosted_tests": self.hosted_tests.listing(),
            "connections": self.connections.settings(),
            "mcp_authorizations": self.connections.oauth.status(),
            "tunnel": self.tunnel.status(),
            "quick_connect": self.browser_connection_status(),
            "chrome_helper": self.helper_status(),
            "codespaces": {
                "settings": self.codespaces.settings(),
                "jobs": self.codespaces.jobs(),
                "creations": self.codespaces.creations(),
            },
            "native_evaluations": (
                [
                    self.native_learning.status(r["id"])
                    for r in self.store.rows(
                        "SELECT id FROM records WHERE kind='native_evaluation'"
                    )
                ]
                if self.native_learning
                else []
            ),
            "native_learning_error": self.native_learning_error,
            "learning_pipeline": learning_stages(
                self.store, self.team.experimental.settings(), self.native_learning
            ),
            "github_setup": self.github_setup.status(),
            "repositories": [
                self.repositories.status(p["id"])
                for p in self.store.rows("SELECT id FROM projects")
            ],
            "projects": self.store.rows("SELECT * FROM projects ORDER BY created DESC"),
            "goals": [
                self.team.goals.status(row["task_id"])
                for row in self.store.rows("SELECT task_id FROM goals")
            ],
            "tasks": self.store.rows("SELECT * FROM tasks ORDER BY updated DESC"),
            "configured_tasks": [
                row["id"]
                for row in self.store.rows(
                    "SELECT id FROM records WHERE kind='acceptance_contract'"
                )
            ],
            "events": self.store.rows(
                "SELECT * FROM events ORDER BY seq DESC LIMIT 60"
            ),
            "operations": self.store.rows(
                "SELECT id,task_id,tool,state,updated,result FROM operations ORDER BY updated DESC LIMIT 50"
            ),
            "experimental_learning": self.team.experimental.settings(),
            "experimental_models": [
                {"evaluation": row["id"], **json.loads(row["payload"])}
                for row in self.store.rows(
                    "SELECT id,payload FROM records WHERE kind='native_evaluation_model'"
                )
            ],
            "knowledge_curations": [
                {"id": row["id"], **self.team.curation.status(row["id"])}
                for row in self.store.rows(
                    "SELECT id FROM records WHERE kind='knowledge_curation'"
                )
            ],
            "knowledge_catalog": self.team.scopes.catalog(),
            "knowledge_scopes": [
                self.team.scopes.status(row["id"])
                for row in self.store.rows("SELECT id FROM tasks")
            ],
            "knowledge_assignments": self.store.rows(
                "SELECT * FROM knowledge_assignments ORDER BY kind,item_id"
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
                    "SELECT payload FROM records WHERE kind='acceptance_result' ORDER BY rowid DESC LIMIT 30"
                )
            ],
            "jobs": self.jobs_view(),
            "foundations": self.foundations_status(),
            "assistant_browser": {
                "mode": "your_chrome" if self.browser.your_chrome() else "own_windows",
                "extension_connected": self.browser.relay.connected(),
            },
            "routes": [
                {
                    **{
                        "id": k,
                        **{a: v[a] for a in ("provider", "mode", "model", "effort")},
                    },
                    "bound": bool(v["conversation_url"]),
                    "out_of_usage": self.team.exhausted(k),
                    "setup": {
                        **self.native_setup.progress(k),
                        "running": bool(
                            self.native_setup_futures.get(k) is not None
                            and not self.native_setup_futures[k].done()
                        ),
                    },
                    "status": (
                        dict(self.team.observations[k].__dict__)
                        if k in self.team.observations
                        else {"ready": False, "blocked": "Not yet observed"}
                    ),
                }
                for k, v in self.config["routes"].items()
            ],
        }

    def foundations_status(self):
        """Whether the pinned foundations are configured on disk, for first-run setup."""
        configured = self.config.get("foundations", {})
        present = {
            name: bool(configured.get(name)) and Path(configured[name]).exists()
            for name in ("ghidra_home", "rea_home", "hermes_home")
        }
        installing = any(
            job["name"] == "Install pinned foundations" and job["status"] == "running"
            for job in self.background.values()
        )
        installed_now = any(
            job["name"] == "Install pinned foundations" and job["status"] == "completed"
            for job in self.background.values()
        )
        progress = next(
            (
                job.get("progress")
                for job in self.background.values()
                if job["name"] == "Install pinned foundations" and job["status"] == "running"
            ),
            None,
        )
        return {
            "ready": all(present.values()),
            "present": present,
            "installing": installing,
            "restart_needed": installed_now and not all(present.values()),
            "progress": progress,
        }

    def jobs_view(self):
        """Background jobs for the 4-second status poll, without frame payloads."""
        view = {}
        for key, job in list(self.background.items()):
            item = dict(job)
            result = item.get("result")
            if isinstance(result, dict) and "frames" in result:
                item["result"] = {k: v for k, v in result.items() if k != "frames"} | {
                    "frame_count": len(result["frames"])
                }
            view[key] = item
        return view

    def background_job(self, name, fn, progress=False):
        finished = [k for k, j in self.background.items() if j["status"] != "running"]
        for old in finished[: max(0, len(finished) - 40)]:
            # Keep recent results; older finished jobs would only grow every poll.
            self.background.pop(old, None)
        key = uid("job")
        self.background[key] = {
            "name": name,
            "status": "running",
            "started": time.time(),
        }

        def publish(state):
            self.background[key]["progress"] = state

        def work():
            try:
                result = fn(publish) if progress else fn()
                self.background[key].pop("progress", None)
                self.background[key].update(status="completed", result=result)
            except Exception as e:
                self.background[key].update(status="failed", error=str(e))

        threading.Thread(target=work, daemon=True).start()
        return {"job": key}

    def action(self, path, data):
        if path in ("/api/game/describe", "/api/game/play", "/api/jobs/result"):
            # Read-only: emulation can take seconds and must not hold the lock
            # that pause, cancel and every other owner action wait for.
            return self._action(path, data)
        with self.action_lock:
            return self._action(path, data)

    def _action(self, path, data):
        if path == "/api/learning/settings":
            from hivemind_assembly.learning.policy import validate as validate_learning

            settings = validate_learning(data)
            self.config["experimental_learning"] = settings
            atomic_write(self.config_path, canonical(self.config))
            return settings
        if path == "/api/knowledge/curate":
            return self.team.curation.queue(data["kind"], data["id"])
        if path in (
            "/api/knowledge/tag",
            "/api/knowledge/assign",
            "/api/knowledge/scope",
        ):
            if any(not p.done() for p in self.team.active.values()):
                raise Blocked("Pause active tasks before changing knowledge access")
            if path.endswith("/tag"):
                self.team.scopes.create_tag(
                    data["id"], data["label"], data.get("description", "")
                )
                return self.team.scopes.catalog()
            if path.endswith("/assign"):
                return self.team.scopes.assign(data["kind"], data["id"], data["tags"])
            task = self.store.task(data["task"])
            if task["status"] != "paused":
                raise Blocked("Pause the task before changing its knowledge scope")
            return self.team.scopes.select(
                task["id"],
                data["tags"],
                data["catalog_revision"],
                data.get("reason", "Owner selection"),
            )
        if path == "/api/tunnel/install":
            return self.background_job(
                "Install official MCP tunnel", self.tunnel.install
            )
        if path == "/api/tunnel/configure":
            return self.tunnel.configure(
                data["tunnel_id"], data.get("key") or None, data.get("remember", False)
            )
        if path == "/api/tunnel/doctor":
            return self.background_job("Check private MCP tunnel", self.tunnel.doctor)
        if path == "/api/tunnel/start":
            return self.tunnel.start()
        if path == "/api/tunnel/stop":
            return self.tunnel.stop()
        if path == "/api/tunnel/forget":
            return self.tunnel.forget()
        if path == "/api/quick/start":
            if self.permanent.enabled():
                if not self.mcp_shared():
                    raise Blocked("Turn on HA MCP access and share a project first.")
                self.permanent.start()
            else:
                self.quick.start()
            return self.browser_connection_status()
        if path == "/api/quick/stop":
            self.connection().stop()
            return self.browser_connection_status()
        if path == "/api/quick/pairing":
            return self.connection().pairing()
        if path == "/api/quick/revoke":
            self.connection().revoke()
            return self.browser_connection_status()
        if path == "/api/permanent/setup":
            if not self.mcp_shared():
                raise Blocked("Turn on HA MCP access and share a project first.")
            self.quick.stop()
            self.permanent.deploy(
                data.get("token", ""),
                data.get("account_id", ""),
                data.get("confirmed_free") is True,
            )
            return self.browser_connection_status()
        if path == "/api/permanent/off":
            self.permanent.forget()
            return self.browser_connection_status()
        if path == "/api/quick/auto":
            return self.auto_reconnect.save(data.get("providers"))
        if path == "/api/quick/reconnect":
            if self.quick.status()["state"] != "ready":
                raise Blocked("Start the browser connection first.")
            providers = self.auto_reconnect.providers()
            if not providers:
                raise Blocked("Choose ChatGPT and/or Claude to reconnect automatically first.")
            self.submit(self.auto_reconnect.run_all())
            return self.auto_reconnect.status()
        if path.startswith("/api/helper/") and path not in ("/api/helper/install", "/api/helper/open-extensions", "/api/helper/open-folder"):
            self.helper_seen = time.time()  # the helper in Chrome is reaching HA
        if path in ("/api/helper/open-extensions", "/api/helper/open-folder"):
            from hivemind_assembly.integrations import chrome_helper

            self.register_helper()
            if path == "/api/helper/open-folder":
                try:
                    chrome_helper.open_folder()
                    return {"opened": True}
                except Exception:
                    return {"opened": False}
            try:
                opened = chrome_helper.open_extensions_page()
            except Exception:
                opened = False
            return {"opened": opened, "url": "chrome://extensions"}
        if path in ("/api/helper/status", "/api/helper/details", "/api/helper/pair"):
            from hivemind_assembly.integrations import chrome_helper

            if path == "/api/helper/status":
                status = self.connection().status()
                return {"state": status["state"], "message": status["message"], "services": status["services"]}
            if path == "/api/helper/details":
                return chrome_helper.details(self.connection(), data.get("provider"))
            return chrome_helper.pair(self.connection(), data.get("provider"), data.get("page_url"), data.get("flow"))
        if path == "/api/helper/relay":
            # Asked every few seconds by the helper in the owner's Chrome.
            if not self.browser.your_chrome():
                return {"url": None}
            self.submit(self.browser.relay.start()).result(10)
            return {"url": self.browser.relay.extension_url}
        if path == "/api/browser/mode":
            mode = data.get("mode")
            if mode not in ("your_chrome", "own_windows"):
                raise ContractError("Choose your Chrome or HA's own windows.")
            if any(not p.done() for p in [*self.team.active.values(), *self.team.learning_jobs.values()]):
                raise Blocked("Pause active tasks before changing where the assistants run.")
            browser = self.config.setdefault("browser", {})
            if mode == "your_chrome":
                browser["mode"] = "your_chrome"
            else:
                browser.pop("mode", None)
            saved = json.loads(Path(self.config_path).read_text())
            saved.setdefault("browser", {}).pop("mode", None)
            if mode == "your_chrome":
                saved["browser"]["mode"] = "your_chrome"
            atomic_write(self.config_path, canonical(saved))
            # Open windows or tabs from the other mode are closed; they reopen in the new place.
            self.submit(self.browser.close()).result(30)
            return {"mode": mode, "extension_connected": self.browser.relay.connected()}
        if path == "/api/helper/install":
            from hivemind_assembly.integrations import chrome_helper

            result = chrome_helper.register_native_host(self.store.root)
            result["opened"] = chrome_helper.open_extensions_page() if data.get("open") else False
            return result
        if path == "/api/mcp/local-apps":
            return self.connections.install_local_apps()
        if path == "/api/mcp/settings":
            return self.connections.save(data)
        if path == "/api/mcp/config":
            return self.connections.client_config()
        if path == "/api/mcp/install":
            return self.connections.install_config(data["path"])
        if path == "/api/mcp/call":
            return self.mcp_gateway.call(data["tool"], data.get("arguments", {}))
        if path == "/api/mcp/credential":
            return self.connections.credential(
                data["server"],
                data.get("token"),
                data.get("remember", False),
                data.get("forget", False),
            )
        if path == "/api/mcp/authorize":
            return self.connections.oauth.start(
                data["server"],
                data.get("remember", False),
                data.get("client_id") or None,
                data.get("port", 0),
                data.get("client_metadata_url"),
            )
        if path == "/api/mcp/client-metadata":
            from ..integrations.mcp_oauth import client_metadata_document

            return client_metadata_document(data.get("url"), data.get("port"))
        if path == "/api/mcp/discover":
            return self.background_job(
                "Discover MCP tools",
                lambda: asyncio.run(self.connections.external(data["server"])),
            )
        if path == "/api/codespaces/setup":
            from .prerequisites import install_missing

            return self.background_job(
                "Prepare Codespaces tools", lambda: install_missing(extra=("gh",))
            )
        if path == "/api/codespaces/connect":
            saved = self.github_auth.credentials()
            return self.github_auth.start(saved["client_id"], codespaces=True)
        if path == "/api/codespaces/settings":
            return self.codespaces.save(data)
        if path == "/api/codespaces/list":
            return self.codespaces.listing()
        if path == "/api/codespaces/machines":
            return self.codespaces.machines(data["owner"], data["repo"])
        if path == "/api/codespaces/create":
            return self.codespaces.create(
                data["owner"],
                data["repo"],
                data["machine"],
                data["request_id"],
                data.get("ref"),
            )
        if path == "/api/codespaces/recover-creation":
            return self.codespaces.reconcile_creation(data["request_id"])
        if path == "/api/codespaces/control":
            return self.codespaces.control(data["space"], data["action"])
        if path == "/api/codespaces/probe":
            return self.background_job(
                "Check Codespace capabilities",
                lambda: self.codespaces.probe(data["space"]),
            )
        if path == "/api/codespaces/run":
            return self.codespaces.submit(data)
        if path == "/api/codespaces/reconcile":
            return self.background_job(
                "Reconcile Codespace job", lambda: self.codespaces.reconcile(data["id"])
            )
        if path == "/api/codespaces/cancel":
            return self.codespaces.cancel(data["id"])
        if path == "/api/codespaces/result":
            return self.codespaces.result(data["id"])
        if path == "/api/codespaces/import":
            return self.codespaces.import_output(
                data["id"],
                data["path"],
                data.get("expected_sha"),
                data.get("allow_stale") is True,
            )
        if path == "/api/native/setup-all":
            if any(
                not p.done()
                for p in [*self.team.active.values(), *self.team.learning_jobs.values()]
            ):
                raise Blocked("Pause active tasks before rebinding native sessions")
            for route in self.config["routes"]:
                future = self.native_setup_futures.get(route)
                if future is None or future.done():
                    self.native_setup_futures[route] = self.submit(
                        self.native_setup.run(route)
                    )
            return {"started": True}
        if path == "/api/learning/share":
            result = Learning(self.store).share(data["lesson"], data["allowed"])
            if data["allowed"] and self.team.scopes.tags("lesson", data["lesson"]) == [
                "unclassified"
            ]:
                result["tagging"] = self.team.curation.queue("lesson", data["lesson"])
            return result
        if path == "/api/learning/native-corpus":
            if not self.native_learning:
                raise Blocked(self.native_learning_error)
            suite = (
                self.native_learning.verifier.import_benchmark(
                    self.native_learning,
                    self.store.root / "private" / "benchmarks",
                    data.get("limit"),
                )
                if data.get("benchmark") == "humaneval_decompile"
                else self.native_learning.verifier.protect_manifest(
                    self.native_learning, data["path"]
                )
                if data.get("path")
                else self.native_learning.verifier.build_corpus(
                    self.native_learning,
                    self.store.root
                    / "private"
                    / "evaluation-corpus"
                    / self.native_learning.fingerprint,
                )
            )
            return {"suite": suite}
        if path == "/api/learning/native-resume":
            if not self.native_learning:
                raise Blocked(self.native_learning_error)
            key = data["evaluation"]
            pending = self.team.learning_jobs.get(key)
            if pending and not pending.done():
                raise Blocked("The evaluation is already running")
            return self.native_learning.resume(key)
        if path == "/api/learning/native-evaluate":
            if not self.native_learning:
                raise Blocked(self.native_learning_error)
            key = self.native_learning.bind(
                data["candidate"],
                data["suite"],
                data.get("route") or None,
                data.get("repeats", 3),
            )
            row = self.store.one(
                "SELECT asset_key FROM lessons WHERE id=?", (data["candidate"],)
            )
            self.store.put(
                "native_suite:" + row["asset_key"],
                uid("binding"),
                {
                    "suite": data["suite"],
                    "route": data.get("route") or None,
                    "repeats": data.get("repeats", 3),
                },
            )
            if data.get("default_suite") is True:
                from hivemind_assembly.learning.pipeline import DEFAULT_SUITE

                self.store.put(
                    DEFAULT_SUITE,
                    uid("binding"),
                    {
                        "suite": data["suite"],
                        "route": data.get("route") or None,
                        "repeats": data.get("repeats", 3),
                    },
                )
            self.native_learning.state(key, "queued")
            return {"evaluation": key}
        if path == "/api/native/renew":
            route = data["route"]
            if any(
                not p.done()
                for p in [*self.team.active.values(), *self.team.learning_jobs.values()]
            ):
                raise Blocked(
                    "Native work must reach a safe boundary before explicit renewal"
                )
            observation = self.team.observations.get(route)
            if observation is None or not observation.eligible():
                raise Blocked("Renewal requires verified sufficient allowance")
            return self.background_job(
                "Native session renewal",
                lambda: self.submit(
                    self.sessions.renew("session_setup", route)
                ).result(),
            )
        if path == "/api/native/setup":
            route = data["route"]
            if route not in self.config["routes"]:
                raise ContractError("Unknown native route")
            if any(
                not p.done()
                for p in [*self.team.active.values(), *self.team.learning_jobs.values()]
            ):
                raise Blocked("Pause active tasks before rebinding native sessions")
            future = self.native_setup_futures.get(route)
            if future is None or future.done():
                self.native_setup_futures[route] = self.submit(
                    self.native_setup.run(route)
                )
            return {"started": True}
        if path == "/api/native/show":
            route = data.get("route")
            if route not in self.config["routes"]:
                raise ContractError("Unknown native route")
            if self.submit(self.native_setup.show(route)).result(20):
                return {"shown": True}
            return {"shown": False}
        if path == "/api/native/snapshot":
            route = data.get("route")
            if route not in self.config["routes"]:
                raise ContractError("Unknown native route")
            picture = self.native_setup.snapshot_path(route)
            if not picture.is_file():
                raise Blocked("No picture of this tab yet.")
            import base64

            return {"jpeg": base64.b64encode(picture.read_bytes()).decode(), "taken": self.native_setup.snapshots.get(route)}
        if path == "/api/github/setup":
            if self.github_setup_future is None or self.github_setup_future.done():
                self.github_setup_future = self.submit(self.github_setup.run())
            return {"started": True, **self.github_setup.status()}
        if path == "/api/traces/viewer":
            from hivemind_assembly.core.telemetry import export_local

            return export_local(self.store, data.get("port", 6006))
        if path == "/api/traces/search":
            return self.controller.traces.search(**data)
        if path == "/api/traces/annotate":
            return {
                "annotation": self.controller.traces.annotate(data["seq"], data["text"])
            }
        if path == "/api/traces/export":
            # Explicit local-owner export; never included in project publications.
            name = "traces-" + uid("export") + ".jsonl"
            target = self.store.root / "exports" / name
            target.parent.mkdir(exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                for line in self.controller.traces.export(**data):
                    stream.write(line)
            return {"path": str(target), "sha256": file_hash(target)}
        if path == "/api/github/connect":
            return self.github_auth.start(
                data["client_id"], codespaces=data.get("codespaces", False)
            )
        if path == "/api/github/poll":
            return self.github_auth.poll()
        if path == "/api/github/cancel":
            return self.github_auth.cancel()
        if path == "/api/github/check":
            return self.github_client.identity()
        if path == "/api/github/disconnect":
            return self.github_auth.disconnect()
        if path == "/api/github/settings":
            cfg = validate_config({**self.config, "github": data})
            atomic_write(self.config_path, canonical(cfg))
            self.config["github"] = cfg["github"]
            return {"saved": True}
        if path == "/api/github/link":
            return self.create_repository(data["task"], data["repository"], link=True)
        if path == "/api/github/repository":
            return self.create_repository(data["task"], data["repository"])
        if path == "/api/workspace/list":
            return self.workspace.listing(data["task"])
        if path == "/api/workspace/read":
            return self.workspace.read(data["task"], data["path"])
        if path == "/api/workspace/write":
            return self.workspace.write(
                data["task"], data["path"], data["text"], data.get("expected_sha")
            )
        if path == "/api/project/starter":
            from .project_checks import starter

            return starter(
                self, data["kind"], data["request_id"], data.get("allow_native", False)
            )
        if path == "/api/project/check":
            from .project_checks import run_checks

            return self.background_job(
                "Check project", lambda: run_checks(self, data["task"])
            )
        if path == "/api/project/check-result":
            task = self.store.task(data["task"])
            contract = Acceptance(self.controller, self.broker).describe(task["id"])
            if contract and contract["scope"] == "native_tool_tests":
                return self._action("/api/native-tests/results", data)
            rows = self.store.rows(
                "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
                ("manual_check:" + task["id"],),
            )
            return json.loads(rows[0]["payload"]) if rows else {"status": "not_run"}
        if path == "/api/project/captures":
            task = self.store.task(data["task"])
            contract = Acceptance(self.controller, self.broker).describe(task["id"])
            if contract and contract["scope"] == "native_tool_tests":
                return self._action("/api/native-tests/results", data)
            report = self._action("/api/project/check-result", data)
            details = report.get("result", {}).get("protected_details")
            if not details:
                return {"status": "not_run", "cases": []}
            result = json.loads(self.broker.artifacts.read(
                details, "evaluator", task["project_id"]
            ))
            # This owner-only dashboard route is not exported to workers or MCP.
            result["checked_revision"] = report["revision"]
            result["current_revision"] = self.store.project(task["project_id"])["revision"]
            return result
        if path == "/api/game/describe":
            return self.game_call("describe_game", data)
        if path == "/api/game/play":
            return self.game_call("play_game", data)
        if path == "/api/game/test":
            self.store.task(data.get("task"))
            return self.background_job(
                "Game " + str(data.get("mode", "compare")),
                lambda: self.game_call("test_game", data),
            )
        if path == "/api/game/save-regression":
            return self.save_game_regression(data)
        if path == "/api/jobs/result":
            job = self.background.get(data.get("job"))
            if job is None:
                raise ContractError("Unknown or expired background job")
            return dict(job)
        if path == "/api/project":
            if not data.get("name") or not data.get("objective"):
                raise ContractError("Name and objective are required")
            t = self.store.create_project(
                data["name"][:200],
                data["objective"][:20000],
                paused=bool(data.get("start_paused", False)),
                continuation=True,
            )
            return t
        if path == "/api/native-tests/results":
            task = self.store.task(data["task"])
            rows = self.store.rows(
                "SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 1",
                ("native_test_run:" + task["id"],),
            )
            return (
                json.loads(
                    self.broker.artifacts.read(
                        json.loads(rows[0]["payload"])["observations_artifact"],
                        "evaluator",
                        task["project_id"],
                    )
                )
                if rows
                else {"status": "not_run"}
            )
        if path == "/api/hosted-tests/start":
            return self.background_job(
                "Start hosted native tests",
                lambda: self.hosted_tests.start(data["task"], data["specification"]),
            )
        if path == "/api/hosted-tests/refresh":
            return self.background_job(
                "Check hosted native tests",
                lambda: self.hosted_tests.refresh(data["request_id"]),
            )
        if path == "/api/hosted-tests/cancel":
            return self.background_job(
                "Cancel hosted native tests",
                lambda: self.hosted_tests.cancel(data["request_id"]),
            )
        if path == "/api/native-tests/run":
            return self.background_job(
                "Run pinned native tests", lambda: self.run_native_tests(data["task"])
            )
        if path == "/api/native-tests/permission":
            from hivemind_assembly.core.test_acceptance import NativeTestAcceptance

            NativeTestAcceptance(self.store).allow(data["project"], data["allowed"])
            return {"allowed": data["allowed"]}
        if path == "/api/native-tests/configure":
            from hivemind_assembly.core.test_acceptance import NativeTestAcceptance

            if data.get("allow_native") is not True:
                raise Blocked(
                    "Enable trusted native execution for this project before pinning a recipe"
                )
            task = self.store.task(data["task"])
            verifier = NativeTestAcceptance(self.store)
            spec = {"scope": "native_tool_tests", "suite": data["suite"]}
            verifier.authorize_recipe(task["project_id"], spec)
            verifier.allow(task["project_id"], True)
            return Acceptance(self.controller, self.broker).configure(task["id"], spec)
        if path == "/api/goal":
            if "command" in data:
                if any(k in data for k in ("action", "objective", "max_turns")):
                    raise ContractError("Use structured objective actions or legacy syntax, not both")
                result = self.team.goals.command(data["task"], data["command"])
            else:
                result = self.team.goals.control(
                    data["task"], data.get("action", "status"),
                    objective=data.get("objective"), max_turns=data.get("max_turns"),
                )
            activating = data.get("action") in ("start", "resume") or data.get("command", "").strip() in ("/goal", "/goal resume")
            if activating and result and result["status"] == "active" and self.store.task(data["task"])["status"] == "queued":
                self.broker.cancel.setdefault(data["task"], threading.Event()).clear()
            return result
        if path == "/api/acceptance":
            return Acceptance(self.controller, self.broker).configure(
                data["task"], data["contract"]
            )
        if path == "/api/learning/optimize":
            from hivemind_assembly.domains.reverse_engineering.workflows import (
                optimize_repeated_proofs,
                optimize_repeated_calls,
            )

            kind = data.get("kind", "proofs")
            optimizers = {
                "proofs": optimize_repeated_proofs,
                "calls": optimize_repeated_calls,
            }
            if kind not in optimizers:
                raise ContractError("Unknown workflow optimization")
            if not self.learning_lock.acquire(blocking=False):
                raise Blocked("A workflow evaluation is already running")

            def optimize():
                try:
                    return optimizers[kind](self.store)
                finally:
                    self.learning_lock.release()

            return self.background_job(
                "Evaluate reusable " + kind + " workflow", optimize
            )
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
                goal = self.team.goals.status(task)
                if goal is None:
                    # Older projects acquire continuation when explicitly resumed;
                    # keep the original root even when resuming a child task.
                    with self.store.tx() as db:
                        root = db.execute(
                            "SELECT id,status FROM tasks WHERE project_id=? ORDER BY rowid LIMIT 1",
                            (t["project_id"],),
                        ).fetchone()
                        if root and root["status"] not in ("accepted", "cancelled"):
                            self.team.goals.prepare(root["id"], db)
                    goal = self.team.goals.status(task)
                if goal and goal["status"] != "active":
                    if goal["task_id"] != task:
                        raise Blocked("Resume the project's objective before its child tasks")
                    self.team.goals.control(task, "resume")
                self.broker.cancel.setdefault(task, threading.Event()).clear()
                self.store.state(task, "queued")
            return self.store.task(task)
        if path == "/api/import-target":
            task = data["task"]
            # Same rules as any workspace edit: paused task, no other owner, no
            # pending operations in the project.
            self.workspace.guard(task)
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
                if target.exists() and file_hash(target) != file_hash(source):
                    raise Blocked("A different file already has this name")
                if not target.exists():
                    shutil.copy2(source, target)
                    c.execute(
                        "UPDATE projects SET revision=revision+1 WHERE id=?",
                        (current["project_id"],),
                    )
            original = self.broker.artifacts.add_file(
                target,
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
            result = Knowledge(self.store).ingest(
                data["path"],
                bool(data.get("external_allowed", False)),
                data.get("tags"),
            )
            if data.get("external_allowed") and not data.get("tags"):
                result["tagging"] = self.team.curation.queue("source", result["id"])
            return result
        if path == "/api/settings":
            if any(
                not p.done()
                for p in [*self.team.active.values(), *self.team.learning_jobs.values()]
            ):
                raise Blocked("Pause active tasks before changing route bindings")
            pending = (
                [self.github_setup_future]
                if self.github_setup_future is not None
                else []
            )
            if any(not p.done() for p in pending) or any(
                j["status"] == "running" for j in self.background.values()
            ):
                raise Blocked(
                    "Wait for active setup and background jobs before changing settings"
                )
            cfg = validate_config(data["config"])

            async def replace_config():
                await self.team.freeze_dispatch()
                try:
                    futures = list(self.native_setup_futures.values())
                    for future in futures:
                        future.cancel()
                    await asyncio.gather(
                        *(
                            (
                                f
                                if isinstance(f, asyncio.Future)
                                else asyncio.wrap_future(f)
                            )
                            for f in futures
                        ),
                        return_exceptions=True,
                    )
                    self.native_setup_futures.clear()
                    await self.browser.close()
                    atomic_write(self.config_path, canonical(cfg))
                    self.config.clear()
                    self.config.update(cfg)
                    self.sessions.drafts.clear()
                    self.native_setup.pages.clear()
                    self.team.observations.clear()
                    self.configure_learning()
                finally:
                    self.team.pause_dispatch = False

            self.submit(replace_config()).result(timeout=20)
            return {"saved": True}
        if path == "/api/probe":
            route = data["route"]
            return self.background_job(
                "Observe native route",
                lambda: self.submit(self.browser.observe(route)).result(timeout=120),
            )
        if path == "/api/verify-foundations":
            from .verification import verify_foundations

            return self.background_job(
                "Verify installed foundations",
                lambda: verify_foundations(
                    self.store.root / "private" / "verification",
                    self.config["foundations"],
                    self.broker.jobs,
                ),
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
            from hivemind_assembly.core.backups import snapshot

            pending = [*self.native_setup_futures.values()]
            if self.github_setup_future is not None:
                pending.append(self.github_setup_future)
            if any(not p.done() for p in pending) or any(
                j["status"] == "running" for j in self.background.values()
            ):
                raise Blocked(
                    "Wait for active setup and background jobs before backing up"
                )
            self.submit(self.team.freeze_dispatch()).result(timeout=15)
            try:
                name = "workspace-" + uid("backup") + ".zip"
                return snapshot(self.store, self.store.root / "backups" / name)
            finally:
                self.loop.call_soon_threadsafe(
                    setattr, self.team, "pause_dispatch", False
                )

        if path == "/api/reconcile":
            op = self.store.one(
                "SELECT tool FROM operations WHERE id=?", (data["operation"],)
            )
            if op["tool"] in (
                "propose_annotation",
                "create_repository",
                "link_repository",
                "publish_checkpoint",
            ):
                return self.broker.reconcile_native(data["operation"])
            return self.broker.reconcile_file(data["operation"])
        if path == "/api/setup":
            from hivemind_assembly.application.setup import install_foundations

            if self.foundations_status()["installing"]:
                raise Blocked("Foundation installation is already running")

            def install(publish):
                from hivemind_assembly.application.setup import SetupProgress
                from .prerequisites import missing

                progress = SetupProgress(publish)
                # Plan the optional downloads too, so the percentage covers the whole step.
                try:
                    if os.name == "nt" and "gh" in missing(extra=("gh",)):
                        progress.expect("Installing the GitHub CLI", 15)
                except Blocked:
                    pass
                if not self.tunnel.status()["installed"]:
                    progress.expect("Installing the MCP tunnel client", 15)
                if not self.quick.installed():
                    progress.expect("Installing the browser connection tunnel", 40)
                result = install_foundations(self.store.root, self.config_path, progress=progress)
                # Load the new paths in place so specialists can use them
                # without restarting HA.
                saved = json.loads(Path(self.config_path).read_text())
                self.config["foundations"].update(saved.get("foundations", {}))
                # Optional downloads in the same step, so setup is one action.
                # Their failures are reported without undoing the core tools.
                result["optional"] = self.install_optional_tools(progress)
                progress.finish()
                return result

            return self.background_job("Install pinned foundations", install, progress=True)
        raise ContractError("Unknown action")

    def game_call(self, tool, data):
        """Owner play-testing through the same deterministic domain operations.

        Read-only: results depend only on workspace files and the trajectory. Frames
        return as raw RGBA for canvas display (the dashboard policy blocks data URLs).
        """
        import base64

        import dataclasses

        task = data.get("task")
        self.store.task(task)
        args = {k: v for k, v in data.items() if k != "task"}
        context = dataclasses.replace(self.broker.context(task), cancel=self.game_cancel)
        result = self.broker.domain.games.execute(context, {"tool": tool, "args": args})
        images = result.pop("_images", None) or []
        result["frames"] = [
            {k: image[k] for k in ("name", "side", "tick", "width", "height")}
            | {"rgba_base64": base64.b64encode(image["rgba"]).decode()}
            for image in images
            if "rgba" in image
        ]
        return result

    def save_game_regression(self, data):
        """Append or replace one saved regression; an ordinary guarded owner edit."""
        from hivemind_assembly.core import game_spec, game_testing

        task = data["task"]
        games = self.broker.domain.games
        spec = games.load(self.broker.workspace(task), data.get("game_path", "game.json"))
        inputs = game_spec.decode_token(data.get("trajectory"), spec)
        if not inputs:
            raise ContractError("Play at least one input before saving a regression")
        name = spec["regressions_path"]
        path = self.workspace.path(task, name)
        current = self.workspace.read(task, name) if path.is_file() else None
        if current is not None and current["text"] is None:
            raise ContractError("The regressions file is not UTF-8 text")
        value = json.loads(current["text"]) if current else {"version": 1, "regressions": []}
        items = game_testing.validate_regressions(spec, value)
        item = {
            "id": data.get("id"),
            "inputs_hex": inputs.hex(),
            "expect": data.get("expect", "match_original"),
            # Findings detected after end of input keep it; manual play ends input.
            "end": data.get("end", True),
        }
        if data.get("note"):
            item["note"] = str(data["note"])[:500]
        value = {
            "version": 1,
            "regressions": [r for r in items if r["id"] != item["id"]] + [item],
        }
        game_testing.validate_regressions(spec, value)
        return self.workspace.write(
            task,
            name,
            json.dumps(value, indent=2) + "\n",
            current["sha256"] if current else None,
        )

    def install_optional_tools(self, progress=None):
        """GitHub CLI (Codespaces) and both MCP tunnels; each reports its own result."""
        from .prerequisites import install_missing

        results = {}
        try:
            if progress:
                install_missing(extra=("gh",), progress=progress)
            else:
                install_missing(extra=("gh",))
            results["github_cli"] = "ready"
        except Blocked as e:
            results["github_cli"] = str(e)
        if self.tunnel.status()["installed"]:
            results["tunnel_client"] = "ready"
        else:
            if progress:
                progress.begin("Installing the MCP tunnel client", 15)
            try:
                self.tunnel.install(progress) if progress else self.tunnel.install()
                results["tunnel_client"] = "ready"
            except Exception as e:  # network, release or disk problems
                results["tunnel_client"] = (
                    "Not installed (" + type(e).__name__ + "); select Install required tools in Settings to retry."
                )
        if self.quick.installed():
            results["browser_tunnel"] = "ready"
        else:
            if progress:
                progress.begin("Installing the browser connection tunnel", 40)
            try:
                self.quick.install(progress)
                results["browser_tunnel"] = "ready"
            except Exception as e:  # network, release or disk problems
                results["browser_tunnel"] = (
                    "Not installed (" + type(e).__name__ + "); select Install required tools in Settings to retry."
                )
        return results

    def run_native_tests(self, task_id, expected_revision=None):
        with self.store.lock:
            self.workspace.guard(task_id)
            with self.store.tx() as db:
                task = self.store.task(task_id)
                if expected_revision is not None and self.store.project(task["project_id"])["revision"] != expected_revision:
                    raise Conflict("Project changed before the requested check started")
                if task["status"] != "paused" or task["owner"]:
                    raise Blocked(
                        "Manual tests require a paused, unassigned task; active workers use test_programs"
                    )
                db.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))
            try:
                epoch = self.controller.acquire(task_id, "user.testing", seconds=1200)
            except BaseException:
                self.store.state(task_id, "paused")
                raise
        try:
            revision = self.store.project(task["project_id"])["revision"]
            event = self.broker.cancel.setdefault(task_id, threading.Event())
            event.clear()
            if self.shutdown:
                event.set()
                raise Blocked("HA is shutting down")
            self.controller.brief(
                task_id,
                {"revision": revision},
                {
                    "procedure": "Run the owner-pinned native recipe",
                    "acceptance": "Exact repeated observations must match the protected oracle",
                },
                {"critical_gaps": []},
                [],
            )
            return self.broker.execute(
                {
                    "id": uid("native_test"),
                    "task_id": task_id,
                    "owner": "user.testing",
                    "epoch": epoch,
                    "revision": revision,
                    "tool": "test_programs",
                    "args": {},
                }
            )
        finally:
            with self.store.tx() as db:
                db.execute(
                    "UPDATE tasks SET status=CASE WHEN status='cancelled' THEN status ELSE 'paused' END,owner=NULL,lease_until=0,brief_id=NULL WHERE id=? AND epoch=? AND owner='user.testing'",
                    (task_id, epoch),
                )

    def create_repository(self, task_id, args, link=False):
        """User-initiated provisioning uses the same journal and writer fences."""
        from hivemind_assembly.core.repositories import repository_args

        repository_args(args)
        with self.store.tx() as db:
            task = self.store.task(task_id)
            if (
                task["status"] not in ("paused", "queued", "waiting_quota")
                or task["owner"]
            ):
                raise Blocked(
                    "Prepare the repository before agents start, or let the assigned worker request it."
                )
            if db.execute(
                "SELECT 1 FROM operations WHERE task_id=? AND state IN ('running','uncertain','applied')",
                (task_id,),
            ).fetchone():
                raise Blocked(
                    "Reconcile the previous operation in Results & backups first."
                )
            # Reserve ownership atomically so the team cannot acquire this task.
            epoch = task["epoch"] + 1
            db.execute(
                "UPDATE tasks SET status='running',owner='user.repository',epoch=?,lease_until=? WHERE id=?",
                (epoch, time.time() + 300, task_id),
            )
        try:
            revision = self.store.project(task["project_id"])["revision"]
            self.controller.brief(
                task_id,
                {"revision": revision},
                {
                    "procedure": "Create or recover the requested private GitHub repository.",
                    "acceptance": "Verify account, repository identity, private visibility and write access.",
                },
                {"critical_gaps": []},
                [],
            )
            return self.broker.execute(
                {
                    "id": uid("repository"),
                    "task_id": task_id,
                    "owner": "user.repository",
                    "epoch": epoch,
                    "revision": revision,
                    "tool": "link_repository" if link else "create_repository",
                    "args": args,
                }
            )
        finally:
            with self.store.tx() as db:
                # Keep this user-prepared project paused, including on uncertainty.
                db.execute(
                    "UPDATE tasks SET status='paused',owner=NULL,lease_until=0,brief_id=NULL WHERE id=? AND epoch=? AND owner='user.repository'",
                    (task_id, epoch),
                )

    def close(self):
        if self.closed:
            return
        self.tunnel.close()
        self.quick.close()
        try:
            self.submit(self.browser.relay.close()).result(5)
        except Exception:
            pass
        self.permanent.close()
        self.connections.oauth.close()
        self.connections.session_credentials.clear()
        self.codespaces.close()
        self.hosted_tests.close()
        self.shutdown = True
        self.game_cancel.set()
        for event in self.broker.cancel.values():
            event.set()
        self.mcp_gateway.checks.close()

        async def close_runtime():
            await self.connections.oauth.drain()
            for future in self.native_setup_futures.values():
                future.cancel()
            if self.github_setup_future is not None:
                self.github_setup_future.cancel()
            await self.team.stop()
            self.runner.cancel()
            await asyncio.gather(self.runner, return_exceptions=True)

        self.submit(close_runtime()).result(timeout=20)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.store.close()
        self.instance_lock.close()
        self.closed = True


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
            import hmac

            return hmac.compare_digest(
                (self.headers.get("X-Workbench-Token") or "").encode(), app.token.encode()
            )

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
                "/native_captures.js": ("native_captures.js", "text/javascript"),
                "/knowledge.js": ("knowledge.js", "text/javascript"),
                "/connections.js": ("connections.js", "text/javascript"),
                "/quick_connect.js": ("quick_connect.js", "text/javascript"),
                "/help.js": ("help.js", "text/javascript"),
                "/workspace.js": ("workspace.js", "text/javascript"),
                "/game_testing.js": ("game_testing.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
                "/favicon.svg": ("favicon.svg", "image/svg+xml"),
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
                if urlsplit(self.path).path == "/api/workspace/upload":
                    from .workspace import UPLOAD_LIMIT

                    n = int(self.headers.get("Content-Length", "-1"))
                    if (
                        not 0 <= n <= UPLOAD_LIMIT
                        or self.headers.get("Content-Type")
                        != "application/octet-stream"
                    ):
                        raise ContractError(
                            "File uploads require binary data up to 256 MiB"
                        )
                    task = self.headers.get("X-HA-Task", "")
                    name = unquote(self.headers.get("X-HA-Path", ""))
                    app.workspace.path(task, name)
                    app.workspace.guard(task)
                    self.connection.settimeout(30)
                    with tempfile.TemporaryDirectory(prefix="ha-upload-") as folder:
                        stage = Path(folder) / "upload"
                        with stage.open("wb") as out:
                            remaining = n
                            while remaining:
                                chunk = self.rfile.read(min(remaining, 1024 * 1024))
                                if not chunk:
                                    raise ContractError("File upload was interrupted")
                                out.write(chunk)
                                remaining -= len(chunk)
                        result = app.workspace.install(
                            task,
                            name,
                            stage,
                            self.headers.get("X-HA-Expected-SHA256") or None,
                        )
                    self.send(200, result)
                    return
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 < n <= 2_000_000:
                    raise ContractError("Invalid request size")
                if (
                    self.headers.get("Content-Type", "").split(";")[0]
                    != "application/json"
                ):
                    raise ContractError("JSON required")
                value = json.loads(self.rfile.read(n))
                if urlsplit(self.path).path == "/api/workspace/download":
                    with app.workspace.download(
                        value["task"], value["path"], value["sha256"]
                    ) as stage:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(stage.stat().st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header(
                            "Content-Disposition",
                            "attachment; filename*=UTF-8''"
                            + quote(Path(value["path"]).name),
                        )
                        self.end_headers()
                        with stage.open("rb") as source:
                            shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
                    return
                result = app.action(urlsplit(self.path).path, value)
                self.send(200, result)
            except FileNotFoundError as e:
                # Name only: absolute host paths stay out of browser responses.
                self.send(400, {"error": "File not found: " + Path(e.filename or "").name})
            except (ContractError, KeyError, ValueError) as e:
                self.send(400, {"error": str(e)})
            except Exception as e:
                reference = uid("error")
                try:
                    log = app.store.root / "logs" / "dashboard-errors.log"
                    log.parent.mkdir(parents=True, exist_ok=True)
                    with log.open("a", encoding="utf-8") as handle:
                        handle.write(reference + " " + type(e).__name__ + ": " + str(e) + "\n")
                except OSError:
                    pass
                self.send(
                    500,
                    {"error": "Internal error (" + type(e).__name__ + "); details are in logs/dashboard-errors.log as " + reference},
                )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    private = app.store.root / "private"
    private.mkdir(parents=True, exist_ok=True)
    atomic_write(
        private / "endpoint.json",
        canonical({"port": server.server_port, "token": app.token}),
    )
    if os.name != "nt":
        (private / "endpoint.json").chmod(0o600)
    return server


def serve(root=None, port=0, open_browser=True):
    if os.name == "nt":
        # Find tools installed since Windows started this process (or installed
        # without a PATH entry) before anything looks for them.
        from .prerequisites import refresh_windows_path

        try:
            refresh_windows_path()
        except OSError:
            pass
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
