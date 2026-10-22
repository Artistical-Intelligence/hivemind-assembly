"""GitHub.com device authorization and repository API; no model inference.

Uses the same repository endpoints as GitHub's MCP server. Device authorization
lets a local installation use an owner-controlled OAuth app without distributing
its client secret or borrowing credentials from a browser/ChatGPT connection.
"""

import json
import re
import sys
import threading
import time
from hashlib import sha256

import httpx

from hivemind_assembly.core.common import Blocked, ContractError


class GitHubError(Blocked):
    def __init__(self, status):
        self.status = status
        messages = {
            401: "GitHub authorization expired or was revoked. Connect GitHub again.",
            403: "GitHub denied access. Check repo scope, app permissions, organization policy or rate limits.",
            404: "GitHub repository is absent or inaccessible to this connection.",
            422: "GitHub rejected the repository name or it already exists.",
            429: "GitHub rate limit reached. Wait before checking again.",
        }
        super().__init__(
            messages.get(status, f"GitHub request failed (HTTP {status}).")
        )


class GitHubHTTP:
    """Bounded calls, no automatic mutation retry, no cross-host redirects."""

    def request(self, method, path, *, token=None, data=None, oauth=False):
        origin = "https://github.com" if oauth else "https://api.github.com"
        headers = {"Accept": "application/json", "User-Agent": "Hivemind-Assembly"}
        if not oauth:
            headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with httpx.Client(timeout=25, follow_redirects=False) as client:
                response = client.request(
                    method,
                    origin + path,
                    headers=headers,
                    **({"data": data} if oauth else {"json": data}),
                )
        except httpx.HTTPError:
            # Do not surface raw exceptions/response bodies containing credentials.
            raise Blocked(
                "GitHub connection interrupted. Check the recorded operation before retrying."
            ) from None
        if not 200 <= response.status_code < 300:
            raise GitHubError(response.status_code)
        if response.status_code in (202, 204) and not response.content:
            return {}
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise Blocked(
                "GitHub returned an invalid response; verify the operation before retrying."
            ) from None


class CredentialVault:
    """Only OS credential stores; never fall back to plaintext files."""

    def __init__(self, root, service="GitHub"):
        self.label = service
        self.account = sha256(str(root.resolve()).encode()).hexdigest()[:32]
        self.service = "HivemindAssembly." + service
        self.backend = None

    def ready(self):
        if self.backend is not None:
            return
        try:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring

                backend = WinVaultKeyring()
            elif sys.platform == "darwin":
                from keyring.backends.macOS import Keyring

                backend = Keyring()
            else:
                from keyring.backends.SecretService import Keyring

                backend = Keyring()
            if backend.priority <= 0:
                raise RuntimeError()
            if sys.platform == "win32":
                from .credential_chunks import WindowsChunks, windows_targets

                backend = WindowsChunks(backend, windows_targets)
            self.backend = backend
        except Exception:
            raise Blocked(
                f"Unlock an OS credential store (Windows Credential Manager, macOS Keychain or Linux Secret Service) before connecting {self.label}."
            ) from None

    def read(self):
        self.ready()
        try:
            value = self.backend.get_password(self.service, self.account)
            return json.loads(value) if value else None
        except Exception:
            raise Blocked(
                f"{self.label} credentials could not be read from the OS credential store."
            ) from None

    def write(self, value):
        self.ready()
        try:
            self.backend.set_password(self.service, self.account, json.dumps(value))
        except Exception:
            raise Blocked(
                f"{self.label} credentials could not be saved to the OS credential store."
            ) from None

    def clear(self):
        self.ready()
        from .credential_chunks import WindowsChunks

        if isinstance(self.backend, WindowsChunks) or self.read() is not None:
            try:
                self.backend.delete_password(self.service, self.account)
            except Exception:
                raise Blocked(
                    f"{self.label} credentials could not be removed from the OS credential store."
                ) from None


class GitHubAuth:
    def __init__(self, root, http=None, vault=None, clock=time.time):
        self.http = http or GitHubHTTP()
        self.vault = vault or CredentialVault(root)
        self.clock = clock
        self.lock = threading.RLock()
        self.pending = None
        self.cached = {"connected": False}
        # Status reads never poll GitHub or require an unlocked credential vault.

    def status(self):
        return dict(self.cached)

    def start(self, client_id, codespaces=False):
        if type(codespaces) is not bool:
            raise ContractError("Codespaces permission must be a boolean")
        if not isinstance(client_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{5,100}", client_id
        ):
            raise ContractError("Enter the public Client ID of your GitHub OAuth app.")
        with self.lock:
            self.vault.ready()
            if self.pending and self.pending["expires"] > self.clock():
                raise Blocked(
                    "A GitHub sign-in is already pending. Finish or cancel it first."
                )
            result = self.http.request(
                "POST",
                "/login/device/code",
                oauth=True,
                data={
                    "client_id": client_id,
                    "scope": "repo codespace" if codespaces else "repo",
                },
            )
            if result.get("error"):
                raise Blocked(
                    "GitHub device sign-in unavailable. Enable Device Flow on your OAuth app and check its Client ID."
                )
            if result.get("verification_uri") != "https://github.com/login/device":
                raise Blocked("Unexpected GitHub verification address.")
            interval = max(5, int(result["interval"]))
            self.pending = {
                "client_id": client_id,
                "device_code": result["device_code"],
                "expires": self.clock() + int(result["expires_in"]),
                "interval": interval,
                "next_poll": self.clock() + interval,
            }
            return {
                "user_code": result["user_code"],
                "verification_uri": result["verification_uri"],
                "expires_in": int(result["expires_in"]),
                "interval": interval,
            }

    def poll(self):
        with self.lock:
            p = self.pending
            if not p:
                raise Blocked("Start GitHub sign-in first.")
            if self.clock() >= p["expires"]:
                self.pending = None
                raise Blocked("GitHub sign-in expired. Start again.")
            if self.clock() < p["next_poll"]:
                return {"status": "pending", "interval": p["interval"]}
            p["next_poll"] = self.clock() + p["interval"]
            result = self.http.request(
                "POST",
                "/login/oauth/access_token",
                oauth=True,
                data={
                    "client_id": p["client_id"],
                    "device_code": p["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            error = result.get("error")
            if error in ("authorization_pending", "slow_down"):
                if error == "slow_down":
                    p["interval"] += 5
                    p["next_poll"] = self.clock() + p["interval"]
                return {"status": "pending", "interval": p["interval"]}
            if error or not result.get("access_token"):
                self.pending = None
                raise Blocked(
                    "GitHub sign-in was denied or expired. Start again when ready."
                )
            self.pending = None
            if "repo" not in result.get("scope", "").replace(",", " ").split():
                raise Blocked(
                    "GitHub did not grant repo scope; reconnect and authorize repository access."
                )
            user = self.http.request("GET", "/user", token=result["access_token"])
            record = self._record(result, p["client_id"], user)
            self.vault.write(record)
            self.cached = {
                "connected": True,
                "login": user["login"],
                "account_id": user["id"],
            }
            return {"status": "connected", **self.cached}

    def _record(self, response, client_id, user):
        return {
            "access_token": response["access_token"],
            "refresh_token": response.get("refresh_token"),
            "expires_at": (
                self.clock() + int(response["expires_in"])
                if response.get("expires_in")
                else None
            ),
            "client_id": client_id,
            "account_id": user["id"],
            "login": user["login"],
        }

    def credentials(self):
        with self.lock:
            saved = self.vault.read()
            if not saved:
                raise Blocked(
                    "Connect GitHub in Settings before creating repositories."
                )
            if saved.get("expires_at") and self.clock() >= saved["expires_at"] - 60:
                if not saved.get("refresh_token"):
                    raise Blocked("GitHub authorization expired. Connect again.")
                result = self.http.request(
                    "POST",
                    "/login/oauth/access_token",
                    oauth=True,
                    data={
                        "client_id": saved["client_id"],
                        "grant_type": "refresh_token",
                        "refresh_token": saved["refresh_token"],
                    },
                )
                if result.get("error") or not result.get("access_token"):
                    raise Blocked(
                        "GitHub authorization could not be refreshed. Connect again."
                    )
                user = self.http.request("GET", "/user", token=result["access_token"])
                if user["id"] != saved["account_id"]:
                    raise Blocked("GitHub account changed during token refresh.")
                saved = self._record(result, saved["client_id"], user)
                self.vault.write(saved)
            self.cached = {
                "connected": True,
                "login": saved["login"],
                "account_id": saved["account_id"],
            }
            return saved

    def disconnect(self):
        with self.lock:
            self.pending = None
            self.vault.clear()
            self.cached = {"connected": False}
            return self.status()

    def cancel(self):
        with self.lock:
            self.pending = None
            return {"cancelled": True}


class GitHubClient:
    def __init__(self, auth):
        self.auth = auth
        self.session = threading.local()

    def identity(self):
        saved = self.auth.credentials()
        user = self.auth.http.request("GET", "/user", token=saved["access_token"])
        if user["id"] != saved["account_id"]:
            raise Blocked(
                "GitHub identity differs from the authorized account. Reconnect."
            )
        self.session.token = saved["access_token"]
        return {"login": user["login"], "id": user["id"]}

    def lookup(self, owner, name):
        try:
            return self.auth.http.request(
                "GET", f"/repos/{owner}/{name}", token=self.session.token
            )
        except GitHubError as error:
            if error.status == 404:
                return None  # Absence OR loss of access; never a reason to replay an uncertain POST.
            raise

    def create(self, owner, name, description, organization=False):
        endpoint = f"/orgs/{owner}/repos" if organization else "/user/repos"
        return self.auth.http.request(
            "POST",
            endpoint,
            token=self.session.token,
            data={
                "name": name,
                "description": description,
                "private": True,
                "auto_init": False,
            },
        )

    def describe(self, owner, name, description):
        return self.auth.http.request(
            "PATCH",
            f"/repos/{owner}/{name}",
            token=self.session.token,
            data={"description": description},
        )

    def git(self, owner, name, method, endpoint, data=None):
        """Repository-scoped Git data calls. No redirects or mutation retry."""
        return self.auth.http.request(
            method,
            f"/repos/{owner}/{name}/{endpoint}",
            token=self.session.token,
            data=data,
        )

    def head(self, owner, name, branch):
        from urllib.parse import quote

        try:
            ref = self.git(
                owner, name, "GET", "git/ref/heads/" + quote(branch, safe="")
            )
            return ref["object"]["sha"]
        except GitHubError as error:
            if error.status in (404, 409):
                return None
            raise
