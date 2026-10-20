"""Atomic generations for Windows Credential Manager's small credential blobs.

Every piece remains in the OS vault. The manifest is switched only after all
pieces are stored. Interrupted/orphan generations are collected on write/forget.
"""

import hashlib
import json
import re
import uuid


class WindowsChunks:
    def __init__(self, backend, targets):
        self.backend, self.targets = backend, targets

    @staticmethod
    def names(service, username):
        owner = hashlib.sha256(username.encode()).hexdigest()[:32]
        return service + ".ha-root." + owner, service + ".ha-parts." + owner + "."

    def get_password(self, service, username):
        root, prefix = self.names(service, username)
        manifest = self.backend.get_password(root, username)
        if manifest is None:
            return self.backend.get_password(service, username)  # Legacy record.
        info = json.loads(manifest)
        if (
            info.get("version") != 1
            or not re.fullmatch(r"[0-9a-f]{32}", info.get("generation", ""))
            or type(info.get("count")) is not int
            or not 1 <= info["count"] <= 2048
        ):
            raise ValueError("Invalid credential generation")
        parts = [
            self.backend.get_password(
                prefix + info["generation"] + "." + str(i), username
            )
            for i in range(info["count"])
        ]
        if any(p is None for p in parts):
            raise ValueError("Incomplete credential generation")
        raw = "".join(parts)
        if hashlib.sha256(raw.encode()).hexdigest() != info["sha256"]:
            raise ValueError("Credential generation hash mismatch")
        return raw

    def set_password(self, service, username, password):
        root, prefix = self.names(service, username)
        parts = [password[i : i + 500] for i in range(0, len(password), 500)] or [""]
        if len(parts) > 2048:
            raise ValueError("Credential exceeds storage limit")
        generation = uuid.uuid4().hex
        keep = prefix + generation + "."
        # Keep staged pieces after an ambiguous write failure. The manifest may
        # already have switched; deleting them could destroy the new credential.
        # Collection on the next write/forget removes unreferenced generations.
        for i, part in enumerate(parts):
            self.backend.set_password(keep + str(i), username, part)
        self.backend.set_password(
            root,
            username,
            json.dumps(
                {
                    "version": 1,
                    "generation": generation,
                    "count": len(parts),
                    "sha256": hashlib.sha256(password.encode()).hexdigest(),
                }
            ),
        )
        # The new manifest is already durable. A cleanup failure cannot undo it.
        try:
            self.collect(prefix, username, keep)
            if self.backend.get_password(service, username) is not None:
                self.backend.delete_password(service, username)
        except Exception:
            pass

    def collect(self, prefix, username, keep=""):
        for name in self.targets(prefix):
            if name.startswith(prefix) and not (keep and name.startswith(keep)):
                if self.backend.get_password(name, username) is not None:
                    self.backend.delete_password(name, username)

    def delete_password(self, service, username):
        root, prefix = self.names(service, username)
        self.collect(prefix, username)
        for name in (root, service):
            if self.backend.get_password(name, username) is not None:
                self.backend.delete_password(name, username)


def windows_targets(prefix):
    import win32cred
    import pywintypes

    try:
        return [item["TargetName"] for item in win32cred.CredEnumerate(prefix + "*", 0)]
    except pywintypes.error as error:
        if error.winerror == 1168:  # No matching credential.
            return []
        raise
