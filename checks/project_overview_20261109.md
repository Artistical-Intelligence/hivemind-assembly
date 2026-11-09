# Project overview and owner-action instruction review

**Verdict: PASS for the bounded documentation delta.** No blocking correction found. Reviewed 9 November 2026, 19:50 UTC. HA remains paused.

## Scope and independence

An author-independent reviewer in a separate session, without inherited author conversation, read the complete pinned `AGENTS.md` and `CHATGPT.md`, their changed text and governing surrounding rules. The reviewer inspected commit metadata, all relevant patches, complete baseline/current text and the narrowly scoped pending-record changes. This is a static review of instructions, not independent external model attestation or acceptance of the previously pending wider documents.

Inputs were obtained as inline UTF-8 through `GitHub.fetch_file` at exact commits. No attachment/materialization route, repository software, tests, builds, GitHub Actions or automation-control writes were used. The reviewer did not modify the repository.

## Source identity and complete delta coverage

Repository: `Artistical-Intelligence/hivemind-assembly`.
Baseline: [`06659cbcef367d78f3d069a2a924d14241429d4d`](https://github.com/Artistical-Intelligence/hivemind-assembly/commit/06659cbcef367d78f3d069a2a924d14241429d4d).
Reviewed commits: `e4c280a30c8245348d7c68d55d757fe794de437a` and [`c8b25d5121a48eb206b688862cd4df6abc9ea308`](https://github.com/Artistical-Intelligence/hivemind-assembly/commit/c8b25d5121a48eb206b688862cd4df6abc9ea308).

The compare reports two commits ahead, no divergence, and exactly four changed documentation paths. Every instruction addition/deletion is covered: 50 added and 14 removed lines. The only other changes are four marker/separator additions.

- `AGENTS.md`: full current text read, lines 1–581. Replacement: baseline 75–83 → current 75–112; 38 additions, 9 deletions. Baseline blob `6b2579160b4d330c9d93addcd00bd82c6d4e698f`; reviewed blob `a0aa68e9d5ef374a8b2f19ab5368f5cfe902a80e`.
- `CHATGPT.md`: full current text read, lines 1–428. Revision line 3 and baseline 29–32 → current 29–39; 12 additions, 5 deletions. Baseline blob `e6ff00552d7a32084f818a5a27d1ffc17165cd87`; reviewed blob `7708366cd85fb75796eb2633e59a679c6e860337`.
- `STATUS.md`: only current lines 1–2 were added. Baseline blob `57382225a0f11347e8c8dd2a0feedd07c1b12db3`; reviewed blob `62a826eef4e7f433fb38b0715647e0947bae5281`.
- `CHECKS_STATUS.md`: only current lines 1–2 were added. Baseline blob `c48b1b70149b850c7bed8868df453e017c9109af`; reviewed blob `d561b429f76eaf07679721d68e92ad78129e51ce`.

Applying the complete instruction patches to their baseline text reproduces the pinned current text exactly. No unreported instruction edit is included.

## Findings

1. **Worker summaries and freshness:** AGENTS 75–82 requires each assigned owner to maintain goal, owner, verified progress, next action, blocker and timestamp with timezone in its existing location. Exact evidence links, observation/edit distinction, stale/unknown/unverified labels and no continuous-freshness claim are explicit.
2. **One useful manager overview:** AGENTS 83–95 requires a single existing-manager overview, evidence-backed change since the preceding overview and actual bottleneck resolution/assignment and authorized priority/handoff improvements at each real invocation. It rejects invented percentages, performance ledgers, repeated summaries, busywork and weekly review rituals. Paused HA permits only authorized documentation/coordination.
3. **Minimal owner action view:** AGENTS 96–103 limits the existing authorized inbox to essential numbered “Run this”/“Approve this” actions and exact links, removes verified completed/unneeded items and excludes explanations, history, optional items, status chatter and agent-solvable work. Private owner actions stay outside this public repository; recovery records and permissions survive cleanup.
4. **Machine state and safeguards:** AGENTS 104–112 explicitly preserves parser state, schemas, required reader fields, source pins, claims, leases, gates, existing ownership, immutable history and no-force-push rules. The changed Chat Mode summary delegates to that full contract and retains provider/surface restrictions. No runtime/control/schema file changed.
5. **Newer manager handoff retained:** The entire AGENTS prefix through the immediate District Manager review-and-apply section is identical to the baseline. Current lines 12–46 still require immediate concrete routing and safe-boundary application without duplicate owner approval, while preserving the pause and review/security/licensing/privacy/ownership gates.
6. **Broader obligations retained:** Full-text comparison confines changes to the stated replacements. Source mediation, independent checking, writer ownership, prompt saving, no-Actions/current pause and release restrictions remain intact. Historical workflow examples do not override the current governing restrictions.

## Marker preservation and permitted closure

The complete pre-existing `STATUS.md` content (1,468 characters) and `CHECKS_STATUS.md` content (39,757 characters) remain unchanged after the new two-line prepend in each file. Older pending records are preserved, not reaccepted or closed by this report.

The publishing owner may clear only the new **2026-11-09 project overview and owner-action inbox instructions** line/row, together with retaining this report in `checks/` in the same commit. Preserve every older pending entry, including broader instruction, source, runtime and release checks. Keep `STATUS.md` because older entries remain.

## Exact acceptance limits

Accepted: the consistency, requested behavior, scope, freshness semantics, ownership and preservation safeguards of these two instruction deltas, plus the scoped pending-record maintenance.

Not accepted or demonstrated: a live overview/inbox installation or cleanup, any manager-owned registry/`current.json` migration, schema compatibility of a future implementation, worker receipt, staffing/role/schedule changes, runtime tests, source correctness, platform/provider behavior, integration or release readiness. There is no authority here to resume HA or run GitHub Actions. Subsequent substantive text changes require affected review; publication must preserve the pinned reviewed instruction blobs and unrelated pending work.

