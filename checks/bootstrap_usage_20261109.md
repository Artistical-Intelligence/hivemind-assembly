# Independent static review: proactive bootstrap instructions

Date: 9 November 2026 (UTC)

**Verdict: PASS for the scoped documentation delta. No blocking correction found.**

This review was performed by a fresh, qualified independent reviewer with no inherited author conversation. It covers the requested run-start and run-end bootstrap checks, not implementation or operational acceptance.

## Exact inputs and coverage

Repository: `Artistical-Intelligence/hivemind-assembly`.

- Baseline: `5c315dde3226d615150d1308c189fba0cb2acf2c`.
- Reviewed draft: `20141ded705dda2d3dbd40f672616f05783f52a7`.
- Native compare reports four commits ahead, no divergence, and only the four paths below changed.

| Path | Baseline blob | Reviewed blob | Covered change |
| --- | --- | --- | --- |
| `AGENTS.md` | `a0aa68e9d5ef374a8b2f19ab5368f5cfe902a80e` | `482d5b0c3aa488e6002ad7d2d3a9b7a1fb8ba580` | All 38 inserted lines, final lines 75–112 |
| `CHATGPT.md` | `7708366cd85fb75796eb2633e59a679c6e860337` | `6a61af67909e34e1e108b218dfdb2b0a0d327d1e` | Revision 1.7 and complete replacement bootstrap block, final lines 134–164; 32 additions/8 deletions overall |
| `STATUS.md` | `57382225a0f11347e8c8dd2a0feedd07c1b12db3` | `7b4479722c4c69417e7b6af4702fe80a60f9efa8` | Scoped pending line and separating blank line only |
| `CHECKS_STATUS.md` | `c48b1b70149b850c7bed8868df453e017c9109af` | `4bd99cee238e7588d43816b5e287c992a90cb903` | Scoped pending row and separating blank line only |

Complete final text and complete baseline-to-draft deltas were inspected through inline UTF-8 reads. Additional governing context was read in full at the reviewed draft:

- `dev/continuous_execution/SHIFT_MANAGER.md`, blob `6142e8a2649f03d8756a4ad6ad509c3727cde05d`.
- `dev/continuous_execution/workplace/WORKPLACE_POLICY.md`, blob `12210b2aa4f8ec4a04bfbbff0617dd9125aa5220`.
- `dev/continuous_execution/PROCESS.md`, blob `efe529c3ca298432cca2bea6d547f948be11cde5`.

## Findings

1. **Required timing is explicit.** Each authorized scheduled Chat Mode run checks at its start and again at its end after its own ready authorized tasks. Mid-run dependency handoffs replace neither check. The worker must not defer its own work, manufacture tasks, impose a dispatch quota, or prolong a run solely to bootstrap; unfinished or blocked work is reported honestly.
2. **Useful work and existing authority control dispatch.** Only dependency-ready, nonduplicative assignments with bounded scope, source pins, output ownership and acceptance qualify. Direct dispatch requires the actor's existing TEMP rights. Restricted, no-trigger and consumer-only roles route the exact packet to the existing District Manager without gaining trigger authority. Permanent recurring prompts, schedules, recurrence and enabled state remain exclusively under the existing District Manager.
3. **Global eligibility is preserved.** Nothing in the new text narrows the existing account-wide rule allowing genuinely idle historical one-time tasks from any chat or former purpose. Discovery remains separate from validated pool registration and dispatch. The prohibition on takeover concerns currently assigned unrelated work, not a task's historical origin. Full-time roles remain disjoint from temps.
4. **Claims and source boundaries remain binding.** Exact current worker identity, stopped/idle state, appointments, holds, claims, source grants, dependencies, writer ownership, capacity and platform limits must be checked. The existing global atomic claim is required and rechecked immediately before activation; a read-before-write is not a lock. The detailed claim policy still requires verified ownership and latest-blob release, with manager reconciliation where needed. No unresolved claim can be discarded, and age, a finished invocation or a null next-run field alone never proves availability.
5. **Results must be consumed, not merely scheduled.** Existing summaries distinguish a ready packet, saved claim/configuration, matched actual run/output and a consumed result. Release requires accounted-for results/obligations and a safely stopped worker under existing release authority. Saved configuration, a distinct task ID or a handoff is not execution, reviewer qualification or independent context.
6. **No permission or execution expansion.** HA remains paused. No Actions, staffing activation, engineering, tests, builds, release, paid route, duplicate run, blind revival, scheduled child creation or service/approval bypass is authorized. Missing capabilities or a safe claim route remain blockers. Chat Mode rules are not injected into Work, Codex, Claude or unknown surfaces. Source mediation, privacy, licensing/security holds, qualified independent review, exclusive saving/integration ownership and receiving-tree gates remain intact.

## Preservation and scoped disposition

`AGENTS.md` retains every baseline line. `CHATGPT.md` changes only its revision and the identified bootstrap block. Both status files retain their entire baseline content byte-for-byte after the two-line prepend. The native compare shows no queue, worker prompt, scheduler, registry, claim, source, test, workflow or other governing-file change.

Only the new **2026-11-09 proactive bootstrap instructions** pending line and row may be cleared with publication of this report, subject to normal single-writer reconciliation. Preserve all older pending markers, including older Chat Mode instruction/source reviews and live scheduler, provider, integration and release gates. The broader pending notices in `CHATGPT.md`, `PROCESS.md` and `SHIFT_MANAGER.md` are outside this acceptance.

## Limits

This was a static text/metadata review. No software, tests, builds, Actions, dispatch, worker-control mutation, claim acquisition/release or live worker receipt was executed or accepted. No attachment materialization was used. No deployed dispatcher, atomic-claim race behavior, saved-prompt receipt, source-access isolation, successful handoff, consumed runtime result or broader project acceptance is established by this report. Public content here contains no private task IDs, claims or private source evidence.
