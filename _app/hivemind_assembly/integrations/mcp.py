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


def secret_forms(secret):
    """The secret and encodings a server might echo it in."""
    import base64
    from urllib.parse import quote

    raw = secret.encode()
    forms = {
        secret,
        quote(secret, safe=""),
        raw.hex(),
        base64.b64encode(raw).decode(),
        base64.urlsafe_b64encode(raw).decode(),
    }
    forms |= {f.rstrip("=") for f in forms}
    # Encodings of very short values would match unrelated text; the exact
    # value is always redacted.
    return sorted({secret, *(f for f in forms if len(f) >= 8)}, key=len, reverse=True)


def inline_github_mcp_text(result, *, max_chars=240_000):
    """Bound a text-file MCP tool result without producing an attachment.

    This runs for explicitly approved file-reading tool names regardless of
    the user-supplied MCP server alias. A compatible embedded UTF-8 resource
    is copied to a text block. Links, binary content and unknown media are
    never fetched, materialized, or silently passed through.

    It does not alter ChatGPT's separate hosted materialization approval gate.
    """
    if not isinstance(result, dict):
        raise ContractError("Expected a structured MCP result")
    if type(max_chars) is not int or not 1 <= max_chars <= 1_000_000:
        raise ContractError("Invalid MCP inline-text response limit")
    total = 0

    def inline_blocks(blocks):
        nonlocal total
        if not isinstance(blocks, list):
            raise ContractError("MCP file content blocks are invalid")
        converted = []
        for block in blocks:
            if not isinstance(block, dict):
                raise ContractError("MCP file content block is invalid")
            kind = block.get("type")
            if kind == "text":
                value = block.get("text")
                if not isinstance(value, str):
                    raise ContractError("MCP text content is invalid")
            elif kind == "resource":
                resource = block.get("resource", {})
                if not isinstance(resource, dict):
                    raise ContractError("MCP embedded resource is invalid")
                mime = resource.get("mimeType", resource.get("mime_type", ""))
                value = resource.get("text")
                if (not isinstance(mime, str)
                    or not (mime.lower().startswith("text/")
                            or mime.lower().split(";")[0].strip() == "application/json")
                    or not isinstance(value, str)
                    or "blob" in resource or "data" in resource):
                    raise Blocked(
                        "MCP returned non-text or encoded file content. "
                        "No automatic attachment materialization; use a separately "
                        "authorized binary-file workflow if actual bytes are needed."
                    )
                charset = []
                for parameter in mime.split(";")[1:]:
                    part = parameter.strip()
                    if re.match(r"^charset\\b", part, re.IGNORECASE):
                        # Media types permit whitespace around '='. Never
                        # mistake 'charset = latin-1' for an absent charset.
                        match = re.fullmatch(
                            r"charset\\s*=\\s*(.+)", part, re.IGNORECASE
                        )
                        if not match:
                            raise Blocked("MCP text resource has an invalid charset")
                        charset.append(match.group(1).strip().strip('"').lower())
                if any(name not in ("utf-8", "utf8", "us-ascii")
                       for name in charset):
                    raise Blocked("MCP text resource declares a non-UTF-8 charset")
            elif kind == "resource_link":
                raise Blocked(
                    "MCP returned a downloadable file link instead of inline text. "
                    "Use an authorized text-only source read with bounded lines; "
                    "no automatic materialization."
                )
            else:
                raise Blocked(
                    "MCP returned non-text content; only inline UTF-8 source reads "
                    "are accepted by this HA bridge."
                )
            # Literal text must be UTF-8 encodable. An MCP server can
            # otherwise supply lone surrogates or NUL-delimited binary data
            # disguised as a text block. Bound encoded bytes, not Unicode
            # code points, before returning anything to a hosted client.
            if "\x00" in value:
                raise Blocked("MCP source contains binary NUL bytes")
            try:
                encoded_size = len(value.encode("utf-8", errors="strict"))
            except UnicodeEncodeError as error:
                raise Blocked("MCP source is not valid UTF-8 text") from error
            total += encoded_size
            if total > max_chars:
                raise Blocked(
                    "MCP inline text exceeds the safe response limit. "
                    "Read a smaller line range instead of an attachment."
                )
            converted.append({"type": "text", "text": value})
        return converted

    output = dict(result)
    if "content" in output:
        output["content"] = inline_blocks(output["content"])
    # MCP structuredContent may mirror file blocks. Convert the usual mirror,
    # and refuse unrecognized nested media rather than accidentally surfacing
    # an unsanitized resource link through a parallel representation.
    for name in ("structuredContent", "structured_content"):
        original = output.get(name)
        if isinstance(original, dict) and "content" in original:
            output[name] = {
                **original,
                "content": inline_blocks(original["content"]),
            }

    def normalize_nested_blocks(value, depth=0):
        """Convert additional structuredContent mirrors without fetching a URI.

        Some MCP servers nest CallToolResult-shaped content arrays below
        structuredContent. Leaving them intact would expose attachable text
        resources, while blocking them would needlessly reject safe inline
        source text. Only recognizable MCP content arrays are normalized;
        ordinary structured JSON stays unchanged.
        """
        if depth > 24:
            raise Blocked("Nested MCP source result exceeds the safe structure limit")
        if isinstance(value, dict):
            cleaned = {}
            for key, child in value.items():
                if (key == "content" and isinstance(child, list) and
                        any(isinstance(item, dict) and item.get("type") in
                            ("text", "resource", "resource_link", "image", "audio")
                            for item in child)):
                    cleaned[key] = inline_blocks(child)
                else:
                    cleaned[key] = normalize_nested_blocks(child, depth + 1)
            return cleaned
        if isinstance(value, list):
            return [normalize_nested_blocks(item, depth + 1) for item in value]
        return value

    for name in ("structuredContent", "structured_content"):
        if name in output:
            output[name] = normalize_nested_blocks(output[name])

    def reject_remaining_media(value, depth=0):
        if depth > 24:
            raise Blocked("Nested MCP source result exceeds the safe structure limit")
        if isinstance(value, dict):
            if value.get("type") in (
                "resource", "resource_link", "image", "audio",
            ):
                raise Blocked(
                    "MCP source result includes an unconverted resource or media "
                    "block. No automatic attachment materialization."
                )
            if ("blob" in value or "data" in value) and (
                "mimeType" in value or "mime_type" in value
            ):
                raise Blocked("MCP source result includes encoded media data")
            # An embedded resource may be represented as a bare descriptor
            # (without type=resource) in arbitrary structured metadata.
            # Reject it instead of returning an attachment-capable URI or
            # base64 payload through an unrecognized nested structure.
            if ("resource" in value and
                    isinstance(value["resource"], (dict, list))):
                raise Blocked("MCP source result includes a nested file resource")
            if (isinstance(value.get("uri"), str) and
                    ("mimeType" in value or "mime_type" in value)):
                raise Blocked("MCP source result includes an unconverted resource URI")
            for child in value.values():
                reject_remaining_media(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                reject_remaining_media(child, depth + 1)

    reject_remaining_media(output)
    # Metadata can also be oversized, even if the content blocks are small.
    if len(canonical(output)) > max_chars + 32_768:
        raise Blocked(
            "MCP inline result exceeds the safe response limit. "
            "Read a smaller line range instead of an attachment."
        )
    return output


# These are read operations, not provider identities. MCP connection aliases
# are user-chosen and can be 'scm' or 'source-control' rather than 'github'.
# File-read results from ANY approved server must not surface attachable
# resource blocks. Other MCP tool calls retain their existing result behavior.
_INLINE_SOURCE_READ_TOOLS = frozenset({
    "get_file_contents", "get_file_content", "fetch_file",
    "read_file", "read_text_file", "read_repository_file",
})


def inline_source_read_tool(tool):
    return isinstance(tool, str) and tool in _INLINE_SOURCE_READ_TOOLS



def redact(value, secrets):
    text = canonical(value)
    for secret in secrets:
        for form in secret_forms(secret):
            text = text.replace(json.dumps(form)[1:-1], "[redacted]")
    return json.loads(text)


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
                "all_projects": False,
                "projects": [],
                "servers": {},
            }
        value = json.loads(self.path.read_text("utf-8"))
        value.setdefault("all_projects", False)
        return value

    def shared(self, project_id):
        cfg = self.settings()
        return bool(cfg["all_projects"] or project_id in cfg["projects"])

    def save(self, value):
        if not isinstance(value, dict) or set(value) - {"all_projects"} != {
            "enabled",
            "allow_create",
            "projects",
            "servers",
        }:
            raise ContractError(
                "MCP settings require enabled, allow_create, projects and servers"
            )
        value = {"all_projects": False, **value}
        if any(type(value[k]) is not bool for k in ("enabled", "allow_create", "all_projects")):
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
                command = spec.get("command")
                if isinstance(command, str) and command and not Path(command).is_absolute():
                    # "npx" or "uvx" as the tool instructions say: store where it is.
                    import shutil

                    found = shutil.which(command)
                    if found:
                        spec["command"] = str(Path(found).absolute())
                if (
                    not isinstance(spec.get("command"), str)
                    or not Path(spec["command"]).is_absolute()
                ):
                    raise ContractError(
                        "HA can't find that program. Use Browse to choose it."
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

    @staticmethod
    def local_clients(home=None):
        """Desktop apps on this computer whose MCP settings HA can add itself to."""
        home = Path(home or Path.home())
        if os.name == "nt":
            claude = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            claude = home / "Library" / "Application Support"
        else:
            claude = home / ".config"
        found = []
        claude = claude / "Claude" / "claude_desktop_config.json"
        if claude.exists() or claude.parent.is_dir():
            found.append(("Claude Desktop", claude))
        codex = home / ".codex" / "config.toml"
        if codex.exists() or codex.parent.is_dir():
            found.append(("Codex", codex))
        return found

    def install_local_apps(self, home=None):
        """Add HA to every detected desktop app; other servers and settings are kept."""
        results = []
        for name, path in self.local_clients(home):
            try:
                if path.suffix == ".json":
                    self.install_config(path)
                else:
                    self.install_codex(path)
                results.append({"app": name, "result": "Added. Restart " + name + " to use HA."})
            except (ContractError, OSError, ValueError) as exc:
                results.append({"app": name, "result": "Not changed: " + str(exc)})
        if not results:
            results.append({"app": "", "result": "No supported desktop app was found. Use Show connection settings to add HA by hand."})
        return {"apps": results}

    def install_codex(self, path):
        import tomllib

        begin, end = "# BEGIN Hivemind Assembly", "# END Hivemind Assembly"
        entry = self.client_config()["mcpServers"]["hivemind-assembly"]
        with self.lock:
            text = path.read_text("utf-8-sig") if path.exists() else ""
            if begin in text:
                if text.count(begin) != 1 or text.count(end) != 1:
                    raise ContractError("Unrecognized HA section; the file was not changed")
                text = re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "", text, flags=re.S)
            if re.search(r"\[mcp_servers\.hivemind-assembly(?:\]|\.)", text) or re.search(
                r'\[mcp_servers\."hivemind-assembly"', text
            ):
                raise ContractError("A server named hivemind-assembly was added by hand; it was kept")
            block = (
                begin + '\n[mcp_servers."hivemind-assembly"]\ncommand = ' + json.dumps(entry["command"])
                + "\nargs = " + json.dumps(entry["args"]) + "\n" + end + "\n"
            )
            updated = (text.rstrip() + "\n\n" if text.strip() else "") + block
            tomllib.loads(updated)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                atomic_write(path.with_name(path.name + "." + uid("backup") + ".bak"), path.read_text("utf-8-sig"))
            atomic_write(path, updated)

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
                if spec.get("transport") == "http" and not isinstance(
                    error, (Blocked, ContractError)
                ):
                    # Transport errors can quote request headers or server
                    # responses; keep only the type in results and traces.
                    raise Blocked(
                        "MCP call failed (" + type(error).__name__ + ")"
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
                        inventory = redact(inventory, [secret])
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
                # File text must not be surfaced as an MCP attachment or
                # resource link during ordinary repository source reads.
                if inline_source_read_tool(tool):
                    value = inline_github_mcp_text(value)
                if oauth_storage:
                    oauth_storage.check()
                    value = oauth_storage.redact(value)
                return redact(value, [secret]) if secret else value


class Gateway:
    """Owner-granted project access. No unrestricted application-action forwarding."""

    def __init__(self, app):
        self.app = app
        self.connections = app.connections
        from .mcp_checks import CheckRequests

        self.checks = CheckRequests(app, self.task)

    def task(self, task_id):
        if not self.connections.settings()["enabled"]:
            raise Blocked("MCP access is disabled")
        task = self.app.store.task(task_id)
        if not self.connections.shared(task["project_id"]):
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
                    for p in (
                        [row["id"] for row in self.app.store.rows("SELECT id FROM projects ORDER BY created")]
                        if cfg["all_projects"]
                        else cfg["projects"]
                    )
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
                    self.app.team.goals.prepare(task_id, db)
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
        if tool == "ha_run_checks":
            return self.checks.start(task["id"], args["request_id"])
        if tool == "ha_check_status":
            return self.checks.status(task["id"], args["request_id"])
        if tool == "ha_control":
            if args["action"] not in ("pause", "resume", "cancel"):
                raise ContractError("Expected pause, resume or cancel")
            return self.app.action("/api/control", args)
        if tool == "ha_goal":
            return {"goal": self.app.action("/api/goal", args)}
        if tool == "ha_publication_status":
            # Read-only: lets a client confirm verified checkpoints after a
            # disconnect without being able to publish or see protected inputs.
            project = task["project_id"]
            broker = self.app.broker
            listing = broker.verified_sources.listing(
                task["id"], broker.workspace(task["id"]), 5
            )
            return {
                "repository": self.app.repositories.status(project),
                "publication": (
                    broker.publications.status(project)
                    if broker.publications
                    else {"sha": None}
                ),
                "verified_snapshots": [
                    {
                        "validation": item["validation"],
                        "tool": item["tool"],
                        "current": item["current"],
                        "files": sorted(item["files"]),
                    }
                    for item in listing["snapshots"]
                ],
            }
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
    from mcp.server.mcpserver.exceptions import ToolError

    unchecked = call

    def call(tool, arguments):
        # HA's own refusals are meant for the client; the SDK hides other errors.
        try:
            return unchecked(tool, arguments)
        except (Blocked, ContractError, Conflict) as exc:
            raise ToolError(str(exc)) from exc

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
    def ha_run_checks(task: str, request_id: str) -> dict[str, Any]:
        """Start existing owner-pinned checks for a paused shared project. Retry with the same ID; no automatic rerun after interruption. Native recipes require prior owner authorization. Does not accept a task or expose holdouts."""
        return call("ha_run_checks", {"task": task, "request_id": request_id})

    @server.tool()
    def ha_check_status(task: str, request_id: str) -> dict[str, Any]:
        """Read the retained outcome of a check request without protected inputs or expected outputs."""
        return call("ha_check_status", {"task": task, "request_id": request_id})

    @server.tool()
    def ha_control(task: str, action: str) -> dict[str, Any]:
        """Pause, resume or cancel a shared task."""
        return call("ha_control", {"task": task, "action": action})

    @server.tool()
    def ha_goal(task: str, action: str = "status", max_turns: int | None = None,
                objective: str | None = None, command: str | None = None) -> dict[str, Any]:
        """Control HA's retained objective: status, start, pause, resume, clear or budget. Projects retain objectives automatically; no provider slash command is needed. max_turns=0 explicitly means unlimited. command is only for older clients."""
        if command is not None:
            if action != "status" or max_turns is not None or objective is not None:
                raise ContractError("Do not mix legacy commands and objective actions")
            return call("ha_goal", {"task": task, "command": command})
        return call("ha_goal", {"task": task, "action": action,
                                "max_turns": max_turns, "objective": objective})

    @server.tool()
    def ha_publication_status(task: str) -> dict[str, Any]:
        """Read a shared project's repository link, last published checkpoint and recent host-verified source snapshots. Read-only; safe to poll after reconnecting."""
        return call("ha_publication_status", {"task": task})

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
