# Full-time bootstrap instruction review

Date: 2026-11-09, 21:58 UTC  
Verdict: **PASS — scoped independent static documentation review**

## Review identity and exact scope

A separate author-independent reviewer received the assigned scope and pinned repository inputs without inheriting the author's conversation. This review covers the owner-requested instruction amendment: full-time receiver bootstrapping alongside temporary help, and productive permanent use of the last two actually available positions when useful temporary work does not consistently fill them.

- Repository: `Artistical-Intelligence/hivemind-assembly`.
- Baseline: `de79b45da54d92dc9c52b2405e545a40f80cf2b4`.
- Reviewed draft: `e61cd661ade97b3759a62c3febe3f7014a4ea3c8`.
- [Pinned comparison](https://github.com/Artistical-Intelligence/hivemind-assembly/compare/de79b45da54d92dc9c52b2405e545a40f80cf2b4...e61cd661ade97b3759a62c3febe3f7014a4ea3c8).
- Native comparison metadata establishes six commits ahead, zero behind, and exactly the nine paths below. A separate native main-head read still returned the reviewed draft during this review.

Complete baseline and draft text was retrieved using inline `fetch_file` at the pinned refs, with returned blob identities retained. The reviewer computed the full line delta, examined every changed line with surrounding context, and searched complete instruction text for remaining manager-only scheduling statements, reserve ratios, fixed capacity assumptions and scope conflicts. This is a delta review, not renewed validation of every historical statement or source implementation.

## Reviewed artifacts

| Path | Draft blob |
| --- | --- |
| `AGENTS.md` | `cb41d3d132905b958bcea545d869e608272150f7` |
| `CHATGPT.md` | `fa4a713220376767861afb2d0b38fff1a5c7fe7b` |
| `CHECKS_STATUS.md` | `25384f6ac8d0a8a7940c04be8521719dc9098ef9` |
| `STATUS.md` | `8e0afebd6ae0a4683adde7b2399ea9e852a18e6a` |
| `dev/continuous_execution/PROCESS.md` | `d2819ef6e4517aee768e54cbadec7ec2f838bec2` |
| `dev/continuous_execution/SHIFT_MANAGER.md` | `7d617e41352a501fbc035508ebd3f556cc20a60b` |
| `dev/continuous_execution/STATUS.md` | `f3b7e8deff26748c2914c999eb7e11f95f6e6b4a` |
| `dev/continuous_execution/workplace/STATUS.md` | `683b8d395bef4d5053d1f822286077ae971e93da` |
| `dev/continuous_execution/workplace/WORKPLACE_POLICY.md` | `483c21aa863c9ece21cb2d5e6cf7627d2c009803` |

## Findings

No blocking issue was found in the scoped amendment.

1. **Full-time and temporary START/END checks: PASS.** AGENTS.md lines 75–82 and CHATGPT.md lines 128–133 require both paths at START and END, after completing ready own work, without treating useful mid-run handoffs as substitutes. PROCESS.md lines 71–79, SHIFT_MANAGER.md lines 7–13 and WORKPLACE_POLICY.md lines 13–22 align with that rule. No dispatch quota, manufactured work or delay of ready own work is introduced.
2. **Narrow permanent-peer action: PASS.** AGENTS.md lines 83–92 permits only another healthy enabled idle permanent receiver's next eligible `DTSTART` advance for its existing ready assignment. Complete prompt/title/role, hourly recurrence, enabled state, timezone, environment, source access and ownership are preserved. CHATGPT.md lines 135–146 and SHIFT_MANAGER.md lines 15–34 agree. There is no authority to retask, convert to one-shot, create self-wake chains or use unapproved `run_now`.
3. **Exclusive reservation, freshness and dedupe: PASS.** AGENTS.md lines 93–100 requires exact target, handoff dedupe key, predecessor run, sole scheduling owner, allowed change and release/uncertain-state condition in existing private manager records. Manager and peers honor the reservation; both it and current task/run state are checked immediately before mutation. Completed invocation/null next-run observations alone are insufficient. Missing safe exclusivity produces a held handoff for reconciliation, not a competing update. SHIFT_MANAGER.md lines 17–26 preserves these controls and separates saved settings from actual receiving output/consumption.
4. **Manager authority and prompt action: PASS.** AGENTS.md lines 101–110 retains structural assignments, leases, prompts/roles, general cadence, pause/revival, enabled state and shared records with the single District Manager. Proactive reservation provisioning avoids an extra approval ceremony for already authorized ready handoffs. Restricted/no-trigger roles remain restricted; peers do not gain shared-record writes or structural staffing authority.
5. **Temporary protocol preserved: PASS.** AGENTS.md lines 111–122 retains current TEMP rights, global exclusive atomic claims, capacity/source/ownership checks, independent qualification and safe release. Full-time IDs remain outside the temp pool. CHATGPT.md lines 148–153 and 191–200, and SHIFT_MANAGER.md's unchanged global claim procedure, preserve actual-result consumption and unresolved-claim handling.
6. **Conditional last-two capacity: PASS.** AGENTS.md lines 123–135, CHATGPT.md lines 155–163, SHIFT_MANAGER.md lines 36–43, PROCESS.md lines 89–103 and WORKPLACE_POLICY.md lines 24–33 require actual recent temp-use evidence across a meaningful period and real available capacity. Suitable permanent workers fill those positions when useful temporary assignments do not consistently do so. The text rejects an invented numerical utilization threshold, configuration-only evidence, a single idle snapshot and a promised fixed service cap. Existing claims, appointments, protected work and safe transfers survive.
7. **Older authority and reserve statements reconciled: PASS.** The current exception explicitly supersedes blanket manager-only scheduling wording. The changed role table and subordinate statements consistently retain manager structural control while permitting only the reserved peer advance. CHATGPT.md lines 423–425 continues to reserve revival/retasking/rescheduling of a *stopped* permanent worker to the manager, which does not conflict with advancing a healthy enabled idle receiver. Earlier 1:1 reserve targets are expressly subordinate to the current last-two condition. Historical separate-manager passages are already marked superseded, not current staffing authority.
8. **Pause, no-Actions and provider boundaries: PASS.** AGENTS.md lines 5–8 authorizes only documentation maintenance while HA development stays paused. Lines 136–141 and the subordinate amendments preserve the pause and no-Actions restriction. CHATGPT.md lines 45–48 makes these controls govern older roster/timing examples. Legacy source-level acceptance requirements do not authorize new Actions. Chat Mode scheduling policy is not injected into Work, Codex, Claude or unknown surfaces.
9. **Privacy and access: PASS.** The new public delta contains no private task/run identifiers, claim contents, private source evidence or credentials. Reservation/decision evidence stays in existing private records. WORKPLACE_POLICY.md lines 11 and 33, together with existing AGENTS.md source-mediation rules, retain HA-only production scope and do not create broad private-source access. Cross-project management does not confer production source rights.
10. **Unrelated pending work retained: PASS.** Root STATUS.md, root CHECKS_STATUS.md and dev/continuous_execution/STATUS.md each retain their complete baseline content byte-for-byte after the new amendment entry and separator. The new workplace STATUS.md covers only this amendment. Older static, source, runtime, provider, test and release pending obligations are not cleared or represented as newly accepted.
11. **No live success assertion: PASS.** The amendment repeatedly distinguishes policy/configuration from matched execution, useful output and consumption. WORKPLACE_POLICY.md lines 49–57 retains safe same-ID transfers, actual new-run evidence and separate staffing versus quality acceptance. No new permanent-worker count, deployed scheduler, successful dispatch or release is certified.

## Completion and remaining obligations

This PASS is restricted to the exact documentation delta and its scoped pending records above. HA remains paused. It is not acceptance of live scheduling, staffing, runtime, tests, native providers, integrations, source code or a release.

The reviewer performed no repository mutations, software tests, Actions, scheduling changes, worker activation or deployment. Private runtime reports were not used as evidence for this public review.

The integration owner may save this report and remove only the pending lines/row for the **2026-11-09 full-time peer bootstrap and conditional last-two-position staffing policy** in the same closure commit. Remove a scoped STATUS.md only if it is empty after that scoped removal. Preserve all earlier pending material and reports. Later substantive instruction changes require review of their changed scope; the absence of a marker alone is not acceptance.

