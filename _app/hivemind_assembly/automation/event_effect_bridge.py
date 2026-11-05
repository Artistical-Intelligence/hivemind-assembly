"""Bridge existing native Chat Mode turns to fenced local effect receipts.

This is a lightweight adapter between NativeTeam's existing browser ask()
and core.DurableEventEffects. It never invokes a model, browser, API or
scheduler itself. Unknown pre-existing dispatches are not blindly resent.

Original Python adaptation of the local outbox/receipt design documented in
dev/continuous_execution/DEEPSEEK_HARNESS_INTEGRATION.md.
"""

from __future__ import annotations

import json
import time

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.durable_effects import DurableEventEffects


class NativeEventEffectBridge:
    """Bind one already authorized event to one existing native intent turn."""

    def __init__(self, store):
        self.store = store
        self.effects = DurableEventEffects(store)

    def prepare(self, task: dict, route: str, receipt_id: str) -> tuple[list[dict], dict | None]:
        """Return events for the current turn and an exact finalization receipt.

        A persisted request wins over a freshly observed inbox after restart.
        One effect is leased per task/conversation; a second browser exchange
        is not permitted during an unresolved earlier event delivery.
        """
        task_id = task["id"]
        prior = self.store.rows(
            "SELECT task_id,route,state,payload FROM messages WHERE id=?",
            (receipt_id,),
        )
        if prior:
            saved = prior[0]
            if saved["task_id"] != task_id or saved["route"] != route:
                raise ContractError("Retained native event belongs to a different task or route")
            try:
                request = json.loads(saved["payload"])
                if (not isinstance(request, dict) or
                        request.get("task_id") != task_id or
                        request.get("project_id") != task["project_id"]):
                    raise ContractError("Retained event request has a different project binding")
                body = request.get("body", {})
                events = body.get("event_inputs", [])
                if not isinstance(events, list) or any(
                    not isinstance(item, dict) or
                    type(item.get("event_id")) is not int or
                    item["event_id"] <= 0 for item in events
                ):
                    raise ContractError("Retained native event envelope is malformed")
            except (ValueError, TypeError, AttributeError) as error:
                raise ContractError("Retained native event request is malformed") from error
            if events and saved["state"] != "validated":
                # Even a locally 'prepared' request may have reached the
                # external browser. Replaying it without evidence risks a
                # duplicate model turn, so pause for human/host reconciliation.
                raise Blocked(
                    "Retained native event request has uncertain browser "
                    "delivery; reconcile saved message before replay"
                )
            if not events:
                return [], None
            ids = [event["event_id"] for event in events]
            if len(ids) != len(set(ids)):
                raise ContractError("Duplicate retained native event IDs")
            linked = self.store.rows(
                """SELECT effect_key,event_id,generation,status
                   FROM ha_native_effect WHERE task_id=?""",
                (task_id,),
            )
            matches = [row for row in linked if row["event_id"] in ids]
            if matches:
                if len(events) != 1 or len(matches) != 1:
                    raise Blocked("Ambiguous retained native event effect binding")
                row = matches[0]
                if row["status"] == "queued":
                    raise Blocked(
                        "Retained validated event predates its unclaimed effect; "
                        "manual reconciliation required"
                    )
                return events, {
                    "effect_key": row["effect_key"],
                    "generation": row["generation"],
                    "fresh": False,
                }
            # Historical validated turns from before effect integration may
            # still own an unread inbox delivery. Keep the older, exact saved
            # request acknowledgment path ONLY when no effect references it.
            return events, {"legacy": True, "fresh": False}

        # Stage one event per native intent turn. The core currently orders
        # equal-due work by string effect_key, not numeric event_id; staging
        # many "event-2"/"event-10" keys at once could reorder project facts.
        # The existing inbox remains durably queued and will be staged in
        # chronological batches across subsequent authorized turns.
        self.effects.stage_pending(task_id, limit=1)
        # Recover only from previously validated local evidence. If the old
        # exchange is still in-flight, or outcome is unknowable, do not start
        # an additional browser event exchange for this conversation.
        for row in self.effects.status(task_id):
            if row["status"] == "leased":
                state = self.effects.recover_expired_lease(
                    task_id, route, task["epoch"], row["effect_key"],
                    row["generation"], now=time.time(),
                )
                if state == "leased":
                    raise Blocked(
                        "Earlier native event delivery is still leased; "
                        "do not send another browser turn"
                    )
            if row["status"] in ("leased", "uncertain"):
                verdict = self.effects.reconcile_uncertain(
                    task_id, route, task["epoch"], row["effect_key"],
                )
                if verdict != "delivered":
                    raise Blocked(
                        "Earlier native event delivery needs validated receipt "
                        "reconciliation before further browser turns"
                    )
        claim = self.effects.claim(task_id, route, task["epoch"])
        if claim is None:
            return [], None
        return [claim["event_input"]], {
            "effect_key": claim["effect_key"],
            "generation": claim["generation"],
            "fresh": True,
        }

    def finalize(self, task: dict, route: str, receipt_id: str,
                 inbox, binding: dict | None) -> str:
        """Consume only a stored validated native reply, never a fake response."""
        if binding is None:
            return "none"
        if binding.get("legacy"):
            inbox.acknowledge_validated_request(
                task["id"], receipt_id, route=route
            )
            return "legacy"
        return self.effects.finalize(
            task["id"], route, task["epoch"], binding["effect_key"],
            binding["generation"], receipt_id
        )

    def mark_interrupted(self, task: dict, route: str, receipt_id: str,
                         binding: dict | None) -> None:
        """Requeue only proven pre-dispatch failure; quarantine every other case.

        NativeTeam._ask() persistently prepares the request BEFORE it can
        invoke browser.exchange(). With no corresponding message at all,
        dispatch was impossible and retry is safe. A prepared/validated or
        otherwise existing saved message is not proof of non-delivery.
        """
        if not binding or not binding.get("fresh"):
            return
        stored = self.store.rows(
            """SELECT id FROM messages WHERE id=? AND task_id=? AND route=?""",
            (receipt_id, task["id"], route),
        )
        definitely_not_sent = not bool(stored)
        self.effects.interrupted(
            task["id"], route, task["epoch"],
            binding["effect_key"], binding["generation"],
            definitely_not_sent=definitely_not_sent,
            delay_seconds=0 if definitely_not_sent else 30,
        )
