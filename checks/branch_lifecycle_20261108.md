# Branch lifecycle and permission guidance: independent static review

Date: 8 November 2026  
Verdict: **PASS**  
Scope: documentation only.

## Reviewed inputs

Repository: `Artistical-Intelligence/hivemind-assembly`

- Original baseline commit: `85284049f03c0c61f02c892c3207c4129b7105bb`
- Baseline `AGENTS.md` blob: `f9471bf4197db29624fe8e8dcd544de3f0a7fbad`
- Initial lifecycle commit: `7973b8ab1490308007b3f543a49b846a25f51fee`
- Permission-guidance commit: `8e3f88d6b838668a9e6e15dfbec999dda384b8eb`
- **Final reviewed policy commit:** `38db62618dc38051a91022bae815d0df42f1433a`
- **Final `AGENTS.md` blob:** `c28e110f9a5823369c8a0fca8268225df41284ba`
- `STATUS.md` blob: `06e833c8123a09b044b9dea678772cd91da7096c`
- `CHECKS_STATUS.md` blob: `7da3cb8d68c1358348fd6505229bd1c3e1a825d6`
- Supporting `dev/continuous_execution/BRANCH_CONSOLIDATION_P0_20261106.md` blob: `aa230f4745b181b3930fdb421eca3cace6beca51`

The separate reviewer received focused sources without author-conversation inheritance. Complete baseline and policy context, every changed line, commit diffs and metadata, and the scoped pending markers were examined through inline GitHub reads. Unchanged prior source-review evidence was reused and checked against the incremental diffs.

[Original baseline to final policy](https://github.com/Artistical-Intelligence/hivemind-assembly/compare/85284049f03c0c61f02c892c3207c4129b7105bb...38db62618dc38051a91022bae815d0df42f1433a)

## Coverage and findings

Line references identify the final AGENTS blob.

### Branch lifecycle

- **Lines 105–107:** the existing exception record now recognizes authorization already covering the assigned scope and asks only for genuinely missing required permission. The neighboring ownership and safe-handoff rules remain unchanged.
- **Lines 116–121:** transferable practices use existing task, PR and handoff records without another registry, recurring job or reporting layer.
- **Lines 122–128:** branch/PR/claim inspection and continuation recovery prevent branch-per-task defaults without overriding ownership or compatibility.
- **Lines 129–134:** justified exceptions retain purpose, writer, starting revision, destination, dependencies and an exit condition.
- **Lines 135–143:** common redundancy candidates require proof. Ancestry, tree equality and behavioral equivalence remain distinct; complete relevant deltas and unique items must be accounted for.
- **Lines 144–151:** accepted compatible work is integrated through the existing owner and independent checks. Evidence or history preservation is not misrepresented as functional integration; unresolved work remains held.
- **Lines 152–160:** retirement requires durable preservation of useful unique content, complete original history and required objects. An authorized retained ref or recoverable archive may be used without inventing an additional personal approval step. Access restrictions, recovery, and the prohibition on importing held content remain intact.
- **Lines 161–169:** fresh heads, ownership, leases, dependencies, branch roles and live links remain mandatory. Changed state invalidates clearance. Supported guards, serialization, remote verification and uncertain-outcome reconciliation do not pretend a preflight read is atomic.
- **Lines 170–179:** authorized integration and cleanup form part of completion without another purely clerical wait. Held branches retain a reason, owner and release condition.

### Permission handling

- **Lines 180–190:** distinct action types must be matched to existing authority. A new worker, tool, turn, retry or handoff does not itself trigger another approval. Material scope/risk changes and mandatory action-time approval remain exceptions. The final wording explicitly retains required current-state and ownership checks.
- **Lines 191–197:** task-equivalent supported routes with fewer permission needs are selected **before** a gated operation. They must preserve the requested result, evidence, access boundaries and review coverage; limitations cannot silently reduce the task.
- **Lines 198–203:** permitted reads establish actual requirements before reporting blockers. Existing scoped approval and authorized coordination count where applicable rules allow them. Invented blanket gates and stale blockers are rejected; current explicit pauses remain controlling.
- **Lines 204–210:** the specific missing action, target, scope and consequences are requested at the real boundary. Independent authorized work may continue. Actual denials and pending approvals cannot be evaded through tools, routes, agents or wording; uncertain outcomes require reconciliation.
- **Lines 211–215:** the closing limitation neither grants blanket authority nor withdraws existing authorization. Mandatory confirmations, access restrictions, holds, ownership, checks and pauses remain binding.

**No corrective findings.** The final policy fulfills the branch-creep prevention and permission-friction requirements while preserving HA’s development pause, independent review, provider/surface separation, source-access mediation, privacy and security boundaries. Existing authority is recognized, not expanded.

## Preservation and scope checks

The original-baseline-to-final comparison contains only:

- `AGENTS.md`: 103 additions and 2 deletions.
- `STATUS.md`: 2 additions.
- `CHECKS_STATUS.md`: 2 additions.

The two baseline AGENTS lines replaced are the branch-exception authorization wording. Removing the added policy sections and restoring that exact two-line wording reproduces the complete baseline text exactly. No unrelated original AGENTS content changed.

The lifecycle status marker and row remain unchanged by the permission amendments. Removing those additions reproduces the baseline status files exactly. No unrelated pending item was accepted or removed. No implementation, workflow or other file changed in this comparison.

## Marker disposition and limits

After saving this report and reconciling current remote files against the reviewed inputs, the integration owner may clear only:

- The `STATUS.md` line beginning `CHECKS PENDING: 2026-11-08 branch lifecycle guidance in AGENTS.md`.
- The `CHECKS_STATUS.md` row beginning `| 2026-11-08 branch lifecycle guidance |`.

Save that clearance in the same commit as this report. Preserve all unrelated markers. Any subsequent substantive policy change requires affected review before clearance.

This is static documentation acceptance, not branch, implementation or release acceptance. The reviewer performed no writes, materialization, executable tests, builds, Actions, comments, merges, branch deletions or schedule changes. No current branch is certified redundant or safe to retire, and HA development remains paused.
