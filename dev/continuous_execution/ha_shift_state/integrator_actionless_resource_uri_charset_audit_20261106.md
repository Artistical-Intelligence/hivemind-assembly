# HA integrator — source-pinned MCP URI/charset audit (2026-11-06)

**Role:** HA-NATIVE-20261105-I-INTEGRATOR. **Status:** CHECKS PENDING / AWAITING CI / independent review and live browser acceptance. **No GitHub Actions, model API, external MCP, binary, RE-Wizard, or hosted approval bypass.**

## Exact inspected source

- GitHub `main` at the read/revalidation point: `a94446dd2b2dc8e856aa77884fb0b4506a29f435`; source commit [a94446dd](https://github.com/Artistical-Intelligence/hivemind-assembly/commit/a94446dd2b2dc8e856aa77884fb0b4506a29f435) (2026-11-06 19:32:49 UTC), modifying only `_app/hivemind_assembly/integrations/mcp.py` (+17/-2).
- `_app/hivemind_assembly/integrations/mcp.py` blob `aa6dc66084f303489afb8d53392283a40681fc77`; `tests/test_mcp_inline_text.py` blob `63bbe71cc8ea3ea146c1733e2976328717b81a53` (14 authored top-level test functions); `_app/hivemind_assembly/core/durable_effects.py` was read separately.
- Focused `.github/workflows/chatmode-native-events.yml` blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183` explicitly includes the existing MCP test and 15 total test-module arguments. Broad `.github/workflows/test.yml` blob `094ac74c77d5b6f7a08664ae45ecc6392cc78ac2` pins browser fixture to `ubuntu-24.04`; no change needed.
- Reviewed all 22 workflow YAML trigger headers, including unrestricted `test.yml` push and `release.yml` workflow_run. A documentation commit with `[skip ci]` should not initiate the normal push tests; that marker is not proof of a green check or of suppression of every possible trigger. Read-only latest 20 Actions records ended with historical skipped release run `42155444831`, 2026-11-06 03:15 UTC. No Actions dispatch performed.

## New source delta and bounded offline diagnostic

Worker B's source now checks embedded resource URI is a string of 1..2048 characters without C0/DEL and no more than 4096 UTF-8 bytes, rejecting invalid UTF-8 surrogates. It also rejects an embedded `mimeType: text/plain; charset=us-ascii` resource whose literal text is non-ASCII.

**14 local isolated copied-predicate examples** (9 URI length/control/encoding, 5 embedded resource charset/body) agreed with intended classifications. These examples used Python's local interpreter on copied validation expressions; **not** `inline_github_mcp_text()`, `Connections._external()`, HA pytest, live MCP, provider or browser acceptance. URI probes: safe `repo://source`, empty, 2049 ASCII chars, boundary 2048 ASCII, TAB, DEL, lone surrogate, 4097 UTF-8 bytes, and 4096 bytes. Charset probes: plain ASCII, accented ASCII contradiction, emoji contradiction, UTF-8 accented positive, empty ASCII positive.

**Additional review hypothesis — do not treat as a proven bypass:** the new US-ASCII/body check is in the `kind == "resource"` conversion branch. A separate plain `type=text` content block can carry `_meta: {"charset":"us-ascii"}`, or `structuredContent` can declare `charset: us-ascii`, alongside non-ASCII text. The recursive metadata validator validates the charset token but does not appear to cross-check it with the literal text block. This may be a semantic source-declaration inconsistency, not an attachment download or hosted platform approval bypass. Worker B should decide whether a metadata declaration is intended to bind content text, and, if so, enforce the relation without rejecting unrelated metadata; independent verifier should capture positive and negative actual-function tests.

## Concrete verifier packet (not yet executed)

The independent verifier should add tests to its owned `tests/test_mcp_inline_text.py`, not have this integrator edit it:

1. Embedded resource URI rejects empty, overlong, control-char and surrogate variants; accepts bounded safe inline source with original URI discarded.
2. Embedded `charset=us-ascii` rejects `café` or emoji literal text, accepts ASCII source; `charset=utf-8` remains valid for non-ASCII source.
3. Determine intended scope of plain text block / structured metadata charset. If bound to content, reject contradictory `{"content":[{"type":"text","text":"café","_meta":{"charset":"us-ascii"}}]}`; keep valid `utf-8` and `README` positives.
4. Repeat through stubbed `Connections._external` with authorization/fence checks; do not infer external hosted GitHub MCP approval handling from local tests.

**Ready-to-run, unexecuted commands when a permitted HA checkout/environment is available:**
```bash
PYTHONPATH=_app HA_SKIP_HELPER_REGISTRATION=1 HA_MEANING_SEARCH=0 python -m pytest -q tests/test_mcp_inline_text.py tests/test_mcp_connections.py
```
Later, under explicit owner permission, verify source-matched cross-platform HA baseline and genuine ChatGPT browser/native saved-receipt/restart behavior. Neither was attempted here.

## Independent blockers and handoff

The separate core owner must repair `_contains_exact_event` typed, exact-scope receipt binding and final live-lease fencing; the verifier should correct obsolete terminal-ticket fixtures without weakening security. Historical whole-HA Linux/Windows failures and Windows Unicorn/Speakeasy access violations remain separate. No direct core/worker/verifier writes or owner-management actions were taken. No unauthorized provider/model/API changes, binaries, ZIPs, private files, credentials, games or compiler tests.

All repository reads were through inline UTF-8 `mcp__GitHub__fetch_file` or `mcp__GitHub__fetch`, not attachments or GitHub MCP file materialization. **CHECKS PENDING / AWAITING CI** until actual-module tests, qualified security review and live native ChatGPT acceptance are independently proved.
