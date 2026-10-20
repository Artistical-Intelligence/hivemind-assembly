"""Tag catalog and durable task grants. Classification never reads item content."""

import json
import re
from hivemind_assembly.core.common import (
    Blocked,
    Conflict,
    ContractError,
    canonical,
    digest,
    uid,
)


class KnowledgeScopes:
    def __init__(self, store):
        self.store = store

    def catalog(self):
        tags = self.store.rows(
            "SELECT id,label,description FROM knowledge_tags WHERE id!='unclassified' ORDER BY id"
        )
        return {"tags": tags, "revision": digest(tags)}

    def create_tag(self, key, label, description=""):
        if not isinstance(key, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,63}", key
        ):
            raise ContractError(
                "Tag IDs use 1–64 lowercase letters, numbers, underscores or hyphens"
            )
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
            raise ContractError("Tag label must contain 1–100 characters")
        if not isinstance(description, str) or len(description) > 300:
            raise ContractError(
                "Category descriptions must fit 300 characters; do not put source material here"
            )
        with self.store.tx() as db:
            old = db.execute(
                "SELECT label,description FROM knowledge_tags WHERE id=?", (key,)
            ).fetchone()
            if old and tuple(old) != (label.strip(), description):
                raise Conflict("Tag ID already exists with different category metadata")
            if not old:
                if (
                    db.execute("SELECT COUNT(*) FROM knowledge_tags").fetchone()[0]
                    >= 512
                ):
                    raise Blocked(
                        "Tag catalog is full; consolidate categories before adding more"
                    )
                db.execute(
                    "INSERT INTO knowledge_tags VALUES(?,?,?)",
                    (key, label.strip(), description),
                )
        return key

    def validate_tags(self, tags, *, allow_empty=False):
        if (
            not isinstance(tags, list)
            or len(tags) > 32
            or (not tags and not allow_empty)
        ):
            raise ContractError(
                "Select up to 32 existing tags; material requires at least one"
            )
        if any(not isinstance(tag, str) for tag in tags) or len(set(tags)) != len(tags):
            raise ContractError("Tag IDs must be unique strings")
        known = {row["id"] for row in self.store.rows("SELECT id FROM knowledge_tags")}
        if set(tags) - known:
            raise ContractError(
                "Select existing tags only; project classification cannot create tags"
            )
        return sorted(tags)

    def assign(self, kind, item_id, tags):
        if kind not in ("source", "lesson", "skill"):
            raise ContractError("Tag assignments apply to sources, lessons or skills")
        tags = self.validate_tags(tags)
        if kind in ("source", "lesson"):
            self.store.one(f"SELECT id FROM {kind + 's'} WHERE id=?", (item_id,))
        elif not self.store.rows(
            "SELECT 1 FROM records WHERE kind='knowledge_skill' AND id=?", (item_id,)
        ):
            raise ContractError("Unknown skill")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO knowledge_assignments VALUES(?,?,?) ON CONFLICT(kind,item_id) DO UPDATE SET tags=excluded.tags",
                (kind, item_id, canonical(tags)),
            )
            self.store.event(
                item_id, "knowledge_tags_assigned", {"kind": kind, "tags": tags}, db
            )
        return {"kind": kind, "id": item_id, "tags": tags}

    def tags(self, kind, item_id):
        rows = self.store.rows(
            "SELECT tags FROM knowledge_assignments WHERE kind=? AND item_id=?",
            (kind, item_id),
        )
        return json.loads(rows[0]["tags"]) if rows else ["unclassified"]

    def migrate(self):
        """Old untagged material is retained privately, never implicitly granted."""
        self.create_tag("unclassified", "Awaiting classification")
        with self.store.tx() as db:
            for kind in ("source", "lesson"):
                db.execute(
                    f"INSERT OR IGNORE INTO knowledge_assignments SELECT ?,id,? FROM {kind + 's'}",
                    (kind, canonical(["unclassified"])),
                )

    def register_skills(self, domain, skills):
        self.migrate()
        for skill in skills:
            key = domain + ":" + skill["id"]
            # Immutable versions allow updated bundled skills without resetting owner tags.
            self.store.put(
                "knowledge_skill", key, {"domain": domain, "id": skill["id"]}
            )
            version = digest(skill)
            prior = self.store.rows(
                "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
                ("knowledge_skill_version:" + key,),
            )
            if not prior or json.loads(prior[0]["payload"])["hash"] != version:
                self.store.put(
                    "knowledge_skill_version:" + key,
                    uid("skill_version"),
                    {"hash": version},
                )
            if self.store.rows(
                "SELECT 1 FROM knowledge_assignments WHERE kind='skill' AND item_id=?",
                (key,),
            ):
                continue
            tags = skill.get("tags") or skill.get("scope") or [domain]
            for tag in tags:
                if not self.store.rows(
                    "SELECT 1 FROM knowledge_tags WHERE id=?", (tag,)
                ):
                    self.create_tag(tag, tag.replace("_", " ").replace("-", " "))
            self.assign("skill", key, tags)

    def objective_hash(self, task):
        row = self.store.task(task)
        return digest(
            {
                "task": row["objective"],
                "project": self.store.project(row["project_id"])["objective"],
            }
        )

    def status(self, task):
        rows = self.store.rows(
            "SELECT * FROM knowledge_scopes WHERE task_id=?", (task,)
        )
        if not rows or rows[0]["objective_hash"] != self.objective_hash(task):
            return {"task_id": task, "selected": False, "tags": []}
        return {**rows[0], "selected": True, "tags": json.loads(rows[0]["tags"])}

    def select(self, task, tags, catalog_revision, reason=""):
        if catalog_revision != self.catalog()["revision"]:
            raise Conflict("Tag catalog changed during classification; classify again")
        tags = self.validate_tags(tags, allow_empty=True)
        if "unclassified" in tags:
            raise ContractError("Unclassified material cannot be assigned to a project")
        if not isinstance(reason, str) or len(reason) > 1000:
            raise ContractError("Scope reason must fit 1000 characters")
        objective_hash = self.objective_hash(task)
        with self.store.tx() as db:
            old = db.execute(
                "SELECT * FROM knowledge_scopes WHERE task_id=?", (task,)
            ).fetchone()
            revision = old["revision"] + 1 if old else 1
            if (
                old
                and old["tags"] == canonical(tags)
                and old["objective_hash"] == objective_hash
            ):
                return self.status(task)
            db.execute(
                "INSERT INTO knowledge_scopes VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET tags=excluded.tags,objective_hash=excluded.objective_hash,catalog_hash=excluded.catalog_hash,revision=excluded.revision,reason=excluded.reason",
                (
                    task,
                    canonical(tags),
                    objective_hash,
                    catalog_revision,
                    revision,
                    reason,
                ),
            )
            db.execute("UPDATE tasks SET brief_id=NULL WHERE id=?", (task,))
            self.store.event(
                task,
                "knowledge_scope_selected",
                {"tags": tags, "revision": revision, "reason": reason},
                db,
            )
        return self.status(task)

    def require(self, task):
        if not task:
            raise Blocked(
                "Task knowledge scope must be selected before reading material"
            )
        scope = self.status(task)
        if not scope["selected"]:
            raise Blocked(
                "Task knowledge scope must be selected before reading material"
            )
        return scope

    def allowed(self, task, kind, item_id):
        scope = self.require(task)
        return bool(set(scope["tags"]) & set(self.tags(kind, item_id)))

    def check(self, task, kind, item_id):
        if not self.allowed(task, kind, item_id):
            raise Blocked("Material is outside the task's selected knowledge tags")

    def fingerprint(self, task):
        """Rebind conversations when grants, permissions, or active material change."""
        scope = self.require(task)
        items = []
        for row in self.store.rows(
            "SELECT * FROM knowledge_assignments ORDER BY kind,item_id"
        ):
            if not set(scope["tags"]) & set(json.loads(row["tags"])):
                continue
            kind, key = row["kind"], row["item_id"]
            if kind == "source":
                evidence = self.store.rows(
                    "SELECT revision,external_allowed FROM sources WHERE id=?", (key,)
                )
            elif kind == "lesson":
                evidence = self.store.rows(
                    "SELECT status,payload FROM lessons WHERE id=?", (key,)
                )
                evidence += self.store.rows(
                    "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
                    ("lesson_permission:" + key,),
                )
            else:
                evidence = self.store.rows(
                    "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
                    ("knowledge_skill_version:" + key,),
                )
            items.append({**row, "version": digest(evidence)})
        return digest({"task": task, "scope": scope, "items": items})
