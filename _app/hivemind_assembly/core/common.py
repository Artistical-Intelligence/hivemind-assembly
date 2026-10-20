from __future__ import annotations
import hashlib, json, os, re, tempfile, uuid
from pathlib import Path


class ContractError(ValueError):
    pass


class Blocked(ContractError):
    pass


class Retryable(Blocked):
    """A retained operation can be observed again without authorizing a resend."""


class WaitingForSignIn(Blocked):
    """Native authentication must finish; retained work resumes without resending."""


class AllowanceUnavailable(Blocked):
    """Reasoning waits for the scheduled allowance observation, not user repair."""


class Conflict(ContractError):
    pass


class InstanceLock:
    """Keep one controller host per data directory across platforms."""

    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.file = open(Path(root) / "host.lock", "a+b")
        try:
            # Windows byte-range locks forbid even reading the locked byte.
            # Inspect metadata instead so contention reaches the lock operation.
            if os.fstat(self.file.fileno()).st_size == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise Blocked(
                "Another workbench host already owns this data directory"
            ) from error

    def close(self):
        if self.file.closed:
            return
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def uid(prefix="id"):
    return prefix + "_" + uuid.uuid4().hex


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def scoped(root, relative):
    root = Path(root).resolve()
    p = (root / relative).resolve()
    if p == root or not p.is_relative_to(root):
        raise ContractError("Path outside allowed project scope")
    if Path(relative).is_absolute():
        raise ContractError("Only relative project paths are accepted")
    return p


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", value):
        raise ContractError("Invalid identifier")
    return value
