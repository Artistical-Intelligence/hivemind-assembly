from __future__ import annotations
import json, sqlite3, threading, time, os
from contextlib import contextmanager
from pathlib import Path
from hivemind_assembly.core.common import canonical, uid, Conflict

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,objective TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),objective TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',owner TEXT,epoch INTEGER NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,step INTEGER NOT NULL DEFAULT 0,brief_id TEXT,next_action TEXT NOT NULL DEFAULT '',blocker TEXT NOT NULL DEFAULT '',updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,entity TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,owner TEXT NOT NULL,epoch INTEGER NOT NULL,revision INTEGER NOT NULL,tool TEXT NOT NULL,payload_hash TEXT NOT NULL,args TEXT NOT NULL,state TEXT NOT NULL,result TEXT,created REAL NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,route TEXT NOT NULL,conversation TEXT NOT NULL,payload_hash TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,response TEXT,created REAL NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reservations(scope TEXT NOT NULL,task TEXT NOT NULL,window TEXT NOT NULL,amount REAL NOT NULL,PRIMARY KEY(scope,task,window));
CREATE TABLE IF NOT EXISTS polls(scope TEXT PRIMARY KEY,last_attempt REAL NOT NULL);
CREATE TABLE IF NOT EXISTS traces(seq INTEGER PRIMARY KEY AUTOINCREMENT,identity TEXT NOT NULL UNIQUE,task_id TEXT NOT NULL,correlation TEXT NOT NULL,route TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS trace_task ON traces(task_id,seq);
CREATE INDEX IF NOT EXISTS trace_correlation ON traces(correlation,seq);
CREATE TABLE IF NOT EXISTS retry_schedule(task_id TEXT PRIMARY KEY REFERENCES tasks(id),attempt INTEGER NOT NULL,due REAL NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,revision TEXT NOT NULL,external_allowed INTEGER NOT NULL,extraction TEXT NOT NULL,sections TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY,asset_key TEXT NOT NULL,version INTEGER NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,predecessor TEXT,created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_lesson ON lessons(asset_key) WHERE status='active';
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL,classification TEXT NOT NULL,project_id TEXT,logical_name TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS project_repositories(project_id TEXT PRIMARY KEY REFERENCES projects(id),operation_id TEXT NOT NULL,owner TEXT NOT NULL COLLATE NOCASE,name TEXT NOT NULL COLLATE NOCASE,description TEXT NOT NULL,account_id INTEGER NOT NULL,marker TEXT NOT NULL,state TEXT NOT NULL,repository_id TEXT,url TEXT,error TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(owner,name));
"""


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            self.root / "controller.sqlite3",
            check_same_thread=False,
            isolation_level=None,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        with self.lock:
            self.db.executescript(SCHEMA)
            version = self.db.execute(
                "SELECT value FROM meta WHERE key='schema'"
            ).fetchone()
            if version and version[0] != "1":
                raise Conflict(
                    "Unsupported database version; restore matching application"
                )
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        if not rows:
            raise Conflict("Record not found")
        return rows[0]

    def event(self, entity, kind, payload, conn=None):
        if conn is None:
            with self.tx() as c:
                return self.event(entity, kind, payload, c)
        conn.execute(
            "INSERT INTO events(entity,kind,payload,created) VALUES(?,?,?,?)",
            (entity, kind, canonical(payload), time.time()),
        )

    def put(self, kind, key, payload, conn=None):
        if conn is None:
            with self.tx() as c:
                return self.put(kind, key, payload, c)
        old = conn.execute(
            "SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        raw = canonical(payload)
        if old and old[0] != raw:
            raise Conflict("Immutable record identity reused with changed payload")
        conn.execute(
            "INSERT OR IGNORE INTO records VALUES(?,?,?,?)",
            (kind, key, raw, time.time()),
        )
        return key

    def get(self, kind, key):
        return json.loads(
            self.one("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key))[
                "payload"
            ]
        )

    def create_project(self, name, objective, paused=False):
        p, t = uid("project"), uid("task")
        now = time.time()
        with self.tx() as c:
            c.execute(
                "INSERT INTO projects VALUES(?,?,?,0,?)", (p, name, objective, now)
            )
            c.execute(
                "INSERT INTO tasks(id,project_id,objective,status,updated) VALUES(?,?,?,?,?)",
                (t, p, objective, "paused" if paused else "queued", now),
            )
            self.event(t, "task_created", {"project_id": p}, c)
        (self.root / "projects" / p / "workspace").mkdir(parents=True)
        return self.task(t)

    def task(self, t):
        return self.one("SELECT * FROM tasks WHERE id=?", (t,))

    def project(self, p):
        return self.one("SELECT * FROM projects WHERE id=?", (p,))

    def state(self, t, status, blocker=""):
        with self.tx() as c:
            current = c.execute(
                "SELECT status,blocker FROM tasks WHERE id=?", (t,)
            ).fetchone()
            if not current:
                raise Conflict("Task missing")
            if current[0] == status and current[1] == blocker:
                return
            c.execute(
                "UPDATE tasks SET status=?,blocker=?,updated=? WHERE id=?",
                (status, blocker, time.time(), t),
            )
            self.event(t, status, {"blocker": blocker}, c)

    def backup(self, destination):
        with self.lock:
            target = sqlite3.connect(destination)
            try:
                self.db.backup(target)
            finally:
                # sqlite3's transaction context manager does not close the file.
                target.close()

    def close(self):
        with self.lock:
            self.db.close()
