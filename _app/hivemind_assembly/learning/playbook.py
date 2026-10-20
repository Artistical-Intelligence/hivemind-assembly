"""Evidence-linked, localized playbook edits; proposals never self-promote.

The delta design follows ACE's grow-and-refine approach. Existing entries retain
their identities and exact content unless an edit explicitly names them. Model
procedure improvements still require separate rollout and holdout evaluation.
"""

import copy
from .engine import Learning
import json
import re
import time
from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    Conflict,
    canonical,
    digest,
)


def apply_delta(entries, edits):
    if (
        not isinstance(entries, dict)
        or not isinstance(edits, list)
        or not 1 <= len(edits) <= 16
    ):
        raise ContractError(
            "Playbook requires an entry mapping and 1–16 localized edits"
        )
    updated = copy.deepcopy(entries)
    touched = set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {
            "action",
            "id",
            "entry",
            "expected_hash",
        }:
            raise ContractError("Invalid playbook edit")
        key, action = edit.get("id"), edit.get("action")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", key)
            or key in touched
        ):
            raise ContractError("Edits require unique stable entry IDs")
        touched.add(key)
        if action not in ("add", "replace", "remove"):
            raise ContractError("Playbook edit must add, replace or remove")
        if action == "add":
            if key in updated or edit.get("expected_hash") is not None:
                raise Conflict("Cannot add an existing playbook entry")
        elif key not in updated or digest(updated[key]) != edit.get("expected_hash"):
            raise Conflict("Playbook entry changed before the proposed edit")
        if action == "remove":
            del updated[key]
            continue
        entry = edit.get("entry")
        required = {"text", "conditions", "exceptions", "evidence"}
        if not isinstance(entry, dict) or set(entry) != required:
            raise ContractError(
                "Every entry must preserve text, conditions, exceptions and evidence"
            )
        if not isinstance(entry["text"], str) or not entry["text"].strip():
            raise ContractError("Playbook entry text is required")
        for field in ("conditions", "exceptions", "evidence"):
            if not isinstance(entry[field], list) or any(
                not isinstance(x, str) for x in entry[field]
            ):
                raise ContractError(
                    "Playbook conditions, exceptions and evidence must be lists of strings"
                )
        if not entry["evidence"]:
            raise ContractError("Playbook edits require retained evidence")
        updated[key] = copy.deepcopy(entry)
    fingerprints = [
        digest({**e, "text": " ".join(e["text"].lower().split()), "evidence": []})
        for e in updated.values()
    ]
    if len(set(fingerprints)) != len(fingerprints):
        raise Conflict("Duplicate playbook entries must be merged under one identity")
    if not updated or len(updated) > 256 or len(canonical(updated)) > 128000:
        raise ContractError("Playbook must retain 1–256 entries within 128 KB")
    return updated


class Playbook:
    def __init__(self, store):
        self.store = store

    def propose(self, task, base_id, edits, evidence_ids=None):
        """Worker edits an active asset using actual operations from its own task."""
        key = "lesson_" + digest(
            {"task": task, "base": base_id, "edits": edits, "evidence": evidence_ids}
        )
        with self.store.tx() as c:
            if c.execute("SELECT 1 FROM lessons WHERE id=?", (key,)).fetchone():
                return {
                    "lesson": key,
                    "status": "candidate",
                    "requires": "Independent regression and holdout evaluation before promotion",
                }
            row = c.execute("SELECT * FROM lessons WHERE id=?", (base_id,)).fetchone()
            if (
                not row
                or row["status"] != "active"
                or row["kind"] not in ("knowledge", "procedure")
            ):
                raise Blocked(
                    "Localized edits require an active knowledge or procedure baseline"
                )
            payload = json.loads(row["payload"])
            entries = payload["content"]
            if not isinstance(entries, dict) or not isinstance(
                entries.get("entries"), dict
            ):
                raise Blocked("This asset does not have a structured playbook")
            content = apply_delta(entries["entries"], edits)
            if evidence_ids is not None and (
                not isinstance(evidence_ids, list)
                or any(not isinstance(x, str) for x in evidence_ids)
            ):
                raise ContractError("Proposal evidence must be operation IDs")
            new_evidence = set(evidence_ids or [])
            for edit in edits:
                for evidence in edit.get("entry", {}).get("evidence", []):
                    new_evidence.add(evidence)
            for evidence in new_evidence:
                op = c.execute(
                    "SELECT state FROM operations WHERE id=? AND task_id=?",
                    (evidence, task),
                ).fetchone()
                if not op or op[0] not in ("completed", "saved"):
                    raise Blocked(
                        "Playbook edits must cite successful operations from the current task"
                    )
            if not new_evidence:
                raise Blocked("Playbook proposal requires fresh execution evidence")
            # Baseline conditions, export permissions and dependency bindings cannot
            # be widened by a worker's text edit.
            payload.update(
                content={**entries, "entries": content},
                evidence=sorted(set(payload["evidence"]) | new_evidence),
                delta={"base": base_id, "edits": edits, "task_id": task},
            )
            version = c.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM lessons WHERE asset_key=?",
                (row["asset_key"],),
            ).fetchone()[0]
            c.execute(
                "INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?)",
                (
                    key,
                    row["asset_key"],
                    version,
                    row["kind"],
                    "candidate",
                    canonical(payload),
                    base_id,
                    time.time(),
                ),
            )
            c.execute(
                "INSERT INTO knowledge_assignments SELECT 'lesson',?,tags FROM knowledge_assignments WHERE kind='lesson' AND item_id=?",
                (key, base_id),
            )
            self.store.event(
                task, "playbook_candidate", {"lesson": key, "base": base_id}, c
            )
            return {
                "lesson": key,
                "status": "candidate",
                "requires": "Independent regression and holdout evaluation before promotion",
            }


def select_context(
    store, domain, query="", external=False, route=None, max_chars=16000, task=None
):
    """Rank applicable assets, retain exceptions, and explain every exclusion."""
    if type(max_chars) is not int or not 512 <= max_chars <= 128000:
        raise ContractError("Learning context budget must be 512–128000 characters")
    from .scopes import KnowledgeScopes

    scopes = KnowledgeScopes(store)
    if task is not None or external:
        scopes.require(task)
    terms = set(re.findall(r"[a-z0-9_]+", query.lower()))
    candidates, omitted = [], []
    for row in store.rows(
        "SELECT * FROM lessons WHERE status='active' ORDER BY created DESC,id"
    ):
        if (task is not None or external) and not scopes.allowed(
            task, "lesson", row["id"]
        ):
            continue
        payload = json.loads(row["payload"])
        reason = None
        if domain not in payload["scope"]:
            continue
        if external and not Learning(store).external_allowed(row):
            continue  # Do not reveal even IDs of unapproved local assets.
        engine = store.rows(
            "SELECT payload FROM records WHERE kind='native_asset_engine' AND id=?",
            (row["id"],),
        )
        if engine:
            current = store.rows(
                "SELECT value FROM meta WHERE key='native_learning_engine'"
            )
            if (
                not current
                or current[0]["value"] != json.loads(engine[0]["payload"])["engine"]
            ):
                reason = "native evaluator changed; revalidation required"
        if payload.get("routes") and route not in payload["routes"]:
            reason = "route requires revalidation"
        for dependency in payload.get("dependencies", []):
            if dependency.get("kind") == "source":
                rows = store.rows(
                    "SELECT revision FROM sources WHERE id=?", (dependency.get("id"),)
                )
                valid = rows and rows[0]["revision"] == dependency.get("revision")
            elif dependency.get("kind") == "lesson":
                rows = store.rows(
                    "SELECT status FROM lessons WHERE id=?", (dependency.get("id"),)
                )
                valid = rows and rows[0]["status"] == "active"
            else:
                valid = False
            if not valid:
                reason = "dependency changed or missing"
        if reason:
            omitted.append({"id": row["id"], "reason": reason})
            continue
        value = {
            "id": row["id"],
            "kind": row["kind"],
            "version": row["version"],
            **{
                k: payload[k]
                for k in ("scope", "preconditions", "exclusions", "content")
            },
        }
        tokens = set(re.findall(r"[a-z0-9_]+", canonical(value).lower()))
        candidates.append((len(terms & tokens), value))
    candidates.sort(key=lambda pair: -pair[0])
    selected, used = [], 0
    for _, value in candidates:
        cost = len(canonical(value))
        if used + cost > max_chars:
            omitted.append(
                {"id": value["id"], "reason": "context budget; retrieve separately"}
            )
        else:
            selected.append(value)
            used += cost
    return {
        "selected": selected,
        "omitted": omitted,
        "characters": used,
        "budget": max_chars,
    }
