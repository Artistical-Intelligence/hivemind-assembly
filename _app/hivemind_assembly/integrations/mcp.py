"""Official-SDK MCP bridge and outbound connections; controller remains authoritative."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    Conflict,
    atomic_write,
    canonical,
    digest,
    uid,
)
from hivemind_assembly.paths import APP_ROOT


class Connections:
    def __init__(self, store):
        self.store = store
        self.path = store.root / "private" / "mcp.json"
        self.lock = threading.RLock()
        self.session_credentials = {}
        self.operation_locks = {}
        from .mcp_oauth import OAuthManager

        self.oauth = OAuthManager(self)

    def settings(self):
        if not self.path.exists():
            return {
                "enabled": False,
                "allow_create": False,
                "projects": [],
                "servers": {},
            }
        return json.loads(self.path.read_text("utf-8"))

    def save(self, value):
        if not isinstance(value, dict) or set(value) != {
            "enabled",
            "allow_create",
            "projects",
            "servers",
        }:
            raise ContractError(
                "MCP settings require enabled, allow_create, projects and servers"
            )
        if any(type(value[k]) is not bool for k in ("enabled", "allow_create")):
            raise ContractError("MCP permissions must be booleans")
        if not isinstance(value["projects"], list) or any(
            not isinstance(x, str) for x in value["projects"]
        ):
            raise ContractError("Select project IDs for MCP access")
        for project in value["projects"]:
            self.store.project(project)
        if not isinstance(value["servers"], dict) or len(value["servers"]) > 32:
            raise ContractError("Expected at most 32 external MCP servers")
        for name, spec in value["servers"].items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
                raise ContractError("Invalid MCP connection name")
            if not isinstance(spec, dict) or set(spec) - {
                "transport",
                "url",
                "command",
                "args",
                "tools",
                "projects",
                "timeout",
                "auth",
                "client_metadata_url",
                "oauth_callback_port",
            }:
                raise ContractError(
                    "Unsupported connection field; keep credentials in the credential store"
                )
            if "client_metadata_url" in spec or "oauth_callback_port" in spec:
                from .mcp_oauth import client_metadata_document

                if spec.get("transport") != "http":
                    raise ContractError("Client metadata is for HTTP MCP connections")
                client_metadata_document(
                    spec.get("client_metadata_url"), spec.get("oauth_callback_port")
                )
            if spec.get("auth", "none") not in (
                "none",
                "session",
                "vault",
                "oauth_session",
                "oauth_vault",
            ):
                raise ContractError(
                    "Choose none, session/vault bearer, or session/vault OAuth authentication"
                )
            if spec.get("auth", "none") != "none" and spec.get("transport") != "http":
                raise ContractError(
                    "HA-managed bearer authentication is for HTTP MCP connections"
                )
            if spec.get("transport") == "http":
                parsed = urlsplit(spec.get("url", ""))
                if (
                    parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or not parsed.hostname
                ):
                    raise ContractError(
                        "MCP URL must not contain credentials, query or fragment"
                    )
                if parsed.scheme != "https" and not (
                    parsed.scheme == "http"
                    and parsed.hostname in ("localhost", "127.0.0.1", "::1")
                ):
                    raise ContractError("Use HTTPS or a loopback HTTP MCP endpoint")
            elif spec.get("transport") == "stdio":
                if (
                    not isinstance(spec.get("command"), str)
                    or not Path(spec["command"]).is_absolute()
                ):
                    raise ContractError(
                        "Use an absolute executable path for local MCP servers"
                    )
                if not isinstance(spec.get("args", []), list) or any(
                    not isinstance(a, str) or "\x00" in a for a in spec.get("args", [])
                ):
                    raise ContractError("MCP arguments must be an argument list")
            else:
                raise ContractError("MCP transport must be http or stdio")
            if (
                type(spec.get("timeout", 120)) is not int
                or not 1 <= spec.get("timeout", 120) <= 3600
            ):
                raise ContractError("MCP request timeout must be 1–3600 seconds")
            for field in ("tools", "projects"):
                if not isinstance(spec.get(field, []), list) or any(
                    not isinstance(x, str) for x in spec.get(field, [])
                ):
                    raise ContractError("MCP tools and projects must be explicit lists")
            for project in spec.get("projects", []):
                self.store.project(project)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, canonical(value))
            if os.name != "nt":
                self.path.chmod(0o600)
        return value

    def client_config(self):
        return {
            "mcpServers": {
                "hivemind-assembly": {
                    "command": sys.executable,
                    "args": [
                        "-u",
                        str(APP_ROOT / "launch.py"),
                        "mcp",
                        "--data-dir",
                        str(self.store.root),
                    ],
                }
            }
        }

    def install_config(self, path):
        """Merge only our entry; preserve unrelated MCP servers and retain a backup."""
        p = Path(path).expanduser().absolute()
        if any(x.is_symlink() for x in (p, *p.parents)) or p.suffix != ".json":
            raise ContractError("Choose a JSON MCP client configuration file")
        with self.lock:
            old = p.read_text("utf-8") if p.exists() else "{}"
            value = json.loads(old)
            if not isinstance(value, dict) or not isinstance(
                value.get("mcpServers", {}), dict
            ):
                raise ContractError("Expected a client configuration with mcpServers")
            backup = None
            if p.exists():
                backup = p.with_name(p.name + "." + uid("backup") + ".bak")
                atomic_write(backup, old)
                if os.name != "nt":
                    backup.chmod(0o600)
            value.setdefault("mcpServers", {}).update(
                self.client_config()["mcpServers"]
            )
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(p, canonical(value))
            if os.name != "nt":
                p.chmod(0o600)
        return {"installed": str(p), "backup": str(backup) if backup else None}

    def credential(self, server, token=None, remember=False, forget=False):
        from .github import CredentialVault

        cfg = self.settings()
        spec = cfg["servers"].get(server)
        if not spec or spec["transport"] != "http":
            raise ContractError("Choose an HTTP MCP connection first")
        if type(remember) is not bool or type(forget) is not bool:
            raise ContractError("Credential storage options must be booleans")
        vault = CredentialVault(self.store.root, service="MCP." + server)
        with self.lock:
            if forget:
                self.oauth.forget(server)
                self.session_credentials.pop(server, None)
                spec["auth"] = "none"
            else:
                if not isinstance(token, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.~+/-]{10,4000}={0,2}", token
                ):
                    raise ContractError("Provide a bearer token without whitespace")
                value = {"url": spec["url"], "token": token}
                if spec.get("auth", "").startswith("oauth_"):
                    self.oauth.forget(server)
                if remember:
                    vault.write(value)
                    self.session_credentials.pop(server, None)
                else:
                    if spec.get("auth") == "vault":
                        vault.clear()
                    self.session_credentials[server] = value
                spec["auth"] = "vault" if remember else "session"
            self.save(cfg)
        return {"server": server, "authentication": spec["auth"]}

    def bearer(self, server, spec):
        if spec.get("auth", "none") == "none":
            return None
        if spec["auth"] == "vault":
            from .github import CredentialVault

            value = CredentialVault(self.store.root, service="MCP." + server).read()
        else:
            value = self.session_credentials.get(server)
        if not value or value["url"] != spec["url"]:
            raise Blocked(
                "MCP credential is unavailable or belongs to a different endpoint; reconnect it"
            )
        return value["token"]

    def authorize(self, server, tool, project):
        spec = self.settings()["servers"].get(server)
        if (
            not spec
            or tool not in spec.get("tools", [])
            or project not in spec.get("projects", [])
        ):
            raise Blocked(
                "MCP tool or project has not been authorized for this connection"
            )
        return spec

    def manifest(self, project):
        result = []
        for name, spec in self.settings()["servers"].items():
            if project not in spec.get("projects", []) or not spec.get("tools"):
                continue
            key = digest(
                {
                    "server": name,
                    "transport": spec.get("transport"),
                    "url": spec.get("url"),
                    "command": spec.get("command"),
                    "args": spec.get("args", []),
                }
            )
            rows = self.store.rows(
                "SELECT payload FROM records WHERE kind='mcp_inventory' AND id=?",
                (key,),
            )
            inventory = json.loads(rows[0]["payload"]) if rows else []
            result.append(
                {
                    "server": name,
                    "tools": spec["tools"],
                    "schemas": [t for t in inventory if t["name"] in spec["tools"]],
                    "usage": {
                        "tool": "mcp_call",
                        "args": {
                            "server": name,
                            "tool": "<allowed tool>",
                            "arguments": {},
                        },
                    },
                }
            )
        return result

    async def external(
        self, server, tool=None, arguments=None, project=None, *, oauth_setup=None
    ):
        # Setup, refresh and tool use share one per-server reservation even when
        # dashboard requests and worker calls arrive on separate event loops.
        with self.lock:
            lock = self.operation_locks.setdefault(server, threading.Lock())
        timeout = (
            600
            if oauth_setup
            else self.settings()["servers"].get(server, {}).get("timeout", 120)
        )
        async with asyncio.timeout(timeout):
            while not lock.acquire(blocking=False):
                await asyncio.sleep(0.05)
            try:
                return await self._external(
                    server, tool, arguments, project, oauth_setup
                )
            except Exception as error:
                spec = self.settings()["servers"].get(server, {})
                if spec.get("auth", "").startswith("oauth_") and not isinstance(
                    error, (Blocked, ContractError)
                ):
                    raise Blocked(
                        "MCP OAuth exchange failed ("
                        + type(error).__name__
                        + "). Reconnect in Connections if authorization has expired."
                    ) from None
                raise
            finally:
                lock.release()

    async def _external(self, server, tool, arguments, project, oauth_setup):
        from mcp import Client, StdioServerParameters

        settings = self.settings()
        spec = settings["servers"].get(server)
        if not spec:
            raise Blocked("MCP connection is not configured")
        if tool is not None:
            self.authorize(server, tool, project)
        secret = None
        oauth_storage = None
        if spec["transport"] == "http":
            from mcp.client.streamable_http import streamable_http_client
            import httpx2

            provider = None
            if spec.get("auth", "").startswith("oauth_"):
                provider, oauth_storage = oauth_setup or await self.oauth.provider(
                    server, spec
                )
            else:
                secret = self.bearer(server, spec)

            @asynccontextmanager
            async def authenticated_transport():
                async with httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + secret} if secret else {},
                    auth=provider,
                    follow_redirects=False,
                    trust_env=False,
                ) as http:
                    async with streamable_http_client(
                        spec["url"], http_client=http
                    ) as streams:
                        yield streams

            target = authenticated_transport()
        else:
            env = {
                k: os.environ[k]
                for k in (
                    "PATH",
                    "SystemRoot",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "HOME",
                    "USERPROFILE",
                )
                if k in os.environ
            }
            target = StdioServerParameters(
                command=spec["command"], args=spec.get("args", []), env=env
            )
        async with asyncio.timeout(600 if oauth_setup else spec.get("timeout", 120)):
            async with Client(target) as client:
                if tool is None:
                    inventory = []
                    cursor = None
                    seen = set()
                    while True:
                        result = await client.list_tools(cursor=cursor)
                        inventory.extend(
                            t.model_dump(mode="json", by_alias=True)
                            for t in result.tools
                        )
                        if (
                            len(inventory) > 1000
                            or len(canonical(inventory)) > 2_000_000
                        ):
                            raise Blocked("MCP tool inventory exceeds discovery limit")
                        cursor = result.next_cursor
                        if not cursor:
                            break
                        if cursor in seen:
                            raise Blocked("MCP discovery repeated a cursor")
                        seen.add(cursor)
                    if secret:
                        inventory = json.loads(
                            canonical(inventory).replace(secret, "[redacted]")
                        )
                    if oauth_storage:
                        oauth_storage.check()
                        inventory = oauth_storage.redact(inventory)
                    key = digest(
                        {
                            "server": server,
                            "transport": spec.get("transport"),
                            "url": spec.get("url"),
                            "command": spec.get("command"),
                            "args": spec.get("args", []),
                        }
                    )
                    with self.store.tx() as db:
                        db.execute(
                            "DELETE FROM records WHERE kind='mcp_inventory' AND id=?",
                            (key,),
                        )
                        self.store.put("mcp_inventory", key, inventory, db)
                    return inventory
                result = await client.call_tool(tool, arguments or {})
                value = result.model_dump(mode="json", by_alias=True)
                if oauth_storage:
                    oauth_storage.check()
                    value = oauth_storage.redact(value)
                return (
                    json.loads(canonical(value).replace(secret, "[redacted]"))
                    if secret
                    else value
                )


class Gateway:
    """Owner-granted project access. No unrestricted application-action forwarding."""

    def __init__(self, app):
        self.app = app
        self.connections = app.connections

    def task(self, task_id):
        task = self.app.store.task(task_id)
        if task["project_id"] not in self.connections.settings()["projects"]:
            raise Blocked("Project is not shared with MCP")
        return task

    def call(self, tool, args):
        cfg = self.connections.settings()
        if not cfg["enabled"]:
            raise Blocked("Enable MCP in HA connection settings first")
        if tool == "ha_projects":
            return {
                "projects": [
                    {
                        **self.app.store.project(p),
                        "tasks": self.app.store.rows(
                            "SELECT id,objective,status FROM tasks WHERE project_id=?",
                            (p,),
                        ),
                    }
                    for p in cfg["projects"]
                ]
            }
        if tool == "ha_create_project":
            if not cfg["allow_create"]:
                raise Blocked("MCP project creation is disabled")
            key = args["request_id"]
            if not isinstance(key, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,100}", key
            ):
                raise ContractError("Provide a stable request ID")
            identity = digest(args)
            with self.app.store.tx() as db:
                old = db.execute(
                    "SELECT payload FROM records WHERE kind='mcp_create' AND id=?",
                    (key,),
                ).fetchone()
                if old:
                    retained = json.loads(old[0])
                    if retained["hash"] != identity:
                        raise Conflict(
                            "Request ID was reused with different project details"
                        )
                    result = retained["task"]
                else:
                    # Create via store transaction below, not a nested Application action.
                    name, objective = args["name"], args["objective"]
                    if (
                        not isinstance(name, str)
                        or not name.strip()
                        or len(name) > 200
                        or not isinstance(objective, str)
                        or not objective.strip()
                        or len(objective) > 20000
                    ):
                        raise ContractError("Provide a project name and objective")
                    import time

                    project_id, task_id = uid("project"), uid("task")
                    db.execute(
                        "INSERT INTO projects VALUES(?,?,?,0,?)",
                        (project_id, name, objective, time.time()),
                    )
                    db.execute(
                        "INSERT INTO tasks(id,project_id,objective,status,updated) VALUES(?,?,?,'paused',?)",
                        (task_id, project_id, objective, time.time()),
                    )
                    result = dict(
                        db.execute(
                            "SELECT * FROM tasks WHERE id=?", (task_id,)
                        ).fetchone()
                    )
                    self.app.store.put(
                        "mcp_create", key, {"hash": identity, "task": result}, db
                    )
            if result["project_id"] not in cfg["projects"]:
                cfg["projects"].append(result["project_id"])
                self.connections.save(cfg)
            self.app.broker.workspace(result["id"]).mkdir(parents=True, exist_ok=True)
            return result
        task = self.task(args["task"])
        if tool == "ha_task_status":
            return {"task": task, "goal": self.app.team.goals.status(task["id"])}
        if tool == "ha_control":
            if args["action"] not in ("pause", "resume", "cancel"):
                raise ContractError("Expected pause, resume or cancel")
            return self.app.action("/api/control", args)
        if tool == "ha_goal":
            return {"goal": self.app.action("/api/goal", args)}
        if tool == "ha_list_files":
            return self.app.workspace.listing(task["id"])
        if tool == "ha_read_file":
            return self.app.workspace.read(task["id"], args["path"])
        if tool == "ha_write_file":
            return self.app.workspace.write(
                task["id"], args["path"], args["text"], args.get("expected_sha")
            )
        raise ContractError("Unknown HA MCP tool")


def build_server(call):
    from mcp.server import MCPServer

    server = MCPServer(
        "Hivemind Assembly",
        instructions="Create or select a shared project. Projects start paused; configure acceptance in HA before autonomous execution. Use stable request IDs. Never treat an execution request as proof of completion.",
    )

    @server.tool()
    def ha_projects() -> dict[str, Any]:
        """List only projects the owner has shared with this MCP connection."""
        return call("ha_projects", {})

    @server.tool()
    def ha_create_project(name: str, objective: str, request_id: str) -> dict[str, Any]:
        """Create a paused project, idempotently, when owner permission permits."""
        return call(
            "ha_create_project",
            {"name": name, "objective": objective, "request_id": request_id},
        )

    @server.tool()
    def ha_task_status(task: str) -> dict[str, Any]:
        """Read durable task status and its standing goal."""
        return call("ha_task_status", {"task": task})

    @server.tool()
    def ha_control(task: str, action: str) -> dict[str, Any]:
        """Pause, resume or cancel a shared task."""
        return call("ha_control", {"task": task, "action": action})

    @server.tool()
    def ha_goal(task: str, command: str = "/goal status") -> dict[str, Any]:
        """Manage the task's persistent /goal, including pause and resume."""
        return call("ha_goal", {"task": task, "command": command})

    @server.tool()
    def ha_list_files(task: str) -> dict[str, Any]:
        """List a shared project's files and acceptance configuration."""
        return call("ha_list_files", {"task": task})

    @server.tool()
    def ha_read_file(task: str, path: str) -> dict[str, Any]:
        """Read a bounded project file. Paths must stay within the shared project."""
        return call("ha_read_file", {"task": task, "path": path})

    @server.tool()
    def ha_write_file(
        task: str, path: str, text: str, expected_sha: str | None = None
    ) -> dict[str, Any]:
        """Write a paused project's text file; existing files require their current hash."""
        return call(
            "ha_write_file",
            {"task": task, "path": path, "text": text, "expected_sha": expected_sha},
        )

    return server


def serve_bridge(root):
    """Stdio is suitable for local clients and private MCP tunnel subprocesses."""
    import httpx

    root = Path(root)

    def call(tool, arguments):
        try:
            endpoint = json.loads((root / "private" / "endpoint.json").read_text())
            port = endpoint["port"]
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError()
            with httpx.Client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                r = client.post(
                    f"http://127.0.0.1:{port}/api/mcp/call",
                    headers={"X-Workbench-Token": endpoint["token"]},
                    json={"tool": tool, "arguments": arguments},
                )
                if r.status_code != 200:
                    raise Blocked(r.json().get("error", "HA rejected the request"))
                return r.json()
        except (OSError, ValueError, httpx.HTTPError):
            raise Blocked(
                "Start HA on this computer before connecting its MCP bridge"
            ) from None

    build_server(call).run()
