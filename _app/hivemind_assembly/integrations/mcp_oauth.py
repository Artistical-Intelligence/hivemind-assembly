"""Native-app OAuth wiring around the official MCP SDK, with private storage."""

import asyncio
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from hivemind_assembly.core.common import Blocked, ContractError, digest
from .github import CredentialVault


class OAuthStorage:
    def __init__(self, manager, server, spec):
        self.manager, self.server = manager, server
        self.url, self.mode = spec["url"], spec["auth"]
        self.generation = manager.generations.get(server, 0)
        self.vault = CredentialVault(
            manager.connections.store.root, "MCP.OAuth." + server
        )
        self.secrets = set()
        self.provider = None

    def check(self):
        current = self.manager.connections.settings()["servers"].get(self.server, {})
        if (
            self.manager.closed
            or current.get("url") != self.url
            or current.get("auth") != self.mode
            or self.manager.generations.get(self.server, 0) != self.generation
        ):
            raise Blocked(
                "MCP OAuth connection changed; reconnect the current endpoint"
            )

    def read(self):
        with self.manager.connections.lock:
            self.check()
            value = (
                self.vault.read()
                if self.mode == "oauth_vault"
                else self.manager.credentials.get(self.server)
            )
            if value and value.get("url") != self.url:
                raise Blocked("MCP OAuth credential belongs to a different endpoint")
            value = json.loads(json.dumps(value or {"url": self.url}))
            self.remember_secrets(value)
            return value

    def remember_secrets(self, value):
        for group, fields in (
            ("tokens", ("access_token", "refresh_token")),
            ("client", ("client_secret",)),
        ):
            for field in fields:
                if value.get(group, {}).get(field):
                    self.secrets.add(value[group][field])

    def write(self, field, data):
        with self.manager.connections.lock:
            value = self.read()
            value[field] = data
            if field == "tokens":
                value["expires_at"] = (
                    time.time() + data["expires_in"]
                    if data.get("expires_in") is not None
                    else None
                )
                if self.provider is not None:
                    context = self.provider.context
                    value["discovery"] = {
                        "authorization_server": context.auth_server_url,
                        "metadata": (
                            context.oauth_metadata.model_dump(mode="json")
                            if context.oauth_metadata
                            else None
                        ),
                        "resource": (
                            context.protected_resource_metadata.model_dump(mode="json")
                            if context.protected_resource_metadata
                            else None
                        ),
                    }
            self.remember_secrets(value)
            if self.mode == "oauth_vault":
                self.vault.write(value)
            else:
                self.manager.credentials[self.server] = value

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        value = self.read()
        token = value.get("tokens")
        if token is not None and value.get("expires_at") is not None:
            token["expires_in"] = max(0, int(value["expires_at"] - time.time()))
        return OAuthToken.model_validate(token) if token else None

    async def set_tokens(self, tokens):
        self.write("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        value = self.read().get("client")
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, client_info):
        self.write("client", client_info.model_dump(mode="json"))

    def redact(self, value):
        raw = json.dumps(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            raw = raw.replace(secret, "[redacted]")
        return json.loads(raw)


class LoopbackCallback:
    """One state-bound callback; authorization codes never enter logs or storage."""

    def __init__(self):
        self.server = None
        self.expected_state = None
        self.future = None
        self.clients = set()
        self.closing = False

    async def start(self, port=0):
        self.future = asyncio.get_running_loop().create_future()
        self.server = await asyncio.start_server(
            self.handle, "127.0.0.1", port, limit=8192
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/oauth/callback"
        return self.url

    def expect(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise Blocked("OAuth authorization requires HTTPS or a local server")
        values = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.username
            or parsed.password
            or parsed.fragment
            or len(values.get("state", [])) != 1
            or not values["state"][0]
        ):
            raise Blocked("OAuth authorization did not provide a unique state")
        if values.get("redirect_uri") != [self.url]:
            raise Blocked("OAuth authorization changed the loopback callback")
        if self.future.done():
            self.future = asyncio.get_running_loop().create_future()
        self.expected_state = values["state"][0]

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        try:
            if not self.closing:
                await self._handle(reader, writer)
        except ConnectionError:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.clients.discard(task)

    async def _handle(self, reader, writer):
        status, body = "400 Bad Request", "Invalid or expired authorization callback."
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(raw) > 8192:
                raise ValueError()
            lines = raw.decode("ascii").split("\r\n")
            method, target, version = lines[0].split(" ")
            headers = [line.split(":", 1) for line in lines[1:] if line]
            hosts = [v.strip() for k, v in headers if k.lower() == "host"]
            parsed = urlsplit(target)
            query = parse_qs(parsed.query, keep_blank_values=True)
            valid = (
                method == "GET"
                and version == "HTTP/1.1"
                and hosts == [f"127.0.0.1:{self.port}"]
                and not parsed.scheme
                and not parsed.netloc
                and not parsed.fragment
                and parsed.path == "/oauth/callback"
                and all(len(v) == 1 for v in query.values())
                and bool(self.expected_state)
                and secrets.compare_digest(
                    query.get("state", [""])[0], self.expected_state
                )
                and not self.future.done()
            )
            if valid and query.get("error"):
                self.future.set_result({"denied": True})
                status, body = (
                    "200 OK",
                    "Authorization was not granted. Return to Hivemind Assembly.",
                )
            elif valid and query.get("code", [""])[0]:
                self.future.set_result(
                    {
                        "code": query["code"][0],
                        "state": query["state"][0],
                        "iss": query.get("iss", [None])[0],
                    }
                )
                status, body = (
                    "200 OK",
                    "Authorization received. You can return to Hivemind Assembly.",
                )
        except (
            ValueError,
            UnicodeError,
            asyncio.TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        try:
            payload = body.encode()
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(payload)}\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nConnection: close\r\n\r\n"
                ).encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def result(self):
        from mcp.shared.auth import AuthorizationCodeResult

        result = await self.future
        if result.get("denied"):
            raise Blocked("MCP authorization was not granted")
        return AuthorizationCodeResult.model_validate(result)

    async def close(self):
        self.closing = True
        if self.server:
            self.server.close()
        clients = list(self.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
        if self.future and not self.future.done():
            self.future.cancel()


class OAuthManager:
    def __init__(self, connections):
        self.connections = connections
        self.credentials, self.generations, self.states, self.futures = {}, {}, {}, {}
        self.open_page = self.submit = None
        self.tasks = set()
        self.closed = False

    def status(self):
        with self.connections.lock:
            return [{"server": key, **value} for key, value in self.states.items()]

    def start(self, server, remember=False, client_id=None, port=0):
        if self.closed:
            raise Blocked("HA is shutting down")
        if (
            type(remember) is not bool
            or type(port) is not int
            or not 0 <= port <= 65535
        ):
            raise ContractError(
                "Choose session/vault storage and a valid callback port"
            )
        if client_id is not None and (
            not isinstance(client_id, str) or not 1 <= len(client_id) <= 1000
        ):
            raise ContractError("Client ID must be a nonempty string")
        with self.connections.lock:
            old = self.futures.get(server)
            if old and not old.done():
                return {"server": server, **self.states[server]}
            cfg = self.connections.settings()
            spec = cfg["servers"].get(server)
            if not spec or spec["transport"] != "http":
                raise Blocked("Save an HTTP MCP connection before authorizing it")
            if self.submit is None or self.open_page is None:
                raise Blocked(
                    "MCP browser authorization requires the running HA application"
                )
            if remember:
                CredentialVault(
                    self.connections.store.root, "MCP.OAuth." + server
                ).ready()
            mode = "oauth_vault" if remember else "oauth_session"
            retained = None
            if spec.get("auth") == mode:
                try:
                    retained = OAuthStorage(self, server, spec).read().get("client")
                except Blocked:
                    pass  # A changed endpoint requires fresh authorization.
            if retained and retained.get("redirect_uris"):
                uri = urlsplit(retained["redirect_uris"][0])
                reusable = (
                    uri.scheme == "http"
                    and uri.hostname == "127.0.0.1"
                    and uri.path == "/oauth/callback"
                    and uri.port
                    and port in (0, uri.port)
                    and (client_id is None or client_id == retained["client_id"])
                )
            else:
                reusable = False
            if reusable:
                port = uri.port
                self.generations[server] = self.generations.get(server, 0) + 1
            else:
                # Switching storage never copies secrets into settings or disk.
                self.forget(server)
            spec["auth"] = mode
            self.connections.save(cfg)
            self.states[server] = {"stage": "connecting"}
            self.futures[server] = self.submit(
                self.run(server, dict(spec), client_id, port)
            )
            return {"server": server, "stage": "connecting"}

    def forget(self, server):
        with self.connections.lock:
            spec = self.connections.settings()["servers"].get(server, {})
            if spec.get("auth") == "oauth_vault":
                CredentialVault(
                    self.connections.store.root, "MCP.OAuth." + server
                ).clear()
            elif spec.get("auth") == "vault":
                CredentialVault(self.connections.store.root, "MCP." + server).clear()
            self.generations[server] = self.generations.get(server, 0) + 1
            self.credentials.pop(server, None)
            self.connections.session_credentials.pop(server, None)
            future = self.futures.get(server)
            if future and not future.done():
                future.cancel()
            self.states.pop(server, None)

    async def provider(self, server, spec, callback=None, client_id=None):
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import (
            OAuthClientInformationFull,
            OAuthClientMetadata,
            OAuthMetadata,
            ProtectedResourceMetadata,
        )

        storage = OAuthStorage(self, server, spec)
        client = await storage.get_client_info()
        redirect = (
            callback.url
            if callback
            else (
                str(client.redirect_uris[0])
                if client and client.redirect_uris
                else None
            )
        )
        if not redirect:
            raise Blocked("Connect this MCP server with browser authorization first")
        metadata = OAuthClientMetadata(
            client_name="Hivemind Assembly",
            redirect_uris=[redirect],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        )
        if client_id and (client is None or client.client_id != client_id):
            await storage.set_client_info(
                OAuthClientInformationFull(**metadata.model_dump(), client_id=client_id)
            )

        async def redirect_handler(url):
            if callback is None:
                raise Blocked(
                    "MCP authorization needs renewal; reconnect in Connections"
                )
            if callback.server is None:
                await callback.start(callback.port)
            callback.expect(url)
            self.states[server] = {"stage": "authorization", "callback": callback.url}
            await self.open_page("mcp-oauth-" + digest(server)[:20], url)

        class PersistentProvider(OAuthClientProvider):
            async def _initialize(self):
                # SDK 2.3 loads tokens but does not reconstruct their original
                # deadline or discovery endpoints. Preserve both across clients
                # so refresh never falls back to an unrelated resource /token.
                await super()._initialize()
                saved = storage.read().get("discovery", {})
                if saved.get("metadata"):
                    self.context.oauth_metadata = OAuthMetadata.model_validate(
                        saved["metadata"]
                    )
                    self.context.auth_server_url = saved.get("authorization_server")
                    if saved.get("resource"):
                        self.context.protected_resource_metadata = (
                            ProtectedResourceMetadata.model_validate(saved["resource"])
                        )
                if self.context.current_tokens:
                    self.context.update_token_expiry(self.context.current_tokens)
                    if (
                        not self.context.is_token_valid()
                        and not self.context.oauth_metadata
                    ):
                        raise Blocked(
                            "MCP refresh metadata is unavailable; reconnect in Connections"
                        )

        provider = PersistentProvider(
            server_url=spec["url"],
            client_metadata=metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback.result if callback else None,
        )
        storage.provider = provider
        return provider, storage

    async def run(self, server, spec, client_id, port):
        self.tasks.add(asyncio.current_task())
        callback = LoopbackCallback()
        generation = self.generations.get(server, 0)
        try:
            async with asyncio.timeout(600):
                if port:
                    # Reuse a registered redirect without opening its listener
                    # unless the provider actually needs interactive consent.
                    callback.port = port
                    callback.url = f"http://127.0.0.1:{port}/oauth/callback"
                else:
                    await callback.start()
                provider, storage = await self.provider(
                    server, spec, callback, client_id
                )
                tools = await self.connections.external(
                    server, oauth_setup=(provider, storage)
                )
                storage.check()
                self.states[server] = {
                    "stage": "connected",
                    "tools": len(tools),
                    "storage": (
                        "OS credential store"
                        if spec["auth"] == "oauth_vault"
                        else "session only"
                    ),
                }
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Provider exceptions can include token response bodies. Retain no
            # response text, callback query, authorization code, or tokens.
            if self.generations.get(server, 0) == generation:
                self.states[server] = {
                    "stage": "attention",
                    "reason": "MCP authorization did not complete ("
                    + type(error).__name__
                    + "). Check the provider's browser page and connection settings, then reconnect.",
                }
        finally:
            await callback.close()
            self.tasks.discard(asyncio.current_task())

    def close(self):
        self.closed = True
        for server in self.generations:
            self.generations[server] += 1
        for future in self.futures.values():
            future.cancel()
        self.credentials.clear()

    async def drain(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
