"""Opt-in local OpenInference/OTLP export. SQLite remains authoritative.

Stable trace/span identities support retry after interrupted exports. Delivery
is at least once; the receiving viewer may display duplicate submissions.
"""

import hashlib
import json
import httpx
from .common import Blocked, ContractError


def export_local(store, port=6006, limit=200):
    if (
        type(port) is not int
        or not 1024 <= port <= 65535
        or type(limit) is not int
        or not 1 <= limit <= 500
    ):
        raise ContractError("Invalid local viewer port or batch size")
    cursor = store.rows(
        "SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT 1",
        ("otlp_cursor:" + str(port),),
    )
    after = json.loads(cursor[0]["payload"])["seq"] if cursor else 0
    rows = store.rows(
        "SELECT * FROM traces WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
    )
    if not rows:
        return {"sent": 0, "through": after}
    spans = []
    for row in rows:
        stamp = int(row["created"] * 1_000_000_000)
        attributes = {
            "openinference.span.kind": (
                "LLM"
                if row["kind"].startswith("response") or row["kind"] == "request"
                else "TOOL"
            ),
            "session.id": row["task_id"],
            "ha.route": row["route"],
            "ha.correlation": row["correlation"],
            "ha.kind": row["kind"],
            "ha.payload": row["payload"],
        }
        spans.append(
            {
                "traceId": hashlib.sha256(row["task_id"].encode()).hexdigest()[:32],
                "spanId": row["identity"][:16],
                "name": row["route"] + "/" + row["kind"],
                "kind": 1,
                "startTimeUnixNano": str(stamp),
                "endTimeUnixNano": str(stamp + 1),
                "attributes": [
                    {"key": k, "value": {"stringValue": v}}
                    for k, v in attributes.items()
                ],
            }
        )
    body = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "hivemind-assembly"},
                        }
                    ]
                },
                "scopeSpans": [
                    {"scope": {"name": "hivemind.local-journal"}, "spans": spans}
                ],
            }
        ]
    }
    try:
        with httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            response = client.post(f"http://127.0.0.1:{port}/v1/traces", json=body)
        if not 200 <= response.status_code < 300:
            raise Blocked(
                "Local trace viewer rejected the export; the journal is retained"
            )
        result = response.json() if response.content else {}
        if result.get("partialSuccess", {}).get("rejectedSpans", 0) not in (0, "0"):
            raise Blocked(
                "Local viewer rejected some spans; export cursor was not advanced"
            )
    except (httpx.HTTPError, ValueError):
        raise Blocked(
            "Local viewer is unavailable; capture continues in the local journal"
        ) from None
    from .common import uid

    store.put("otlp_cursor:" + str(port), uid("export"), {"seq": rows[-1]["seq"]})
    return {"sent": len(rows), "through": rows[-1]["seq"]}
