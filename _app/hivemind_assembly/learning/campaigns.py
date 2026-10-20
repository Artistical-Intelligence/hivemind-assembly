"""Durable native ACE reflection/curation and SkillOpt procedure edits.

A model may propose a candidate but cannot provide its own evaluation score.
Promotion remains a separate protected experiment against a pinned evaluator.
"""

import json
from .engine import Learning
from .playbook import apply_delta
from hivemind_assembly.core.common import Blocked, ContractError, canonical, digest
from hivemind_assembly.vendor.ace.reflector import REFLECTOR_PROMPT_NO_GT
from hivemind_assembly.vendor.ace.curator import CURATOR_PROMPT
from hivemind_assembly.vendor.skillopt.skill import apply_patch_with_report


def rationale_only(prompt):
    return prompt.replace(
        "Your chain of thought / reasoning / thinking process, detailed analysis and calculations",
        "Brief evidence-based explanation",
    ).replace(
        "your chain of thought / reasoning / thinking process, detailed analysis and calculations",
        "a brief evidence-based explanation",
    )


class Campaigns:
    def __init__(self, store):
        self.store = store

    def start(self, task, baseline, evidence):
        row = self.store.one("SELECT * FROM lessons WHERE id=?", (baseline,))
        payload = json.loads(row["payload"])
        if row["kind"] not in ("knowledge", "procedure") or row["status"] not in (
            "active",
            "candidate",
        ):
            raise Blocked("Reflection requires a knowledge or procedure baseline")
        if not Learning(self.store).external_allowed(row):
            raise Blocked(
                "This learning asset is local-only; native reflection cannot receive it"
            )
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 24:
            raise ContractError("Reflection requires 1–24 operation references")
        records = []
        for key in evidence:
            op = self.store.one(
                "SELECT * FROM operations WHERE id=? AND task_id=?", (key, task)
            )
            if op["state"] not in ("completed", "saved"):
                raise Blocked("Reflection evidence must be completed operations")
            records.append({k: op[k] for k in ("id", "tool", "args", "result")})
        key = (
            "campaign_"
            + digest({"task": task, "baseline": baseline, "evidence": evidence})[:32]
        )
        self.store.put(
            "learning_campaign",
            key,
            {
                "task": task,
                "baseline": baseline,
                "kind": row["kind"],
                "payload": payload,
                "evidence": records,
            },
        )
        return key

    def reflection_prompt(self, key):
        row = self.store.get("learning_campaign", key)
        return (
            rationale_only(
                REFLECTOR_PROMPT_NO_GT.format(
                    self.store.task(row["task"])["objective"],
                    "Only observable actions and results are available.",
                    canonical(row["evidence"]),
                    "Assess observed correctness, failures, unnecessary work and reusable conditions. Do not infer hidden thoughts.",
                    canonical(row["payload"]["content"]),
                )
            )
            + "\nReturn the reflection as type learning_feedback with feedback containing concise evidence-based observations and bullet_tags. Preserve the outer request_id."
        )

    def retain_reflection(self, key, response):
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("feedback"), dict)
            or len(canonical(response)) > 64000
        ):
            raise ContractError("A bounded structured learning reflection is required")
        self.store.put("learning_reflection", key, response["feedback"])

    def curation_prompt(self, key):
        row = self.store.get("learning_campaign", key)
        reflection = self.store.get("learning_reflection", key)
        prompt = CURATOR_PROMPT.format(
            token_budget=16000,
            current_step=1,
            total_samples=1,
            playbook_stats="Preserve entry IDs, conditions, exclusions and evidence.",
            recent_reflection=canonical(reflection),
            current_playbook=canonical(row["payload"]["content"]),
            question_context=self.store.task(row["task"])["objective"],
        )
        suffix = (
            "Return type learning_candidate with edits [{action,id,entry,expected_hash}], entry {text,conditions,exceptions,evidence}; cite only provided operation IDs. Do not supply promotion scores."
            if row["kind"] == "knowledge"
            else "Return type learning_candidate with patch {edits:[{op,target,content}]}. Operations are replace, append, insert_after or delete; preserve conditions and exclusions. The procedure text is the current content serialized as JSON. Do not supply promotion scores."
        )
        return (
            rationale_only(prompt)
            + "\nThe host output contract supersedes the upstream example: "
            + suffix
            + " Preserve the outer request_id."
        )

    def propose(self, key, response):
        old = self.store.rows(
            "SELECT payload FROM records WHERE kind='campaign_candidate' AND id=?",
            (key,),
        )
        if old:
            return json.loads(old[0]["payload"])
        row = self.store.get("learning_campaign", key)
        payload = row["payload"]
        if row["kind"] == "knowledge":
            entries = (
                payload["content"].get("entries", {})
                if isinstance(payload["content"], dict)
                else {}
            )
            edits = response.get("edits")
            allowed = {e["id"] for e in row["evidence"]}
            if not isinstance(edits, list) or any(
                not set(e.get("entry", {}).get("evidence", [])) <= allowed
                for e in edits
            ):
                raise Blocked("Curated entries must cite the supplied observations")
            content = {"entries": apply_delta(entries, edits)}
            report = {"method": "ACE localized curation", "edits": edits}
        else:
            patch = response.get("patch")
            if (
                not isinstance(patch, dict)
                or not isinstance(patch.get("edits"), list)
                or not 1 <= len(patch["edits"]) <= 16
            ):
                raise ContractError(
                    "Procedure optimization requires a bounded SkillOpt patch"
                )
            text, reports = apply_patch_with_report(
                canonical(payload["content"]), patch
            )
            if (
                len(text) > 128000
                or text == canonical(payload["content"])
                or any(
                    not r["status"].startswith("applied_") or "fallback" in r["status"]
                    for r in reports
                )
            ):
                raise Blocked("Procedure edit did not apply cleanly")
            try:
                content = json.loads(text)
            except ValueError:
                raise ContractError(
                    "Procedure patch must preserve structured JSON content"
                ) from None
            report = {"method": "SkillOpt patch application", "reports": reports}
        source = self.store.one(
            "SELECT asset_key FROM lessons WHERE id=?", (row["baseline"],)
        )
        candidate = Learning(self.store).propose(
            source["asset_key"],
            row["kind"],
            {
                **payload,
                "external_allowed": Learning(self.store).external_allowed(self.store.one("SELECT * FROM lessons WHERE id=?", (row["baseline"],))),
                "content": content,
                "campaign": key,
                "baseline": row["baseline"],
                "evidence": sorted(
                    set(payload["evidence"]) | {e["id"] for e in row["evidence"]}
                ),
                "optimization": report,
            },
            identity="lesson_" + digest(key)[:32],
        )
        result = {
            "candidate": candidate,
            "status": "awaiting_independent_evaluation",
            "campaign": key,
        }
        self.store.put("campaign_candidate", key, result)
        return result
